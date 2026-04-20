from fastapi import APIRouter
from app.db import get_conn

router = APIRouter()

@router.get("/stores/{store_id}/metrics")
def get_metrics(store_id: str):
    with get_conn() as conn:
        c = conn.cursor()

        # unique visitors (exclude staff)
        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id=? AND is_staff=0
        """, (store_id,))
        visitors = c.fetchone()[0] or 0

        # visitors who reached billing
        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id=? AND zone_id='BILLING' AND is_staff=0
        """, (store_id,))
        billing = c.fetchone()[0] or 0

        conversion = (billing / visitors) if visitors > 0 else 0

        # avg dwell
        c.execute("""
        SELECT zone_id, AVG(dwell_ms)
        FROM events
        WHERE store_id=? AND dwell_ms > 0
        GROUP BY zone_id
        """, (store_id,))
        dwell = {row[0]: row[1] for row in c.fetchall()}

    return {
        "visitors": visitors,
        "conversion_rate": conversion,
        "avg_dwell": dwell
    }