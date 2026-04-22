# pipeline/emit.py
import uuid
from datetime import datetime


class EventEmitter:
    def __init__(self, store_id, camera_id, camera_type):
        self.store_id = store_id
        self.camera_id = camera_id
        self.camera_type = camera_type

        self.sessions = {}

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
                "seq": 1,
                "entry_time": now,
                "last_dwell_emit": now,
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
        events = []
        now = self._now_ms()

        for t in tracks:
            if not t["is_valid"]:
                continue

            gid = t["global_id"]
            s = self._get_session(gid)

            # -------- ENTRY --------
            if self.camera_type == "ENTRY":
                if t.get("crossed") and t.get("direction") in ("ENTRY", "EXIT"):
                    evt_type = t["direction"]
                    if evt_type == "ENTRY":
                        s["entered"] = True
                        s["entry_time"] = now
                        s["visitor_id"] = f"VIS_{gid}"
                        s["id_source"] = "entry_line"
                    else:
                        s["entered"] = False
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
                dwell = now - s["entry_time"]

                if now - s["last_dwell_emit"] >= self.DWELL_INTERVAL_MS:
                    visitor_id, id_source = self._ensure_visitor_id(gid, s)
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
                dwell = now - s["entry_time"]

                if now - s["last_dwell_emit"] >= self.DWELL_INTERVAL_MS:
                    visitor_id, id_source = self._ensure_visitor_id(gid, s)
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

        return events