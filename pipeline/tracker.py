# pipeline/tracker.py
import numpy as np
import supervision as sv


class SmartTracker:
    def __init__(self):
        self.tracker = sv.ByteTrack()

        self.track_first_seen = {}
        self.track_last_seen = {}
        self.track_last_pos = {}

        self.track_to_global = {}
        self.global_last_seen = {}
        self.global_last_pos = {}

        self.next_gid = 0
        self.frame_count = 0

        # rules
        self.TTL = 50
        self.MAX_DIST = 150
        self.MIN_FRAMES = 15

    def _center(self, b):
        x1, y1, x2, y2 = b
        return ((x1 + x2)//2, (y1 + y2)//2)

    def _dist(self, p1, p2):
        return np.linalg.norm(np.array(p1) - np.array(p2))

    def _recover_gid(self, c):
        best_id, best_d = None, float("inf")
        for gid, pos in self.global_last_pos.items():
            if self.frame_count - self.global_last_seen.get(gid, 0) > self.TTL:
                continue
            d = self._dist(pos, c)
            if d < best_d and d < self.MAX_DIST:
                best_d, best_id = d, gid
        return best_id

    def update(self, detections):
        self.frame_count += 1
        if not detections:
            return []

        det_sv = sv.Detections(
            xyxy=np.array([d["bbox"] for d in detections]),
            confidence=np.array([d["confidence"] for d in detections]),
            class_id=np.zeros(len(detections))
        )

        tracks = self.tracker.update_with_detections(det_sv)
        out = []

        for box, tid in zip(tracks.xyxy, tracks.tracker_id):
            x1, y1, x2, y2 = map(int, box)
            c = self._center((x1, y1, x2, y2))

            if tid not in self.track_first_seen:
                self.track_first_seen[tid] = self.frame_count

            self.track_last_seen[tid] = self.frame_count
            self.track_last_pos[tid] = c

            if tid in self.track_to_global:
                gid = self.track_to_global[tid]
            else:
                rec = self._recover_gid(c)
                if rec is not None:
                    gid = rec
                else:
                    self.next_gid += 1
                    gid = self.next_gid
                self.track_to_global[tid] = gid

            self.global_last_seen[gid] = self.frame_count
            self.global_last_pos[gid] = c

            duration = self.frame_count - self.track_first_seen[tid]

            out.append({
                "global_id": gid,
                "bbox": [x1, y1, x2, y2],
                "center": c,
                "duration": duration,
                "is_valid": duration >= self.MIN_FRAMES
            })
        return out

    # ------------------ TODOs (future) ------------------
    def detect_direction(self, track):
        """TODO: ENTRY vs EXIT via motion across a line."""
        return "UNKNOWN"

    def detect_reentry(self, track):
        """TODO: detect REENTRY using prior EXIT + same identity."""
        return False