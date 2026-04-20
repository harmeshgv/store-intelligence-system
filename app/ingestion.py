from fastapi import APIRouter
from typing import List
from app.models import Event
from app.db import get_conn

router = APIRouter()

@router.post("/events/ingest")
def ingest_events(events: List[Event]):
    inserted = 0
    skipped = 0

    with get_conn() as conn:
        c = conn.cursor()

        for e in events:
            try:
                c.execute("""
                INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    e.event_id,
                    e.store_id,
                    e.camera_id,
                    e.visitor_id,
                    e.event_type,
                    e.timestamp,
                    e.zone_id,
                    e.dwell_ms,
                    int(e.is_staff),
                    e.confidence
                ))
                inserted += 1
            except:
                skipped += 1  # duplicate or bad

        conn.commit()

    return {
        "inserted": inserted,
        "skipped": skipped
    }