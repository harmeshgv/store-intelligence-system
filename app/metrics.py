import sqlite3

from fastapi import APIRouter, HTTPException

from app.db import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/metrics")
def get_metrics(store_id: str):
    try:
        with get_conn() as conn:
            c = conn.cursor()
            today_filter = "date(timestamp) = date('now')"

            c.execute(
                f"""
                SELECT COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=? AND is_staff=0 AND {today_filter}
                """,
                (store_id,),
            )
            visitors = c.fetchone()[0] or 0

            c.execute(
                f"""
                SELECT COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND is_staff=0
                AND event_type='BILLING_QUEUE_JOIN'
                AND {today_filter}
                """,
                (store_id,),
            )
            converted_visitors = c.fetchone()[0] or 0

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
            avg_dwell_per_zone = {zone: round(avg or 0, 2) for zone, avg in c.fetchall()}

            c.execute(
                f"""
                SELECT
                    COALESCE(
                        CAST(json_extract(metadata, '$.queue_depth') AS INTEGER),
                        0
                    )
                FROM events
                WHERE store_id=?
                AND event_type='BILLING_QUEUE_JOIN'
                AND {today_filter}
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (store_id,),
            )
            q_row = c.fetchone()
            queue_depth = q_row[0] if q_row else 0

            c.execute(
                f"""
                SELECT COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND is_staff=0
                AND event_type='BILLING_QUEUE_JOIN'
                AND {today_filter}
                """,
                (store_id,),
            )
            billing_visitors = c.fetchone()[0] or 0

            c.execute(
                f"""
                SELECT COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND is_staff=0
                AND event_type='BILLING_QUEUE_ABANDON'
                AND {today_filter}
                """,
                (store_id,),
            )
            abandoned_visitors = c.fetchone()[0] or 0

            return {
                "unique_visitors": visitors,
                "conversion_rate": round(
                    (converted_visitors / visitors) if visitors else 0.0, 4
                ),
                "avg_dwell_per_zone": avg_dwell_per_zone,
                "queue_depth": queue_depth,
                "abandonment_rate": round(
                    (abandoned_visitors / billing_visitors) if billing_visitors else 0.0, 4
                ),
            }
    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "Unable to compute metrics",
            },
        )