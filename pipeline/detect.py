# pipeline/detect.py
from ultralytics import YOLO


class Detector:
    def __init__(self, model_path="yolov8s.pt", conf=0.4):
        self.model = YOLO(model_path)
        self.conf = conf

    def detect(self, frame):
        results = self.model(frame, conf=self.conf)[0]

        dets = []
        for box in results.boxes:
            cls = int(box.cls[0])
            if cls != 0:  # person only
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])

            dets.append({
                "bbox": [x1, y1, x2, y2],
                "confidence": conf
            })
        return dets

    # ------------------ TODOs (future) ------------------
    def detect_staff(self, crop):
        """TODO: classify staff (uniform / model)."""
        return False