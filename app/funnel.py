import sqlite3

from fastapi import APIRouter, HTTPException

from app.db import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/funnel")
def get_funnel(store_id: str):
    try:
        with get_conn() as conn:
            c = conn.cursor()
            today_filter = "date(timestamp) = date('now')"

            c.execute(
                f"""
                SELECT DISTINCT visitor_id
                FROM events
                WHERE store_id=?
                AND event_type IN ('ENTRY', 'REENTRY')
                AND is_staff=0
                AND {today_filter}
                """,
                (store_id,),
            )
            entry_set = {row[0] for row in c.fetchall()}

            c.execute(
                f"""
                SELECT DISTINCT visitor_id
                FROM events
                WHERE store_id=?
                AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
                AND is_staff=0
                AND {today_filter}
                """,
                (store_id,),
            )
            zone_set = {row[0] for row in c.fetchall()}

            c.execute(
                f"""
                SELECT DISTINCT visitor_id
                FROM events
                WHERE store_id=?
                AND event_type='BILLING_QUEUE_JOIN'
                AND is_staff=0
                AND {today_filter}
                """,
                (store_id,),
            )
            billing_set = {row[0] for row in c.fetchall()}

            c.execute(
                f"""
                SELECT DISTINCT visitor_id
                FROM events
                WHERE store_id=?
                AND event_type='BILLING_QUEUE_JOIN'
                AND is_staff=0
                AND {today_filter}
                """,
                (store_id,),
            )
            purchase_set = {row[0] for row in c.fetchall()}

            entry_count = len(entry_set)
            zone_count = len(entry_set & zone_set)
            billing_count = len(entry_set & zone_set & billing_set)
            purchase_count = len(entry_set & zone_set & billing_set & purchase_set)

            def pct(num: int, den: int) -> float:
                return round((num / den) * 100, 2) if den else 0.0

            return {
                "counts": {
                    "entry": entry_count,
                    "zone_visit": zone_count,
                    "billing_queue": billing_count,
                    "purchase": purchase_count,
                },
                "drop_off_pct": {
                    "entry_to_zone": pct(entry_count - zone_count, entry_count),
                    "zone_to_billing": pct(zone_count - billing_count, zone_count),
                    "billing_to_purchase": pct(
                        billing_count - purchase_count, billing_count
                    ),
                },
            }
    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "Unable to compute funnel",
            },
        )