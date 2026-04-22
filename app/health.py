from datetime import datetime, timezone
import sqlite3

from fastapi import APIRouter, HTTPException

from app.db import get_conn

router = APIRouter()

STALE_THRESHOLD_SECONDS = 600  # 10 minutes


@router.get("/health")
def health():
    now_utc = datetime.now(timezone.utc)

    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT store_id, MAX(timestamp)
                FROM events
                GROUP BY store_id
                """
            )
            rows = c.fetchall()

            stores = {}
            stale_feed = []
            for store_id, last_timestamp in rows:
                lag_seconds = None
                warning = None
                if last_timestamp:
                    dt = datetime.fromisoformat(last_timestamp.replace("Z", "+00:00"))
                    lag_seconds = int((now_utc - dt).total_seconds())
                    if lag_seconds > STALE_THRESHOLD_SECONDS:
                        warning = "STALE_FEED"
                        stale_feed.append(store_id)

                stores[store_id] = {
                    "last_event_timestamp": last_timestamp,
                    "lag_seconds": lag_seconds,
                    "warning": warning,
                }

            return {
                "status": "DEGRADED" if stale_feed else "OK",
                "stores": stores,
                "stale_feed_stores": stale_feed,
            }
    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "Unable to run health checks",
            },
        )