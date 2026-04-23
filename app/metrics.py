import sqlite3
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.db import get_conn

router = APIRouter()
POS_PATH = Path("data/pos_transactions.csv")


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _converted_visitors_from_pos(c, store_id: str) -> int:
    if not POS_PATH.exists():
        return -1

    # All billing presence events for this store (used for 5-minute pre-transaction linking).
    c.execute(
        """
        SELECT visitor_id, timestamp
        FROM events
        WHERE store_id=?
        AND is_staff=0
        AND event_type IN ('BILLING_QUEUE_JOIN', 'ZONE_DWELL', 'ZONE_ENTER')
        AND zone_id='BILLING'
        """,
        (store_id,),
    )
    billing_rows = c.fetchall()
    visitor_times: dict[str, list[datetime]] = {}
    for row in billing_rows:
        try:
            visitor_times.setdefault(row[0], []).append(_parse_iso(row[1]))
        except Exception:
            continue
    if not visitor_times:
        return 0

    today = datetime.now(timezone.utc).date()
    converted_visitors: set[str] = set()
    with POS_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            if rec.get("store_id") != store_id:
                continue
            ts = rec.get("timestamp")
            if not ts:
                continue
            try:
                txn_time = _parse_iso(ts)
            except Exception:
                continue
            if txn_time.date() != today:
                continue
            low = txn_time - timedelta(minutes=5)
            for visitor_id, moments in visitor_times.items():
                if any(low <= m <= txn_time for m in moments):
                    converted_visitors.add(visitor_id)
    return len(converted_visitors)


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

            converted_visitors = _converted_visitors_from_pos(c, store_id)
            if converted_visitors < 0:
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