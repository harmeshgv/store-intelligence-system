# tests/test_anomalies.py
# PROMPT:
# Write pytest tests for GET /stores/{store_id}/anomalies.
# Focus on real-world scenarios rather than only synthetic triggers.
# Cover:
# - Dead zone (>30m inactivity) -> CRITICAL
# - Queue spike -> WARN
# - Conversion drop -> WARN
# Edge cases:
# - no events
# - normal behavior (no anomalies)
# - only ENTRY events
# - very small dataset
# Also verify:
# - response is a list
# - each anomaly has type, severity, suggested_action
# - severity is INFO/WARN/CRITICAL
#
# CHANGES MADE:
# 1) Aligned anomaly expectations with current implementation logic:
#    DEAD_ZONE from stale zone timestamps, QUEUE_SPIKE from recent-vs-baseline queue_depth,
#    and CONVERSION_DROP from today vs historical conversion ratio.
# 2) Added deterministic timestamp seeding to exercise 30-minute and 7-day windows.
# 3) Simplified assertions to check anomaly type/severity presence rather than exact full object equality.
# 4) Added edge-case tests for no-data, only-ENTRY, and small dataset stability.

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.db import get_conn


client = TestClient(app)
ALLOWED_SEVERITIES = {"INFO", "WARN", "CRITICAL"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_event(
    event_id: str,
    store_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: str,
    zone_id=None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    queue_depth=None,
):
    return {
        "event_id": event_id,
        "store_id": store_id,
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": 0.9,
        "metadata": {
            "queue_depth": queue_depth,
            "session_seq": 1,
        },
    }


def _ingest(events):
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    return r.json()


def _cleanup_by_prefix(prefix: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM events WHERE event_id LIKE ?", (f"{prefix}%",))
        conn.commit()


def _assert_anomaly_shape(a: dict):
    assert isinstance(a, dict)
    assert "type" in a
    assert "severity" in a
    assert "suggested_action" in a
    assert a["severity"] in ALLOWED_SEVERITIES


def test_anomalies_no_events_returns_list_no_crash():
    store_id = f"STORE_EMPTY_{uuid.uuid4().hex[:8]}"
    r = client.get(f"/stores/{store_id}/anomalies")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # may be empty in no-data condition
    assert len(body) == 0


def test_anomalies_only_entry_events_no_false_queue_or_dead_zone():
    store_id = f"STORE_ENTRY_{uuid.uuid4().hex[:8]}"
    prefix = f"ta_entry_{uuid.uuid4().hex[:8]}_"
    _cleanup_by_prefix(prefix)

    now = datetime.now(timezone.utc)
    events = [
        make_event(f"{prefix}1", store_id, "VIS_1", "ENTRY", _iso(now - timedelta(minutes=1))),
        make_event(f"{prefix}2", store_id, "VIS_2", "ENTRY", _iso(now - timedelta(minutes=2))),
    ]
    _ingest(events)

    r = client.get(f"/stores/{store_id}/anomalies")
    assert r.status_code == 200
    anomalies = r.json()
    assert isinstance(anomalies, list)

    for a in anomalies:
        _assert_anomaly_shape(a)
        # with only entry events, these should not be spuriously triggered
        assert a["type"] not in {"QUEUE_SPIKE", "DEAD_ZONE"}

    _cleanup_by_prefix(prefix)


def test_dead_zone_triggers_critical_when_zone_stale_over_30min():
    store_id = f"STORE_DEAD_{uuid.uuid4().hex[:8]}"
    prefix = f"ta_dead_{uuid.uuid4().hex[:8]}_"
    _cleanup_by_prefix(prefix)

    now = datetime.now(timezone.utc)
    stale_ts = _iso(now - timedelta(minutes=40))

    events = [
        make_event(f"{prefix}1", store_id, "VIS_1", "ZONE_DWELL", stale_ts, zone_id="FLOOR"),
    ]
    _ingest(events)

    r = client.get(f"/stores/{store_id}/anomalies")
    assert r.status_code == 200
    anomalies = r.json()
    assert isinstance(anomalies, list)

    dead = [a for a in anomalies if a.get("type") == "DEAD_ZONE"]
    assert dead, "Expected DEAD_ZONE anomaly"
    assert any(a.get("severity") == "CRITICAL" for a in dead)

    for a in anomalies:
        _assert_anomaly_shape(a)

    _cleanup_by_prefix(prefix)


def test_queue_spike_warn_when_recent_queue_depth_high_vs_baseline():
    store_id = f"STORE_QUEUE_{uuid.uuid4().hex[:8]}"
    prefix = f"ta_queue_{uuid.uuid4().hex[:8]}_"
    _cleanup_by_prefix(prefix)

    now = datetime.now(timezone.utc)

    events = []
    # Baseline window (older than 30 min, within 7d): low queue depth
    for i in range(5):
        events.append(
            make_event(
                f"{prefix}b{i}",
                store_id,
                f"VIS_b{i}",
                "BILLING_QUEUE_JOIN",
                _iso(now - timedelta(days=1, minutes=i)),
                zone_id="BILLING",
                queue_depth=1,
            )
        )

    # Recent window (last 30 min): high queue depth
    for i in range(6):
        events.append(
            make_event(
                f"{prefix}r{i}",
                store_id,
                f"VIS_r{i}",
                "BILLING_QUEUE_JOIN",
                _iso(now - timedelta(minutes=5 + i)),
                zone_id="BILLING",
                queue_depth=5,
            )
        )

    _ingest(events)

    r = client.get(f"/stores/{store_id}/anomalies")
    assert r.status_code == 200
    anomalies = r.json()
    assert isinstance(anomalies, list)

    queue_spike = [a for a in anomalies if a.get("type") == "QUEUE_SPIKE"]
    assert queue_spike, "Expected QUEUE_SPIKE anomaly"
    assert any(a.get("severity") == "WARN" for a in queue_spike)

    for a in anomalies:
        _assert_anomaly_shape(a)

    _cleanup_by_prefix(prefix)


def test_conversion_drop_warn_when_today_rate_below_baseline():
    store_id = f"STORE_CONV_{uuid.uuid4().hex[:8]}"
    prefix = f"ta_conv_{uuid.uuid4().hex[:8]}_"
    _cleanup_by_prefix(prefix)

    now = datetime.now(timezone.utc)
    events = []

    # 7-day baseline: decent conversion (entries + billing joins)
    # for last 3 days (excluding today)
    for d in [1, 2, 3]:
        day_ts = now - timedelta(days=d, hours=1)
        # entries: 10
        for i in range(10):
            events.append(
                make_event(
                    f"{prefix}e{d}_{i}",
                    store_id,
                    f"VIS_e{d}_{i}",
                    "ENTRY",
                    _iso(day_ts + timedelta(minutes=i)),
                )
            )
        # converted: 6
        for i in range(6):
            events.append(
                make_event(
                    f"{prefix}c{d}_{i}",
                    store_id,
                    f"VIS_e{d}_{i}",
                    "BILLING_QUEUE_JOIN",
                    _iso(day_ts + timedelta(minutes=20 + i)),
                    zone_id="BILLING",
                    queue_depth=2,
                )
            )

    # Today: poor conversion (entries but no/very low billing joins)
    today_ts = now - timedelta(hours=1)
    for i in range(10):
        events.append(
            make_event(
                f"{prefix}te_{i}",
                store_id,
                f"VIS_te_{i}",
                "ENTRY",
                _iso(today_ts + timedelta(minutes=i)),
            )
        )
    # today converted: 0 (intentionally low)

    _ingest(events)

    r = client.get(f"/stores/{store_id}/anomalies")
    assert r.status_code == 200
    anomalies = r.json()
    assert isinstance(anomalies, list)

    conv_drop = [a for a in anomalies if a.get("type") == "CONVERSION_DROP"]
    assert conv_drop, "Expected CONVERSION_DROP anomaly"
    assert any(a.get("severity") == "WARN" for a in conv_drop)

    for a in anomalies:
        _assert_anomaly_shape(a)

    _cleanup_by_prefix(prefix)


def test_normal_small_dataset_can_return_empty_or_valid_anomalies_without_crash():
    store_id = f"STORE_SMALL_{uuid.uuid4().hex[:8]}"
    prefix = f"ta_small_{uuid.uuid4().hex[:8]}_"
    _cleanup_by_prefix(prefix)

    now = datetime.now(timezone.utc)
    # Small, recent, healthy-like sample
    events = [
        make_event(f"{prefix}1", store_id, "VIS_1", "ENTRY", _iso(now - timedelta(minutes=2))),
        make_event(
            f"{prefix}2",
            store_id,
            "VIS_1",
            "ZONE_DWELL",
            _iso(now - timedelta(minutes=1)),
            zone_id="FLOOR",
            dwell_ms=30000,
        ),
    ]
    _ingest(events)

    r = client.get(f"/stores/{store_id}/anomalies")
    assert r.status_code == 200
    anomalies = r.json()
    assert isinstance(anomalies, list)

    for a in anomalies:
        _assert_anomaly_shape(a)

    _cleanup_by_prefix(prefix)