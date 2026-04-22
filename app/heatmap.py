import sqlite3

from fastapi import APIRouter, HTTPException

from app.db import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/heatmap")
def get_heatmap(store_id: str):
    try:
        with get_conn() as conn:
            c = conn.cursor()
            today_filter = "date(timestamp) = date('now')"

            c.execute(
                f"""
                SELECT zone_id, COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND zone_id IS NOT NULL
                AND is_staff=0
                AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
                AND {today_filter}
                GROUP BY zone_id
                """,
                (store_id,),
            )
            visits = {row[0]: row[1] for row in c.fetchall()}

            c.execute(
                f"""
                SELECT zone_id, AVG(dwell_ms)
                FROM events
                WHERE store_id=?
                AND zone_id IS NOT NULL
                AND is_staff=0
                AND event_type='ZONE_DWELL'
                AND dwell_ms > 0
                AND {today_filter}
                GROUP BY zone_id
                """,
                (store_id,),
            )
            dwell = {row[0]: (row[1] or 0) for row in c.fetchall()}

            zones = sorted(set(visits.keys()) | set(dwell.keys()))
            combined_scores = {}
            for zone in zones:
                combined_scores[zone] = visits.get(zone, 0) * (dwell.get(zone, 0) / 1000.0)

            max_score = max(combined_scores.values()) if combined_scores else 0
            heatmap = []
            for zone in zones:
                normalized = (
                    round((combined_scores[zone] / max_score) * 100, 2) if max_score else 0.0
                )
                heatmap.append(
                    {
                        "zone_id": zone,
                        "visit_frequency": visits.get(zone, 0),
                        "avg_dwell_ms": round(dwell.get(zone, 0), 2),
                        "normalized_score": normalized,
                    }
                )

            c.execute(
                f"""
                SELECT COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND is_staff=0
                AND {today_filter}
                """,
                (store_id,),
            )
            sessions = c.fetchone()[0] or 0

            return {
                "store_id": store_id,
                "zones": heatmap,
                "data_confidence": "LOW" if sessions < 20 else "HIGH",
                "session_count": sessions,
            }
    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "Unable to compute heatmap",
            },
        )