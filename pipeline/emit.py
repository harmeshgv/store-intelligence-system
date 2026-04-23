# pipeline/emit.py
import uuid
from datetime import datetime


class EventEmitter:
    def __init__(self, store_id, camera_id, camera_type):
        self.store_id = store_id
        self.camera_id = camera_id
        self.camera_type = camera_type

        self.sessions = {}
        self.tick = 0

        self.DWELL_INTERVAL_MS = 30000

    def _ts(self):
        return datetime.utcnow().isoformat(timespec="seconds") + "Z"

    def _now_ms(self):
        return int(datetime.utcnow().timestamp() * 1000)

    def _evt(self, gid, etype, zone, dwell, seq, conf=0.9, visitor_id=None, id_source=None):
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,  # ✅ always fixed
            "camera_id": self.camera_id,
            "visitor_id": visitor_id or f"VIS_{gid}",
            "event_type": etype,
            "timestamp": self._ts(),
            "zone_id": zone,
            "dwell_ms": dwell,
            "is_staff": False,
            "confidence": conf,
            "metadata": {
                "queue_depth": None,
                "sku_zone": zone,
                "session_seq": seq,
                "id_source": id_source,
                "confidence_tier": "LOW" if id_source == "fallback_non_entry" else "HIGH",
            }
        }

    def _get_session(self, gid):
        if gid not in self.sessions:
            now = self._now_ms()
            self.sessions[gid] = {
                "entered": False,
                "exited_once": False,
                "seq": 1,
                "entry_time": now,
                "zone_enter_time": now,
                "last_dwell_emit": now,
                "last_seen_tick": self.tick,
                "in_zone": False,
                "billing_joined": False,
                "visitor_id": None,
                "id_source": None,
            }
        return self.sessions[gid]

    def _ensure_visitor_id(self, gid, session):
        if session["visitor_id"]:
            return session["visitor_id"], session["id_source"]

        # For entry camera, keep stable identity-style id.
        if self.camera_type == "ENTRY":
            session["visitor_id"] = f"VIS_{gid}"
            session["id_source"] = "entry_line"
            return session["visitor_id"], session["id_source"]

        # For non-entry cameras, assign fallback session id and continue.
        short = uuid.uuid4().hex[:8]
        session["visitor_id"] = f"VIS_FALLBACK_{self.camera_id}_{short}"
        session["id_source"] = "fallback_non_entry"
        return session["visitor_id"], session["id_source"]

    def process(self, tracks):
        self.tick += 1
        events = []
        now = self._now_ms()
        seen_gids = set()

        for t in tracks:
            if not t["is_valid"]:
                continue

            gid = t["global_id"]
            seen_gids.add(gid)
            s = self._get_session(gid)
            s["last_seen_tick"] = self.tick

            # -------- ENTRY --------
            if self.camera_type == "ENTRY":
                if t.get("crossed") and t.get("direction") in ("ENTRY", "EXIT"):
                    evt_type = t["direction"]
                    if evt_type == "ENTRY":
                        s["entered"] = True
                        s["entry_time"] = now
                        s["visitor_id"] = f"VIS_{gid}"
                        s["id_source"] = "entry_line"
                        if s["exited_once"]:
                            evt_type = "REENTRY"
                    else:
                        s["entered"] = False
                        s["exited_once"] = True
                    visitor_id, id_source = self._ensure_visitor_id(gid, s)
                    events.append(
                        self._evt(
                            gid, evt_type, None, 0, s["seq"],
                            visitor_id=visitor_id, id_source=id_source
                        )
                    )
                    s["seq"] += 1

            # -------- FLOOR --------
            elif self.camera_type == "FLOOR":
                visitor_id, id_source = self._ensure_visitor_id(gid, s)
                if not s["in_zone"]:
                    s["in_zone"] = True
                    s["zone_enter_time"] = now
                    events.append(
                        self._evt(
                            gid, "ZONE_ENTER", "FLOOR", 0, s["seq"],
                            visitor_id=visitor_id, id_source=id_source
                        )
                    )
                    s["seq"] += 1
                dwell = now - s["zone_enter_time"]

                if now - s["last_dwell_emit"] >= self.DWELL_INTERVAL_MS:
                    events.append(
                        self._evt(
                            gid, "ZONE_DWELL", "FLOOR", dwell, s["seq"],
                            visitor_id=visitor_id, id_source=id_source
                        )
                    )
                    s["last_dwell_emit"] = now
                    s["seq"] += 1

            # -------- BILLING --------
            elif self.camera_type == "BILLING":
                visitor_id, id_source = self._ensure_visitor_id(gid, s)
                if not s["in_zone"]:
                    s["in_zone"] = True
                    s["zone_enter_time"] = now
                    events.append(
                        self._evt(
                            gid, "ZONE_ENTER", "BILLING", 0, s["seq"],
                            visitor_id=visitor_id, id_source=id_source
                        )
                    )
                    s["seq"] += 1
                    queue_evt = self._evt(
                        gid, "BILLING_QUEUE_JOIN", "BILLING", 0, s["seq"],
                        visitor_id=visitor_id, id_source=id_source
                    )
                    # Simple online estimate: everyone currently visible in billing except self.
                    queue_evt["metadata"]["queue_depth"] = max(0, len(seen_gids) - 1)
                    events.append(queue_evt)
                    s["billing_joined"] = True
                    s["seq"] += 1
                dwell = now - s["zone_enter_time"]

                if now - s["last_dwell_emit"] >= self.DWELL_INTERVAL_MS:
                    events.append(
                        self._evt(
                            gid, "BILLING_QUEUE_JOIN", "BILLING", dwell, s["seq"],
                            visitor_id=visitor_id, id_source=id_source
                        )
                    )
                    s["last_dwell_emit"] = now
                    s["seq"] += 1

            # -------- GODOWN --------
            elif self.camera_type == "GODOWN":
                pass

        if self.camera_type in ("FLOOR", "BILLING"):
            for gid, s in self.sessions.items():
                if not s.get("in_zone"):
                    continue
                # treat missing for 2 consecutive process cycles as zone leave
                if gid in seen_gids:
                    continue
                if (self.tick - s.get("last_seen_tick", self.tick)) < 2:
                    continue
                visitor_id, id_source = self._ensure_visitor_id(gid, s)
                zone = "BILLING" if self.camera_type == "BILLING" else "FLOOR"
                if self.camera_type == "BILLING" and s.get("billing_joined"):
                    events.append(
                        self._evt(
                            gid, "BILLING_QUEUE_ABANDON", zone, 0, s["seq"],
                            visitor_id=visitor_id, id_source=id_source
                        )
                    )
                    s["seq"] += 1
                events.append(
                    self._evt(
                        gid, "ZONE_EXIT", zone, 0, s["seq"],
                        visitor_id=visitor_id, id_source=id_source
                    )
                )
                s["seq"] += 1
                s["in_zone"] = False
                s["billing_joined"] = False

        return events