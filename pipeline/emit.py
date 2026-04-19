# pipeline/emit.py
import uuid
from datetime import datetime

class EventEmitter:
    def __init__(self, store_id, camera_id):
        self.store_id = store_id
        self.camera_id = camera_id
        self.active_sessions = {}

    def _timestamp(self):
        return datetime.utcnow().isoformat() + "Z"

    def create_event(self, visitor_id, event_type, zone_id=None, confidence=1.0):
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "visitor_id": f"VIS_{visitor_id}",
            "event_type": event_type,
            "timestamp": self._timestamp(),
            "zone_id": zone_id,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": confidence,
            "metadata": {
                "queue_depth": None,
                "sku_zone": zone_id,
                "session_seq": 1
            }
        }