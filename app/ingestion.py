import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.db import get_conn
from app.models import Event

router = APIRouter()
MAX_BATCH_SIZE = 500


@router.post("/events/ingest")
def ingest_events(events: list[dict[str, Any]]):
    if len(events) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "batch_too_large",
                "message": f"Batch size must be <= {MAX_BATCH_SIZE}",
            },
        )

    inserted = 0
    duplicate = 0
    malformed = 0
    errors: list[dict[str, Any]] = []

    try:
        with get_conn() as conn:
            c = conn.cursor()

            for idx, raw_event in enumerate(events):
                event_id = raw_event.get("event_id")
                try:
                    event = Event(**raw_event)
                except ValidationError as ex:
                    malformed += 1
                    errors.append(
                        {
                            "index": idx,
                            "event_id": event_id,
                            "reason": "validation_error",
                            "details": ex.errors(),
                        }
                    )
                    continue

                try:
                    c.execute(
                        """
                        INSERT INTO events (
                            event_id,
                            store_id,
                            camera_id,
                            visitor_id,
                            event_type,
                            timestamp,
                            zone_id,
                            dwell_ms,
                            is_staff,
                            confidence,
                            metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            event.store_id,
                            event.camera_id,
                            event.visitor_id,
                            event.event_type,
                            event.timestamp,
                            event.zone_id,
                            event.dwell_ms,
                            int(event.is_staff),
                            event.confidence,
                            json.dumps(event.metadata) if event.metadata else None,
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    duplicate += 1
                    errors.append(
                        {
                            "index": idx,
                            "event_id": event.event_id,
                            "reason": "duplicate",
                        }
                    )
            conn.commit()
    except sqlite3.Error:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "database_unavailable",
                "message": "Unable to write events at the moment",
            },
        )

    return {
        "received": len(events),
        "inserted": inserted,
        "skipped": duplicate + malformed,
        "duplicate": duplicate,
        "malformed": malformed,
        "errors": errors,
    }