from detect import Detector
from tracker import SimpleTracker
from emit import EventEmitter
import cv2
import json

def main():
    detector = Detector()
    tracker = SimpleTracker()
    emitter = EventEmitter("STORE_BLR_002", "CAM_ENTRY_01")

    cap = cv2.VideoCapture("data/CAM 4.mp4")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 1️⃣ Detect
        detections = detector.detect(frame)

        # 2️⃣ Track
        tracks = tracker.update(detections)

        # 3️⃣ Process each tracked person
        for t in tracks:
            x1, y1, x2, y2 = map(int, t["bbox"])
            track_id = t["track_id"]
            conf = t["confidence"]

            # 4️⃣ Create event (for now: simple ENTRY event)
            event = emitter.create_event(
                visitor_id=track_id,
                event_type="ENTRY",
                confidence=conf
            )

            # Print event (later → save to file)
            print(json.dumps(event))

            # 5️⃣ Draw bounding box + ID
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
            cv2.putText(frame, f"ID:{track_id}", (x1, y1-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)

        cv2.imshow("Frame", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()