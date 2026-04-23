import cv2
import argparse
from datetime import datetime
from ultralytics import YOLO
import supervision as sv
import numpy as np

DEFAULT_DOOR_LINE = ((1357, 256), (627, 1078))


# ---------------- Geometry ----------------
def side_of_line(p, a, b):
    # cross product sign: >0 one side, <0 other side
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def mmss_from_frame(frame_idx, fps):
    if fps <= 0:
        return "00:00"
    sec = int(frame_idx / fps)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def fit_to_screen(img, max_w=1280, max_h=720):
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale < 1.0:
        return cv2.resize(img, (int(w * scale), int(h * scale))), scale
    return img, 1.0


# ---------------- Main ----------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path to video, e.g. data/CAM 3.mp4")
    parser.add_argument("--model", default="yolov8s.pt")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--min-frames", type=int, default=8, help="Track warmup before counting")
    parser.add_argument("--max-dist", type=float, default=180.0)
    parser.add_argument("--ttl", type=int, default=50)
    parser.add_argument("--max-width", type=int, default=1280, help="Viewer max width")
    parser.add_argument("--max-height", type=int, default=720, help="Viewer max height")
    args = parser.parse_args()

    model = YOLO(args.model)
    tracker = sv.ByteTrack()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open video: {args.video}")
        return

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

    # Interactive line drawing
    line_pts = [DEFAULT_DOOR_LINE[0], DEFAULT_DOOR_LINE[1]]
    drawing_done = True

    # Track memory
    frame_count = 0
    track_first_seen = {}
    track_prev_center = {}
    track_last_cross_frame = {}

    # Global ID recovery memory (similar to your current pipeline)
    track_to_gid = {}
    gid_last_pos = {}
    gid_last_seen = {}
    next_gid = 0

    entry_count = 0
    exit_count = 0
    crossing_log = []  # (time_str, event_type, gid)

    # Convention:
    # side_of_line(...) > 0  => LEFT side of directed line a->b
    # side_of_line(...) < 0  => RIGHT side of directed line a->b
    INSIDE_SIGN = 1   # LEFT side is INSIDE
    OUTSIDE_SIGN = -1 # RIGHT side is OUTSIDE

    click_scale = 1.0

    def mouse_cb(event, x, y, flags, param):
        nonlocal line_pts, drawing_done, click_scale
        if drawing_done:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            ox = int(x / click_scale)
            oy = int(y / click_scale)
            ox = max(0, min(ox, first.shape[1] - 1))
            oy = max(0, min(oy, first.shape[0] - 1))
            if len(line_pts) < 2:
                line_pts.append((ox, oy))
            if len(line_pts) == 2:
                drawing_done = True

    cv2.namedWindow("Entry Line Calibrator", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Entry Line Calibrator", args.max_width, args.max_height)
    cv2.setMouseCallback("Entry Line Calibrator", mouse_cb)

    # ---------- Step 1: freeze first frame and draw line ----------
    ret, first = cap.read()
    if not ret:
        print("[ERROR] Cannot read first frame.")
        return

    while True:
        canvas = first.copy()
        cv2.putText(canvas, "Default door line loaded. Press r to redraw", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(canvas, "Press Enter to continue calibration", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        for p in line_pts:
            cv2.circle(canvas, p, 6, (0, 0, 255), -1)
        if len(line_pts) == 2:
            cv2.line(canvas, line_pts[0], line_pts[1], (0, 255, 255), 2)

        shown, click_scale = fit_to_screen(canvas, args.max_width, args.max_height)
        cv2.imshow("Entry Line Calibrator", shown)
        k = cv2.waitKey(20) & 0xFF
        if k == ord('r'):
            line_pts = []
            drawing_done = False
        elif k == 13 and len(line_pts) == 2:  # Enter
            break
        elif k == ord('q'):
            cap.release()
            cv2.destroyAllWindows()
            return

    print(f"[INFO] Door line points: {line_pts[0]}, {line_pts[1]}")

    print("\n[INFO] Direction mapping fixed:")
    print("  LEFT side of line  -> INSIDE")
    print("  RIGHT side of line -> OUTSIDE")

    # rewind video
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # ---------- Step 2: live detect + track + crossing ----------
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        results = model(frame, conf=args.conf, verbose=False)[0]

        dets = []
        for box in results.boxes:
            cls = int(box.cls[0])
            if cls != 0:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            dets.append({"bbox": [x1, y1, x2, y2], "confidence": conf})

        if dets:
            det_sv = sv.Detections(
                xyxy=np.array([d["bbox"] for d in dets]),
                confidence=np.array([d["confidence"] for d in dets]),
                class_id=np.zeros(len(dets))
            )
            tracks = tracker.update_with_detections(det_sv)
        else:
            tracks = sv.Detections.empty()

        # draw line
        a, b = line_pts
        cv2.line(frame, a, b, (0, 255, 255), 2)

        if tracks is None or tracks.tracker_id is None or len(tracks.xyxy) == 0:
            track_pairs = []
        else:
            track_pairs = zip(tracks.xyxy, tracks.tracker_id)

        for box, tid in track_pairs:
            x1, y1, x2, y2 = map(int, box)
            c = ((x1 + x2) // 2, (y1 + y2) // 2)

            if tid not in track_first_seen:
                track_first_seen[tid] = frame_count

            # lightweight gid map
            if tid not in track_to_gid:
                # nearest recent gid
                best_gid = None
                best_d = 1e9
                for gid, p in gid_last_pos.items():
                    if frame_count - gid_last_seen.get(gid, 0) > args.ttl:
                        continue
                    d = np.linalg.norm(np.array(c) - np.array(p))
                    if d < best_d and d < args.max_dist:
                        best_d = d
                        best_gid = gid
                if best_gid is None:
                    next_gid += 1
                    track_to_gid[tid] = next_gid
                else:
                    track_to_gid[tid] = best_gid

            gid = track_to_gid[tid]
            gid_last_pos[gid] = c
            gid_last_seen[gid] = frame_count

            duration = frame_count - track_first_seen[tid]
            is_valid = duration >= args.min_frames

            color = (0, 220, 0) if is_valid else (0, 0, 220)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.circle(frame, c, 4, color, -1)
            cv2.putText(frame, f"GID {gid}", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

            # crossing logic
            if is_valid and gid in track_prev_center:
                p_prev = track_prev_center[gid]
                s1 = side_of_line(p_prev, a, b)
                s2 = side_of_line(c, a, b)

                # crossed if sign changed
                if s1 == 0:
                    s1 = 1e-6
                if s2 == 0:
                    s2 = -1e-6

                sign1 = 1 if s1 > 0 else -1
                sign2 = 1 if s2 > 0 else -1

                crossed = sign1 != sign2
                cooldown_ok = (frame_count - track_last_cross_frame.get(gid, -9999)) > int(fps * 1.0)

                if crossed and cooldown_ok:
                    # moving to INSIDE side => ENTRY
                    if sign2 == INSIDE_SIGN:
                        event = "ENTRY"
                        entry_count += 1
                    else:
                        event = "EXIT"
                        exit_count += 1

                    track_last_cross_frame[gid] = frame_count
                    t = mmss_from_frame(frame_count, fps)
                    crossing_log.append((t, event, gid))
                    print(f"[{t}] {event} | GID {gid}")

            track_prev_center[gid] = c

        # overlay
        cv2.rectangle(frame, (10, 10), (460, 130), (20, 20, 20), -1)
        cv2.putText(frame, f"ENTRY: {entry_count}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(frame, f"EXIT: {exit_count}", (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 128, 255), 2)
        cv2.putText(frame, f"Frame: {frame_count}  Time: {mmss_from_frame(frame_count, fps)}", (20, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, "q=quit  space=pause", (20, 123),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
        cv2.putText(frame, "INSIDE: LEFT of line | OUTSIDE: RIGHT of line", (20, 146),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # recent event
        if crossing_log:
            t, ev, gid = crossing_log[-1]
            cv2.putText(frame, f"Last: [{t}] {ev} GID {gid}", (20, 175),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        shown, _ = fit_to_screen(frame, args.max_width, args.max_height)
        cv2.imshow("Entry Line Calibrator", shown)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        if key == ord(" "):
            while True:
                k2 = cv2.waitKey(0) & 0xFF
                if k2 in (ord(" "), ord("q")):
                    key = k2
                    break
            if key == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()

    print("\n========== Crossing Summary ==========")
    print(f"Line points: {line_pts[0]}, {line_pts[1]}")
    print(f"ENTRY total: {entry_count}")
    print(f"EXIT total: {exit_count}")
    print("Recent events:")
    for row in crossing_log[-20:]:
        print(row)
    print("======================================")


if __name__ == "__main__":
    main()