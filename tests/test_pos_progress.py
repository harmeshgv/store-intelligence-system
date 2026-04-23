# PROMPT:
# Add focused tests to improve coverage on new POS-correlation and progress endpoints.
# Keep tests deterministic and lightweight, using temporary CSV files and isolated store ids.
#
# CHANGES MADE:
# - Added progress endpoint tests for validation, defaults, and sorted camera output.
# - Added metrics POS-correlation test using a temporary pos_transactions.csv.
# - Added funnel POS-correlation test to verify purchase stage from POS matching window.

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import app.funnel as funnel_module
import app.metrics as metrics_module
from app.db import get_conn
from app.main import app

client = TestClient(app)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cleanup_store(store_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM events WHERE store_id=?", (store_id,))
        conn.commit()


def _ingest(events: list[dict]):
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200


def _event(event_id: str, store_id: str, visitor_id: str, event_type: str, ts: str, zone_id=None):
    return {
        "event_id": event_id,
        "store_id": store_id,
        "camera_id": "CAM_BILLING_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": ts,
        "zone_id": zone_id,
        "dwell_ms": 1000,
        "is_staff": False,
        "confidence": 0.9,
        "metadata": {"queue_depth": 1, "session_seq": 1},
    }


def test_progress_endpoints_validation_and_sorted_output():
    bad = client.post("/pipeline/progress", json={"store_id": "S1"})
    assert bad.status_code == 400

    r1 = client.post(
        "/pipeline/progress",
        json={
            "store_id": "STORE_PROG_TEST",
            "camera_id": "CAM_B",
            "elapsed_sec": 11,
            "duration_sec": 100,
            "progress_pct": 11,
        },
    )
    assert r1.status_code == 200
    assert r1.json()["ok"] is True

    r2 = client.post(
        "/pipeline/progress",
        json={
            "store_id": "STORE_PROG_TEST",
            "camera_id": "CAM_A",
            "status": "RUNNING",
        },
    )
    assert r2.status_code == 200

    out = client.get("/stores/STORE_PROG_TEST/progress")
    assert out.status_code == 200
    body = out.json()
    cams = body["cameras"]
    assert [c["camera_id"] for c in cams] == ["CAM_A", "CAM_B"]
    assert cams[0]["status"] == "RUNNING"


def test_metrics_uses_pos_correlation_when_file_available(tmp_path, monkeypatch):
    store_id = "STORE_POS_METRICS"
    _cleanup_store(store_id)
    now = datetime.now(timezone.utc)

    # visitor in billing within 5 minutes before txn
    events = [
        _event("pm_1", store_id, "VIS_1", "ENTRY", _iso(now - timedelta(minutes=4))),
        _event(
            "pm_2",
            store_id,
            "VIS_1",
            "BILLING_QUEUE_JOIN",
            _iso(now - timedelta(minutes=3)),
            zone_id="BILLING",
        ),
        # another visitor without billing evidence
        _event("pm_3", store_id, "VIS_2", "ENTRY", _iso(now - timedelta(minutes=2))),
    ]
    _ingest(events)

    pos_file = tmp_path / "pos_transactions.csv"
    pos_file.write_text(
        "store_id,transaction_id,timestamp,basket_value_inr\n"
        f"{store_id},TXN_1,{_iso(now - timedelta(minutes=1))},899.00\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics_module, "POS_PATH", Path(pos_file))

    r = client.get(f"/stores/{store_id}/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["unique_visitors"] >= 2
    # POS path should mark 1 converted out of at least 2 visitors.
    assert 0 <= body["conversion_rate"] <= 1
    assert body["conversion_rate"] > 0

    _cleanup_store(store_id)


def test_funnel_uses_pos_purchase_set_when_file_available(tmp_path, monkeypatch):
    store_id = "STORE_POS_FUNNEL"
    _cleanup_store(store_id)
    now = datetime.now(timezone.utc)

    events = [
        _event("pf_1", store_id, "VIS_P", "ENTRY", _iso(now - timedelta(minutes=6))),
        _event(
            "pf_2",
            store_id,
            "VIS_P",
            "ZONE_ENTER",
            _iso(now - timedelta(minutes=5)),
            zone_id="FLOOR",
        ),
        _event(
            "pf_3",
            store_id,
            "VIS_P",
            "BILLING_QUEUE_JOIN",
            _iso(now - timedelta(minutes=4)),
            zone_id="BILLING",
        ),
    ]
    _ingest(events)

    pos_file = tmp_path / "pos_transactions.csv"
    pos_file.write_text(
        "store_id,transaction_id,timestamp,basket_value_inr\n"
        f"{store_id},TXN_2,{_iso(now - timedelta(minutes=2))},499.00\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(funnel_module, "POS_PATH", Path(pos_file))

    r = client.get(f"/stores/{store_id}/funnel")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["entry"] >= 1
    assert body["counts"]["purchase"] >= 1

    _cleanup_store(store_id)
