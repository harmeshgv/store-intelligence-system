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


def _purchase_set_from_pos(c, store_id: str) -> set[str] | None:
    if not POS_PATH.exists():
        return None

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
    rows = c.fetchall()
    visitor_times: dict[str, list[datetime]] = {}
    for row in rows:
        try:
            visitor_times.setdefault(row[0], []).append(_parse_iso(row[1]))
        except Exception:
            continue
    if not visitor_times:
        return set()

    today = datetime.now(timezone.utc).date()
    purchase_set: set[str] = set()
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
                    purchase_set.add(visitor_id)
    return purchase_set


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

            purchase_set = _purchase_set_from_pos(c, store_id)
            if purchase_set is None:
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