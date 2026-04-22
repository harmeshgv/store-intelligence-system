from fastapi import APIRouter
from app.db import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/debug")
def debug_store(store_id: str):
    result = {
        "per_camera": {},
        "total_events": 0
    }

    with get_conn() as conn:
        c = conn.cursor()

        # get all cameras
        c.execute("""
        SELECT DISTINCT camera_id
        FROM events
        WHERE store_id=?
        """, (store_id,))
        cameras = [row[0] for row in c.fetchall()]

        total = 0

        for cam in cameras:
            c.execute("""
            SELECT COUNT(*)
            FROM events
            WHERE store_id=? AND camera_id=?
            """, (store_id, cam))

            count = c.fetchone()[0] or 0
            result["per_camera"][cam] = count
            total += count

        result["total_events"] = total

    return result