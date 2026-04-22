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

    def _evt(self, gid, etype, zone, dwell, seq, conf=0.9):
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,  # ✅ always fixed
            "camera_id": self.camera_id,
            "visitor_id": f"VIS_{gid}",
            "event_type": etype,
            "timestamp": self._ts(),
            "zone_id": zone,
            "dwell_ms": dwell,
            "is_staff": False,
            "confidence": conf,
            "metadata": {
                "queue_depth": None,
                "sku_zone": zone,
                "session_seq": seq
            }
        }

    def _get_session(self, gid):
        if gid not in self.sessions:
            now = self._now_ms()
            self.sessions[gid] = {
                "entered": False,
                "seq": 1,
                "entry_time": now,
                "last_dwell_emit": now
            }
        return self.sessions[gid]

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
                if not s["entered"]:
                    s["entered"] = True
                    s["entry_time"] = now

                    events.append(self._evt(gid, "ENTRY", None, 0, s["seq"]))
                    s["seq"] += 1

            # -------- FLOOR --------
            elif self.camera_type == "FLOOR":
                dwell = now - s["entry_time"]

                if now - s["last_dwell_emit"] >= self.DWELL_INTERVAL_MS:
                    events.append(self._evt(gid, "ZONE_DWELL", "FLOOR", dwell, s["seq"]))
                    s["last_dwell_emit"] = now
                    s["seq"] += 1

            # -------- BILLING --------
            elif self.camera_type == "BILLING":
                dwell = now - s["entry_time"]

                if now - s["last_dwell_emit"] >= self.DWELL_INTERVAL_MS:
                    events.append(
                        self._evt(gid, "BILLING_QUEUE_JOIN", "BILLING", dwell, s["seq"])
                    )
                    s["last_dwell_emit"] = now
                    s["seq"] += 1

            # -------- GODOWN --------
            elif self.camera_type == "GODOWN":
                pass

        return events