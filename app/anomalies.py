from fastapi import APIRouter
from app.db import get_conn
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/stores/{store_id}/anomalies")
def get_anomalies(store_id: str):
    anomalies = []

    with get_conn() as conn:
        c = conn.cursor()

        # 1️⃣ DEAD ZONE (no events in last 30 min)
        c.execute("""
        SELECT MAX(timestamp) FROM events WHERE store_id=?
        """, (store_id,))
        last_event = c.fetchone()[0]

        if last_event:
            last_time = datetime.fromisoformat(last_event.replace("Z",""))
            if datetime.utcnow() - last_time > timedelta(minutes=30):
                anomalies.append({
                    "type": "DEAD_ZONE",
                    "severity": "CRITICAL",
                    "suggested_action": "Check store activity or camera feed"
                })

        # 2️⃣ QUEUE SPIKE (simple logic)
        c.execute("""
        SELECT COUNT(*) FROM events
        WHERE store_id=? AND zone_id='BILLING'
        """, (store_id,))
        billing_count = c.fetchone()[0]

        if billing_count > 50:  # simple threshold
            anomalies.append({
                "type": "QUEUE_SPIKE",
                "severity": "WARN",
                "suggested_action": "Open additional billing counters"
            })

        # 3️⃣ CONVERSION DROP (simplified)
        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events WHERE store_id=? AND event_type='ENTRY'
        """, (store_id,))
        entry = c.fetchone()[0] or 0

        c.execute("""
        SELECT COUNT(DISTINCT visitor_id)
        FROM events WHERE store_id=? AND zone_id='BILLING'
        """, (store_id,))
        billing = c.fetchone()[0] or 0

        if entry > 0:
            conversion = billing / entry
            if conversion < 0.2:  # threshold
                anomalies.append({
                    "type": "CONVERSION_DROP",
                    "severity": "WARN",
                    "suggested_action": "Review pricing or staff assistance"
                })

    return anomalies