# pipeline/run.py
import os
import time
import cv2
import requests
from datetime import datetime, timezone
from threading import Thread, Lock

from detect import Detector
from tracker import SmartTracker
from emit import EventEmitter

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

MAX_BATCH_SIZE = 500
FLUSH_INTERVAL = 2.0  # seconds

lock = Lock()


# ------------------ API ------------------

def post_events(events):
    if not events:
        return

    try:
        r = requests.post(
            f"{API_BASE}/events/ingest",
            json=events,
            timeout=5
        )
        r.raise_for_status()
        print(f"[ingest] sent {len(events)} events → {r.json()}")
    except Exception as e:
        print(f"[ingest] failed: {e}")


def post_progress(store_id, camera_id, elapsed_sec, duration_sec, progress_pct, status):
    payload = {
        "store_id": store_id,
        "camera_id": camera_id,
        "elapsed_sec": elapsed_sec,
        "duration_sec": duration_sec,
        "progress_pct": progress_pct,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
    }
    try:
        requests.post(f"{API_BASE}/pipeline/progress", json=payload, timeout=2)
    except Exception:
        # Progress is best-effort telemetry; do not block video processing.
        pass


# ------------------ Batch Buffer ------------------

class BatchBuffer:
    def __init__(self, size, interval):
        self.size = size
        self.interval = interval
        self.buf = []
        self.last_flush = time.time()
        self.lock = Lock()

    def add(self, items):
        batches = []

        with self.lock:
            self.buf.extend(items)
            now = time.time()

            # 🔥 Split into multiple batches if needed
            while len(self.buf) >= self.size:
                batch = self.buf[:self.size]
                self.buf = self.buf[self.size:]
                batches.append(batch)

            # ⏱ Time-based flush
            if (now - self.last_flush) >= self.interval and self.buf:
                batches.append(self.buf[:])
                self.buf.clear()
                self.last_flush = now

        return batches

    def flush(self):
        with self.lock:
            if not self.buf:
                return []

            batch = self.buf[:]
            self.buf.clear()
            self.last_flush = time.time()
            return [batch]


# ------------------ Camera Runner ------------------

def run_camera(cam_id, cam_type, video, store_id, buffer: BatchBuffer):
    det = Detector()
    trk = SmartTracker()
    emit = EventEmitter(store_id, cam_id, cam_type)

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        print(f"[{cam_id}] ❌ cannot open {video}")
        post_progress(store_id, cam_id, 0, 0, 0, "FAILED")
        return

    print(f"[{cam_id}] 🚀 started ({cam_type}) → {video}")
    post_progress(store_id, cam_id, 0, 0, 0, "RUNNING")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    duration_sec = (total_frames / fps) if fps > 0 else 0.0
    last_progress_post = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        detections = det.detect(frame)
        tracks = trk.update(detections)
        events = emit.process(tracks)

        if events:
            batches = buffer.add(events)

            for batch in batches:
                post_events(batch)

        now = time.time()
        if now - last_progress_post >= 1.0:
            current_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES) or 0)
            elapsed_sec = (current_frame / fps) if fps > 0 else 0.0
            progress_pct = (
                min(100.0, (current_frame / total_frames) * 100.0) if total_frames > 0 else 0.0
            )
            post_progress(
                store_id,
                cam_id,
                round(elapsed_sec, 2),
                round(duration_sec, 2),
                round(progress_pct, 2),
                "RUNNING",
            )
            last_progress_post = now

    cap.release()

    # flush remaining
    remaining_batches = buffer.flush()
    for batch in remaining_batches:
        post_events(batch)

    post_progress(store_id, cam_id, round(duration_sec, 2), round(duration_sec, 2), 100.0, "DONE")

    print(f"[{cam_id}] ✅ finished")


# ------------------ Main ------------------

def main():
    store_id = os.getenv("STORE_ID", "STORE_BLR_002")

    cameras = [
        ("CAM_ENTRY_01",   "ENTRY",   "data/CAM 3.mp4"),
        ("CAM_FLOOR_01",   "FLOOR",   "data/CAM 1.mp4"),
        ("CAM_FLOOR_02",   "FLOOR",   "data/CAM 2.mp4"),
        ("CAM_BILLING_01", "BILLING", "data/CAM 5.mp4"),
        ("CAM_GODOWN_01",  "GODOWN",  "data/CAM 4.mp4"),
    ]

    buffer = BatchBuffer(MAX_BATCH_SIZE, FLUSH_INTERVAL)

    threads = []
    for cam_id, cam_type, video in cameras:
        t = Thread(
            target=run_camera,
            args=(cam_id, cam_type, video, store_id, buffer),
            daemon=True
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    # final flush
    remaining_batches = buffer.flush()
    for batch in remaining_batches:
        post_events(batch)

    print("\n🎯 All cameras processed and ingested")


if __name__ == "__main__":
    main()