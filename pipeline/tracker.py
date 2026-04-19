# pipeline/tracker.py
import math

class SimpleTracker:
    def __init__(self):
        self.next_id = 1
        self.tracks = {}

    def _center(self, bbox):
        x1, y1, x2, y2 = bbox
        return ((x1+x2)/2, (y1+y2)/2)

    def update(self, detections):
        updated_tracks = []

        for det in detections:
            cx, cy = self._center(det["bbox"])

            assigned_id = None
            for tid, prev in self.tracks.items():
                px, py = prev
                dist = math.hypot(cx-px, cy-py)

                if dist < 50:  # threshold
                    assigned_id = tid
                    break

            if assigned_id is None:
                assigned_id = self.next_id
                self.next_id += 1

            self.tracks[assigned_id] = (cx, cy)

            updated_tracks.append({
                "track_id": assigned_id,
                "bbox": det["bbox"],
                "confidence": det["confidence"]
            })

        return updated_tracks