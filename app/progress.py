from datetime import datetime, timezone
from threading import Lock
from typing import Any

from fastapi import APIRouter

router = APIRouter()

_state_lock = Lock()
_progress_state: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@router.post("/pipeline/progress")
def update_progress(payload: dict[str, Any]):
    store_id = payload.get("store_id")
    camera_id = payload.get("camera_id")
    if not store_id or not camera_id:
        return {
            "ok": False,
            "error": "store_id and camera_id are required",
        }

    record = {
        "camera_id": camera_id,
        "elapsed_sec": round(float(payload.get("elapsed_sec", 0.0)), 2),
        "duration_sec": round(float(payload.get("duration_sec", 0.0)), 2),
        "progress_pct": round(float(payload.get("progress_pct", 0.0)), 2),
        "status": str(payload.get("status", "RUNNING")),
        "updated_at": payload.get("updated_at") or _now_iso(),
    }

    with _state_lock:
        _progress_state.setdefault(store_id, {})
        _progress_state[store_id][camera_id] = record

    return {"ok": True}


@router.get("/stores/{store_id}/progress")
def get_progress(store_id: str):
    with _state_lock:
        per_cam = _progress_state.get(store_id, {})
        cameras = list(per_cam.values())

    cameras.sort(key=lambda x: x["camera_id"])
    return {
        "store_id": store_id,
        "cameras": cameras,
        "updated_at": _now_iso(),
    }
