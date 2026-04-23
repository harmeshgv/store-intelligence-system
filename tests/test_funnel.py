# tests/test_funnel.py
# PROMPT:
# Need a clean funnel test for re-entry flow.
# Main check: same visitor with ENTRY + REENTRY should not be double-counted at entry stage.
#
# CHANGES MADE:
# - Assertions follow current funnel response shape (counts + drop_off_pct).
# - Used isolated store data and event-id prefix cleanup for stable runs.
# - Added explicit re-entry dedup check for the entry stage.

import uuid
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.db import get_conn


client = TestClient(app)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cleanup_by_prefix(prefix: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM events WHERE event_id LIKE ?", (f"{prefix}%",))
        conn.commit()


def _ingest(events):
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    return r.json()


def _make_event(
    event_id: str,
    store_id: str,
    visitor_id: str,
    event_type: str,
    ts: str,
    zone_id=None,
    dwell_ms: int = 0,
):
    return {
        "event_id": event_id,
        "store_id": store_id,
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": ts,
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": None, "session_seq": 1},
    }


def test_funnel_reentry_same_visitor_not_double_counted_in_entry_stage():
    store_id = f"STORE_FUNNEL_{uuid.uuid4().hex[:8]}"
    prefix = f"tf_reentry_{uuid.uuid4().hex[:8]}_"
    _cleanup_by_prefix(prefix)

    now = datetime.now(timezone.utc)
    visitor_id = "VIS_REENTRY_001"

    events = [
        _make_event(f"{prefix}1", store_id, visitor_id, "ENTRY", _iso(now - timedelta(minutes=6))),
        _make_event(f"{prefix}2", store_id, visitor_id, "EXIT", _iso(now - timedelta(minutes=5))),
        _make_event(f"{prefix}3", store_id, visitor_id, "REENTRY", _iso(now - timedelta(minutes=4))),
        _make_event(
            f"{prefix}4", store_id, visitor_id, "ZONE_DWELL", _iso(now - timedelta(minutes=3)),
            zone_id="FLOOR", dwell_ms=30000
        ),
        _make_event(
            f"{prefix}5", store_id, visitor_id, "BILLING_QUEUE_JOIN", _iso(now - timedelta(minutes=2)),
            zone_id="BILLING", dwell_ms=10000
        ),
    ]
    _ingest(events)

    r = client.get(f"/stores/{store_id}/funnel")
    assert r.status_code == 200
    body = r.json()

    assert "counts" in body
    assert "drop_off_pct" in body
    assert body["counts"]["entry"] == 1
    assert body["counts"]["zone_visit"] == 1
    assert body["counts"]["billing_queue"] == 1
    assert body["counts"]["purchase"] == 1

    _cleanup_by_prefix(prefix)
