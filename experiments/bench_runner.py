import time
from dataclasses import asdict

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

from experiments.bench_configs import ExperimentConfig


def _center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _distance(p1, p2):
    return np.linalg.norm(np.array(p1) - np.array(p2))


def _cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6)


def _get_hist_embedding(crop):
    crop = cv2.resize(crop, (64, 128))
    crop = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([crop], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist.flatten()


def run_experiment(config: ExperimentConfig, video_path: str, frame_limit: int = 0):
    model = YOLO(config.model_path)
    tracker = sv.ByteTrack()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "ok": False,
            "error": f"Cannot open video: {video_path}",
            "config": asdict(config),
        }

    fps_video = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    frame_count = 0
    det_count = 0
    track_count = 0
    valid_track_count = 0

    next_global_id = 0
    unique_ids_seen = set()

    # Common state
    track_first_seen = {}
    track_to_global = {}
    global_last_seen = {}
    global_last_pos = {}

    # Embedding mode state
    embedding_db = {}
    external_tracker = None

    if config.mode == "deepsort":
        try:
            from deep_sort_realtime.deepsort_tracker import DeepSort
        except Exception:
            cap.release()
            return {
                "ok": False,
                "skipped": True,
                "error": "DeepSORT dependency not installed (deep_sort_realtime).",
                "config": asdict(config),
                "video_path": video_path,
            }
        external_tracker = DeepSort(max_age=config.ttl)

    if config.mode == "strongsort":
        # Common StrongSORT package availability differs by environment.
        # Keep explicit skip if dependency is unavailable.
        try:
            from boxmot import StrongSORT
        except Exception:
            cap.release()
            return {
                "ok": False,
                "skipped": True,
                "error": "StrongSORT dependency not installed (boxmot with StrongSORT).",
                "config": asdict(config),
                "video_path": video_path,
            }
        external_tracker = StrongSORT()

    t0 = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_count += 1

        if frame_limit > 0 and frame_count > frame_limit:
            break

        results = model(frame, conf=config.conf, verbose=False)[0]
        detections = sv.Detections.from_ultralytics(results)
        if detections.class_id is None or len(detections) == 0:
            continue

        detections = detections[detections.class_id == 0]
        if len(detections) == 0:
            continue
        det_count += len(detections)

        track_items = []
        if config.mode in ("distance_reid", "hist_embedding_reid"):
            tracks = tracker.update_with_detections(detections)
            if tracks is None or tracks.tracker_id is None:
                continue
            track_items = list(zip(tracks.xyxy, tracks.tracker_id))
        elif config.mode == "deepsort":
            ds_input = []
            for dbox, conf in zip(detections.xyxy, detections.confidence):
                x1, y1, x2, y2 = dbox.tolist()
                ds_input.append(([x1, y1, x2 - x1, y2 - y1], float(conf), "person"))
            ds_tracks = external_tracker.update_tracks(ds_input, frame=frame)
            for t in ds_tracks:
                if not t.is_confirmed():
                    continue
                ltrb = t.to_ltrb()
                track_items.append((np.array(ltrb), int(t.track_id)))
        elif config.mode == "strongsort":
            # Minimal callable path; depends on boxmot tensor input support.
            # If runtime call fails, return explicit skipped result.
            try:
                # Format: x1,y1,x2,y2,conf,cls
                ss_input = []
                for dbox, conf, cls_id in zip(detections.xyxy, detections.confidence, detections.class_id):
                    x1, y1, x2, y2 = dbox.tolist()
                    ss_input.append([x1, y1, x2, y2, float(conf), int(cls_id)])
                ss_input = np.array(ss_input, dtype=float) if ss_input else np.empty((0, 6), dtype=float)
                ss_tracks = external_tracker.update(ss_input, frame)
                for row in ss_tracks:
                    # common output: x1,y1,x2,y2,id,conf,cls,...
                    x1, y1, x2, y2, tid = row[:5]
                    track_items.append((np.array([x1, y1, x2, y2]), int(tid)))
            except Exception as ex:
                cap.release()
                return {
                    "ok": False,
                    "skipped": True,
                    "error": f"StrongSORT runtime path unavailable: {ex}",
                    "config": asdict(config),
                    "video_path": video_path,
                }

        for box, track_id in track_items:
            x1, y1, x2, y2 = map(int, box)
            c = _center((x1, y1, x2, y2))
            track_count += 1

            if track_id not in track_first_seen:
                track_first_seen[track_id] = frame_count
            duration = frame_count - track_first_seen[track_id]

            global_id = None
            if config.mode == "distance_reid":
                if track_id in track_to_global:
                    global_id = track_to_global[track_id]
                else:
                    best_id = None
                    best_d = float("inf")
                    for gid, pos in global_last_pos.items():
                        if frame_count - global_last_seen.get(gid, 0) > config.ttl:
                            continue
                        d = _distance(pos, c)
                        if d < best_d and d < config.max_dist:
                            best_d, best_id = d, gid
                    if best_id is None:
                        next_global_id += 1
                        best_id = next_global_id
                    track_to_global[track_id] = best_id
                    global_id = best_id
            else:
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                emb = _get_hist_embedding(crop)

                best_id = None
                best_score = 0
                for gid, old_emb in embedding_db.items():
                    if frame_count - global_last_seen.get(gid, 0) > config.ttl:
                        continue
                    prev_center = global_last_pos.get(gid, c)
                    if _distance(prev_center, c) > config.max_dist:
                        continue
                    score = _cosine_similarity(emb, old_emb)
                    if score > best_score:
                        best_score = score
                        best_id = gid

                if best_id is not None and best_score > config.reid_thresh:
                    global_id = best_id
                else:
                    next_global_id += 1
                    global_id = next_global_id
                embedding_db[global_id] = emb

            global_last_seen[global_id] = frame_count
            global_last_pos[global_id] = c

            if duration >= config.min_frames:
                valid_track_count += 1
                unique_ids_seen.add(global_id)

    elapsed = time.time() - t0
    cap.release()

    processed_frames = frame_count if frame_limit <= 0 else min(frame_count, frame_limit)
    avg_fps = (processed_frames / elapsed) if elapsed > 0 else 0.0

    return {
        "ok": True,
        "config": asdict(config),
        "video_path": video_path,
        "frame_limit": frame_limit,
        "processed_frames": processed_frames,
        "video_fps": fps_video,
        "video_total_frames": total_frames,
        "runtime_sec": round(elapsed, 3),
        "avg_fps": round(avg_fps, 3),
        "detections_total": int(det_count),
        "track_observations_total": int(track_count),
        "valid_track_observations": int(valid_track_count),
        "unique_humans_estimate": int(len(unique_ids_seen)),
    }

