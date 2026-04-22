import base64
import time
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter()

_lock = Lock()
_latest_frames: dict[str, bytes] = {}


@router.post("/stream/frame")
def push_frame(payload: dict[str, Any]):
    camera_id = payload.get("camera_id")
    frame_b64 = payload.get("frame_b64")
    if not camera_id or not frame_b64:
        raise HTTPException(status_code=400, detail="camera_id and frame_b64 are required")

    try:
        jpg_bytes = base64.b64decode(frame_b64)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Invalid frame_b64: {ex}") from ex

    with _lock:
        _latest_frames[camera_id] = jpg_bytes
    return {"ok": True}


@router.get("/stream/{camera_id}")
def stream_camera(camera_id: str):
    boundary = "frame"

    def gen():
        while True:
            with _lock:
                frame = _latest_frames.get(camera_id)
            if frame:
                yield (
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" +
                    frame + b"\r\n"
                )
            time.sleep(0.08)

    return StreamingResponse(
        gen(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
    )
