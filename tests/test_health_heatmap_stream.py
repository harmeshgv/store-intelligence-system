"""
PROMPT:
Needed quick but useful tests for health, heatmap, and stream endpoints
so these APIs are covered properly and easy to trust.

CHANGES MADE:
- Added health checks for normal, stale-feed degraded, and db-down behavior.
- Added heatmap checks for zone scoring flow and db-down fallback.
- Added stream frame validation checks (missing/invalid/valid payload).
- Kept setup simple with helper insert + clear functions for repeatable tests.
"""

from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import stream as stream_module
from app.db import get_conn
from app.main import app

client = TestClient(app)


def _clear_events() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM events")
        conn.commit()


def _insert_event(**overrides):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    event = {
        "event_id": f"evt-{now}-{overrides.get('visitor_id', 'v')}",
        "store_id": "store-123",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_1",
        "event_type": "ENTRY",
        "timestamp": now,
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {},
    }
    event.update(overrides)
    response = client.post("/events/ingest", json=[event])
    assert response.status_code == 200
    assert response.json()["inserted"] == 1


def test_health_empty_store_state_ok():
    _clear_events()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OK"
    assert body["stores"] == {}
    assert body["stale_feed_stores"] == []


def test_health_marks_stale_feed_as_degraded():
    _clear_events()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    _insert_event(store_id="store-stale", timestamp=old_ts, event_id="evt-stale")
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DEGRADED"
    assert "store-stale" in body["stale_feed_stores"]
    assert body["stores"]["store-stale"]["warning"] == "STALE_FEED"


def test_health_returns_structured_503_on_db_error(monkeypatch):
    def _raise_db_error():
        raise sqlite3.Error("db down")

    monkeypatch.setattr("app.health.get_conn", _raise_db_error)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"


def test_heatmap_returns_zone_scores():
    _clear_events()
    _insert_event(event_id="evt-z1-enter", event_type="ZONE_ENTER", zone_id="Z1", visitor_id="VIS_A")
    _insert_event(
        event_id="evt-z1-dwell",
        event_type="ZONE_DWELL",
        zone_id="Z1",
        visitor_id="VIS_A",
        dwell_ms=5000,
    )
    _insert_event(
        event_id="evt-z2-dwell",
        event_type="ZONE_DWELL",
        zone_id="Z2",
        visitor_id="VIS_B",
        dwell_ms=1000,
    )

    response = client.get("/stores/store-123/heatmap")
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == "store-123"
    assert body["data_confidence"] == "LOW"
    assert body["session_count"] >= 2
    assert len(body["zones"]) >= 2
    zone_ids = {z["zone_id"] for z in body["zones"]}
    assert {"Z1", "Z2"}.issubset(zone_ids)


def test_heatmap_returns_structured_503_on_db_error(monkeypatch):
    def _raise_db_error():
        raise sqlite3.Error("db down")

    monkeypatch.setattr("app.heatmap.get_conn", _raise_db_error)
    response = client.get("/stores/store-123/heatmap")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "database_unavailable"


def test_stream_frame_validations_and_mjpeg_output():
    missing = client.post("/stream/frame", json={"camera_id": "CAM_ENTRY_01"})
    assert missing.status_code == 400

    bad = client.post(
        "/stream/frame",
        json={"camera_id": "CAM_ENTRY_01", "frame_b64": "not-base64!"},
    )
    assert bad.status_code == 400

    frame_payload = base64.b64encode(b"fake-jpeg-data").decode("utf-8")
    ok = client.post(
        "/stream/frame",
        json={"camera_id": "CAM_ENTRY_01", "frame_b64": frame_payload},
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    stream_response = stream_module.stream_camera("CAM_ENTRY_01")
    assert "multipart/x-mixed-replace" in stream_response.media_type
