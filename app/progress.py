from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()

_lock = Lock()
_progress_by_store: dict[str, dict[str, dict[str, Any]]] = {}


@router.post("/pipeline/progress")
def upsert_progress(payload: dict[str, Any]):
    store_id = payload.get("store_id")
    camera_id = payload.get("camera_id")
    if not store_id or not camera_id:
        raise HTTPException(status_code=400, detail="store_id and camera_id are required")

    with _lock:
        store_progress = _progress_by_store.setdefault(store_id, {})
        store_progress[camera_id] = {
            "camera_id": camera_id,
            "elapsed_sec": float(payload.get("elapsed_sec") or 0.0),
            "duration_sec": float(payload.get("duration_sec") or 0.0),
            "progress_pct": float(payload.get("progress_pct") or 0.0),
            "status": payload.get("status") or "RUNNING",
            "updated_at": payload.get("updated_at"),
        }
    return {"ok": True}


@router.get("/stores/{store_id}/progress")
def get_store_progress(store_id: str):
    with _lock:
        cams = list(_progress_by_store.get(store_id, {}).values())
    cams.sort(key=lambda x: x["camera_id"])
    return {"store_id": store_id, "cameras": cams}
