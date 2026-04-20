# app/heatmap.py
from fastapi import APIRouter
from app.db import get_conn

router = APIRouter()

@router.get("/stores/{store_id}/heatmap")
def get_heatmap(store_id: str):
    with get_conn() as conn:
        c = conn.cursor()

        # 1) Distinct visitors per zone (frequency)
        c.execute("""
        SELECT zone_id, COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id=? AND zone_id IS NOT NULL AND is_staff=0
        GROUP BY zone_id
        """, (store_id,))
        visit_rows = c.fetchall()
        visits = {row[0]: row[1] for row in visit_rows}

        # 2) Avg dwell per zone (engagement)
        c.execute("""
        SELECT zone_id, AVG(dwell_ms)
        FROM events
        WHERE store_id=? AND zone_id IS NOT NULL AND dwell_ms > 0 AND is_staff=0
        GROUP BY zone_id
        """, (store_id,))
        dwell_rows = c.fetchall()
        dwell = {row[0]: (row[1] or 0) for row in dwell_rows}

        # 3) Combine into a raw score
        # simple: score = visits * avg_dwell
        scores = {}
        for z in set(list(visits.keys()) + list(dwell.keys())):
            v = visits.get(z, 0)
            d = dwell.get(z, 0)
            scores[z] = v * d

        # 4) Normalize to 0–100
        max_score = max(scores.values()) if scores else 0
        heatmap = {}
        for z, s in scores.items():
            if max_score == 0:
                heatmap[z] = 0
            else:
                heatmap[z] = round((s / max_score) * 100, 2)

        # 5) Data confidence (based on sessions)
        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events
        WHERE store_id=? AND is_staff=0
        """, (store_id,))
        sessions = c.fetchone()[0] or 0

        confidence = "LOW" if sessions < 20 else "HIGH"

    return {
        "zones": heatmap,
        "data_confidence": confidence,
        "sessions": sessions
    }