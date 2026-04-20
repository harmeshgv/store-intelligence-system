from fastapi import APIRouter
from app.db import get_conn
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/health")
def health():
    result = {
        "status": "OK",
        "stores": {}
    }

    with get_conn() as conn:
        c = conn.cursor()

        # get all stores
        c.execute("SELECT DISTINCT store_id FROM events")
        stores = [row[0] for row in c.fetchall()]

        for store in stores:
            c.execute("""
            SELECT MAX(timestamp)
            FROM events
            WHERE store_id=?
            """, (store,))
            last_event = c.fetchone()[0]

            if last_event:
                last_time = datetime.fromisoformat(last_event.replace("Z",""))
                now = datetime.utcnow()
                lag = (now - last_time).total_seconds()

                warning = None
                if lag > 600:  # 10 minutes
                    warning = "STALE_FEED"

                result["stores"][store] = {
                    "last_event_time": last_event,
                    "lag_seconds": int(lag),
                    "warning": warning
                }
            else:
                result["stores"][store] = {
                    "last_event_time": None,
                    "lag_seconds": None,
                    "warning": "NO_DATA"
                }

    return result