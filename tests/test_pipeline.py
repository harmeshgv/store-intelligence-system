# tests/test_pipeline.py
# PROMPT:
# Need strong tests for /events/ingest so real flow doesn't break.
# Covered normal insert, too big batch, duplicates, idempotency,
# malformed input, mixed payload, empty payload, and db-down case.
#
# CHANGES MADE:
# - Assertions match current API response keys: received/inserted/skipped/duplicate/malformed/errors.
# - Used unique event ids per test so tests don't clash.
# - Added cleanup + count helpers to keep runs clean and repeatable.
# - Added db row count checks to confirm duplicates are not inserted twice.
# - Added graceful 503 test for database unavailable path.

import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.db import DB_PATH, get_conn
import app.ingestion as ingestion_module


client = TestClient(app)


def _iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_event(event_id: str, **overrides):
    evt = {
        "event_id": event_id,
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_test_001",
        "event_type": "ENTRY",
        "timestamp": _iso_now(),
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.91,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    evt.update(overrides)
    return evt


def _cleanup_ids(event_ids):
    if not event_ids:
        return
    with get_conn() as conn:
        c = conn.cursor()
        placeholders = ",".join(["?"] * len(event_ids))
        c.execute(f"DELETE FROM events WHERE event_id IN ({placeholders})", event_ids)
        conn.commit()


def _count_ids(event_ids):
    if not event_ids:
        return 0
    with get_conn() as conn:
        c = conn.cursor()
        placeholders = ",".join(["?"] * len(event_ids))
        c.execute(f"SELECT COUNT(*) FROM events WHERE event_id IN ({placeholders})", event_ids)
        return c.fetchone()[0] or 0


def test_valid_batch_inserts_all_successfully():
    ids = [f"t_valid_{uuid.uuid4().hex[:10]}" for _ in range(3)]
    payload = [make_event(i) for i in ids]
    _cleanup_ids(ids)

    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 200
    body = res.json()

    assert body["received"] == 3
    assert body["inserted"] == 3
    assert body["skipped"] == 0
    assert body["duplicate"] == 0
    assert body["malformed"] == 0
    assert isinstance(body["errors"], list)

    assert _count_ids(ids) == 3
    _cleanup_ids(ids)


def test_batch_size_over_500_returns_400():
    payload = [make_event(f"t_501_{i}_{uuid.uuid4().hex[:6]}") for i in range(501)]

    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 400
    body = res.json()
    # FastAPI HTTPException with detail payload
    assert "detail" in body
    assert body["detail"]["error"] == "batch_too_large"


def test_idempotency_same_payload_twice_no_duplicate_rows():
    ids = [f"t_idem_{uuid.uuid4().hex[:10]}" for _ in range(2)]
    payload = [make_event(i) for i in ids]
    _cleanup_ids(ids)

    first = client.post("/events/ingest", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["inserted"] == 2
    assert first_body["duplicate"] == 0

    second = client.post("/events/ingest", json=payload)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["inserted"] == 0
    assert second_body["duplicate"] == 2
    assert second_body["skipped"] == 2

    # DB still has only 2 rows for those ids
    assert _count_ids(ids) == 2
    _cleanup_ids(ids)


def test_deduplication_inside_same_batch_duplicate_event_id_skipped():
    eid = f"t_dupbatch_{uuid.uuid4().hex[:10]}"
    payload = [make_event(eid), make_event(eid)]  # same event_id twice
    _cleanup_ids([eid])

    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 200
    body = res.json()

    assert body["received"] == 2
    assert body["inserted"] == 1
    assert body["duplicate"] == 1
    assert body["skipped"] == 1
    assert _count_ids([eid]) == 1

    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert "index" in err
    assert "event_id" in err
    assert err["reason"] == "duplicate"

    _cleanup_ids([eid])


def test_partial_success_valid_plus_malformed():
    good_id = f"t_partial_good_{uuid.uuid4().hex[:10]}"
    bad_id = f"t_partial_bad_{uuid.uuid4().hex[:10]}"
    _cleanup_ids([good_id, bad_id])

    malformed = make_event(bad_id)
    malformed.pop("timestamp")  # required field removed

    payload = [make_event(good_id), malformed]
    res = client.post("/events/ingest", json=payload)

    assert res.status_code == 200
    body = res.json()
    assert body["received"] == 2
    assert body["inserted"] == 1
    assert body["malformed"] == 1
    assert body["skipped"] == 1
    assert _count_ids([good_id, bad_id]) == 1

    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["event_id"] == bad_id
    assert err["reason"] == "validation_error"
    assert isinstance(err.get("details"), list)

    _cleanup_ids([good_id, bad_id])


def test_structured_response_fields_exist_and_types():
    eid = f"t_struct_{uuid.uuid4().hex[:10]}"
    _cleanup_ids([eid])

    res = client.post("/events/ingest", json=[make_event(eid)])
    assert res.status_code == 200
    body = res.json()

    for k in ["received", "inserted", "skipped", "duplicate", "malformed", "errors"]:
        assert k in body

    assert isinstance(body["received"], int)
    assert isinstance(body["inserted"], int)
    assert isinstance(body["skipped"], int)
    assert isinstance(body["duplicate"], int)
    assert isinstance(body["malformed"], int)
    assert isinstance(body["errors"], list)

    _cleanup_ids([eid])


def test_empty_batch_returns_valid_response_and_no_crash():
    res = client.post("/events/ingest", json=[])
    assert res.status_code == 200
    body = res.json()
    assert body["received"] == 0
    assert body["inserted"] == 0
    assert body["skipped"] == 0
    assert body["duplicate"] == 0
    assert body["malformed"] == 0
    assert body["errors"] == []


def test_mixed_batch_valid_duplicate_malformed_together():
    good1 = f"t_mix_good1_{uuid.uuid4().hex[:10]}"
    good2 = f"t_mix_good2_{uuid.uuid4().hex[:10]}"
    dup = f"t_mix_dup_{uuid.uuid4().hex[:10]}"
    bad = f"t_mix_bad_{uuid.uuid4().hex[:10]}"
    _cleanup_ids([good1, good2, dup, bad])

    # Create existing duplicate by inserting once first
    pre = client.post("/events/ingest", json=[make_event(dup)])
    assert pre.status_code == 200
    assert pre.json()["inserted"] == 1

    malformed = make_event(bad)
    malformed.pop("visitor_id")

    payload = [
        make_event(good1),
        make_event(good2),
        make_event(dup),   # duplicate against existing DB row
        malformed,         # malformed
    ]

    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 200
    body = res.json()

    assert body["received"] == 4
    assert body["inserted"] == 2
    assert body["duplicate"] == 1
    assert body["malformed"] == 1
    assert body["skipped"] == 2

    # DB should contain only pre-existing dup + 2 new valid
    assert _count_ids([good1, good2, dup, bad]) == 3

    reasons = sorted(e["reason"] for e in body["errors"])
    assert reasons == ["duplicate", "validation_error"]

    _cleanup_ids([good1, good2, dup, bad])


def test_ingest_database_unavailable_returns_structured_503(monkeypatch):
    eid = f"t_db_down_{uuid.uuid4().hex[:10]}"
    payload = [make_event(eid)]

    def _boom():
        raise sqlite3.Error("db down")

    monkeypatch.setattr(ingestion_module, "get_conn", _boom)
    res = client.post("/events/ingest", json=payload)

    assert res.status_code == 503
    body = res.json()
    assert "detail" in body
    assert body["detail"]["error"] == "database_unavailable"
    assert "message" in body["detail"]