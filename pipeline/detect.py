# pipeline/detect.py
from ultralytics import YOLO
import cv2

class Detector:
    def __init__(self, model_path="yolov8n.pt"):
        self.model = YOLO(model_path)

    def detect(self, frame):
        results = self.model(frame)[0]
        detections = []

        for box in results.boxes:
            cls = int(box.cls[0])
            if cls != 0:  # 0 = person
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])

            detections.append({
                "bbox": [x1, y1, x2, y2],
                "confidence": conf
            })

        return detections

