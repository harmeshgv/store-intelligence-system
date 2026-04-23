from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    model_path: str
    conf: float
    mode: str  # "distance_reid" | "hist_embedding_reid"
    ttl: int = 50
    max_dist: float = 150.0
    min_frames: int = 15
    reid_thresh: float = 0.7


DEFAULT_EXPERIMENTS = [
    ExperimentConfig(
        name="yolov8s_distance_reid",
        model_path="yolov8s.pt",
        conf=0.40,
        mode="distance_reid",
        ttl=50,
        max_dist=150.0,
        min_frames=15,
    ),
    ExperimentConfig(
        name="yolov8m_distance_reid",
        model_path="yolov8m.pt",
        conf=0.40,
        mode="distance_reid",
        ttl=50,
        max_dist=150.0,
        min_frames=15,
    ),
    ExperimentConfig(
        name="yolov8s_hist_embedding_reid",
        model_path="yolov8s.pt",
        conf=0.40,
        mode="hist_embedding_reid",
        ttl=50,
        max_dist=150.0,
        min_frames=15,
        reid_thresh=0.70,
    ),
    ExperimentConfig(
        name="yolov8s_deepsort",
        model_path="yolov8s.pt",
        conf=0.40,
        mode="deepsort",
        ttl=50,
        max_dist=150.0,
        min_frames=15,
    ),
    ExperimentConfig(
        name="yolov8s_strongsort",
        model_path="yolov8s.pt",
        conf=0.40,
        mode="strongsort",
        ttl=50,
        max_dist=150.0,
        min_frames=15,
    ),
]

