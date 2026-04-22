from datetime import datetime, timedelta, timezone
import sqlite3

from fastapi import APIRouter, HTTPException

from app.db import get_conn

router = APIRouter()


@router.get("/stores/{store_id}/anomalies")
def get_anomalies(store_id: str):
    anomalies = []
    now_utc = datetime.now(timezone.utc)

    def parse_ts(ts: str | None) -> datetime | None:
        if not ts:
            return None
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    try:
        with get_conn() as conn:
            c = conn.cursor()
            today_filter = "date(timestamp) = date('now')"

            c.execute(
                """
                SELECT zone_id, MAX(timestamp)
                FROM events
                WHERE store_id=?
                AND is_staff=0
                AND zone_id IS NOT NULL
                GROUP BY zone_id
                """,
                (store_id,),
            )
            for zone_id, last_event in c.fetchall():
                last_time = parse_ts(last_event)
                if last_time and (now_utc - last_time) > timedelta(minutes=30):
                    anomalies.append(
                        {
                            "type": "DEAD_ZONE",
                            "severity": "CRITICAL",
                            "zone_id": zone_id,
                            "suggested_action": "Inspect merchandising and camera coverage for this zone.",
                        }
                    )

            c.execute(
                f"""
                SELECT AVG(COALESCE(CAST(json_extract(metadata, '$.queue_depth') AS INTEGER), 0))
                FROM events
                WHERE store_id=?
                AND event_type='BILLING_QUEUE_JOIN'
                AND datetime(timestamp) >= datetime('now', '-30 minutes')
                """,
                (store_id,),
            )
            recent_queue_avg = c.fetchone()[0] or 0

            c.execute(
                f"""
                SELECT AVG(COALESCE(CAST(json_extract(metadata, '$.queue_depth') AS INTEGER), 0))
                FROM events
                WHERE store_id=?
                AND event_type='BILLING_QUEUE_JOIN'
                AND datetime(timestamp) < datetime('now', '-30 minutes')
                AND datetime(timestamp) >= datetime('now', '-7 day')
                """,
                (store_id,),
            )
            baseline_queue_avg = c.fetchone()[0] or 0

            if recent_queue_avg >= 3 and recent_queue_avg > (baseline_queue_avg * 1.5):
                anomalies.append(
                    {
                        "type": "QUEUE_SPIKE",
                        "severity": "WARN",
                        "suggested_action": "Open another billing counter or redeploy floor staff.",
                    }
                )

            c.execute(
                f"""
                SELECT COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND event_type IN ('ENTRY', 'REENTRY')
                AND is_staff=0
                AND {today_filter}
                """,
                (store_id,),
            )
            today_entries = c.fetchone()[0] or 0

            c.execute(
                f"""
                SELECT COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND event_type='BILLING_QUEUE_JOIN'
                AND is_staff=0
                AND {today_filter}
                """,
                (store_id,),
            )
            today_converted = c.fetchone()[0] or 0
            today_conversion = (today_converted / today_entries) if today_entries else 0.0

            c.execute(
                """
                SELECT date(timestamp), COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND event_type IN ('ENTRY', 'REENTRY')
                AND is_staff=0
                AND datetime(timestamp) >= datetime('now', '-7 day')
                GROUP BY date(timestamp)
                """,
                (store_id,),
            )
            entries_by_day = {row[0]: row[1] for row in c.fetchall()}

            c.execute(
                """
                SELECT date(timestamp), COUNT(DISTINCT visitor_id)
                FROM events
                WHERE store_id=?
                AND event_type='BILLING_QUEUE_JOIN'
                AND is_staff=0
                AND datetime(timestamp) >= datetime('now', '-7 day')
                GROUP BY date(timestamp)
                """,
                (store_id,),
            )
            converted_by_day = {row[0]: row[1] for row in c.fetchall()}

            daily_rates = []
            for day, day_entries in entries_by_day.items():
                if day_entries:
                    daily_rates.append(converted_by_day.get(day, 0) / day_entries)
            baseline_conversion = sum(daily_rates) / len(daily_rates) if daily_rates else 0.0

            if baseline_conversion and today_conversion < (baseline_conversion * 0.7):
                anomalies.append(
                    {
                        "type": "CONVERSION_DROP",
                        "severity": "WARN",
                        "suggested_action": "Audit billing wait times and high-dwell zones for friction.",
                    }
                )

            return anomalies
    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "Unable to compute anomalies",
            },
        )