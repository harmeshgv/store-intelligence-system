"""
PROMPT:
Need focused unit tests for pipeline pieces so overall coverage can go above target
without touching heavy video runtime flow.

CHANGES MADE:
- Added emitter tests for entry/exit, floor dwell, billing queue, invalid/godown paths.
- Added tracker tests with mocked supervision backend (empty, none-id, gid recovery, crossing).
- Added detector tests with mocked YOLO so class-filter logic is tested fast.
- Kept tests lightweight and deterministic (no real model/video dependency).
"""

from __future__ import annotations

import numpy as np

from pipeline import detect as detect_module
from pipeline.emit import EventEmitter
from pipeline import tracker as tracker_module


def test_emitter_entry_flow_emits_entry_and_exit():
    emitter = EventEmitter("STORE_X", "CAM_ENTRY_01", "ENTRY")
    tracks = [{"is_valid": True, "global_id": 7, "crossed": True, "direction": "ENTRY"}]
    events = emitter.process(tracks)
    assert len(events) == 1
    assert events[0]["event_type"] == "ENTRY"
    assert events[0]["visitor_id"] == "VIS_7"
    assert events[0]["metadata"]["id_source"] == "entry_line"

    exit_events = emitter.process(
        [{"is_valid": True, "global_id": 7, "crossed": True, "direction": "EXIT"}]
    )
    assert len(exit_events) == 1
    assert exit_events[0]["event_type"] == "EXIT"


def test_emitter_floor_and_billing_emit_periodic_events():
    floor = EventEmitter("STORE_X", "CAM_FLOOR_01", "FLOOR")
    floor.DWELL_INTERVAL_MS = 1
    floor.process([{"is_valid": True, "global_id": 10}])
    floor.sessions[10]["last_dwell_emit"] = 0
    events = floor.process([{"is_valid": True, "global_id": 10}])
    assert len(events) == 1
    assert events[0]["event_type"] == "ZONE_DWELL"
    assert events[0]["zone_id"] == "FLOOR"
    assert events[0]["metadata"]["id_source"] == "fallback_non_entry"

    billing = EventEmitter("STORE_X", "CAM_BILLING_01", "BILLING")
    billing.DWELL_INTERVAL_MS = 1
    billing.process([{"is_valid": True, "global_id": 11}])
    billing.sessions[11]["last_dwell_emit"] = 0
    billing_events = billing.process([{"is_valid": True, "global_id": 11}])
    assert len(billing_events) == 1
    assert billing_events[0]["event_type"] == "BILLING_QUEUE_JOIN"
    assert billing_events[0]["zone_id"] == "BILLING"


def test_emitter_godown_and_invalid_tracks_emit_nothing():
    godown = EventEmitter("STORE_X", "CAM_GODOWN_01", "GODOWN")
    events = godown.process([{"is_valid": True, "global_id": 99}])
    assert events == []

    entry = EventEmitter("STORE_X", "CAM_ENTRY_01", "ENTRY")
    no_events = entry.process([{"is_valid": False, "global_id": 1, "crossed": True, "direction": "ENTRY"}])
    assert no_events == []


def test_emitter_private_helpers_cover_paths():
    emitter = EventEmitter("STORE_X", "CAM_ENTRY_01", "ENTRY")
    session = emitter._get_session(3)
    visitor_id, source = emitter._ensure_visitor_id(3, session)
    assert visitor_id == "VIS_3"
    assert source == "entry_line"
    # Cached path
    visitor_id2, source2 = emitter._ensure_visitor_id(3, session)
    assert visitor_id2 == visitor_id
    assert source2 == source

    evt = emitter._evt(3, "ENTRY", None, 0, 1, visitor_id=visitor_id, id_source=source)
    assert evt["store_id"] == "STORE_X"
    assert evt["camera_id"] == "CAM_ENTRY_01"
    assert evt["metadata"]["session_seq"] == 1


class _FakeTracks:
    def __init__(self, xyxy, tracker_id):
        self.xyxy = xyxy
        self.tracker_id = tracker_id


class _FakeByteTrack:
    def __init__(self):
        self._queue = []

    def queue(self, result):
        self._queue.append(result)

    def update_with_detections(self, _detections):
        if self._queue:
            return self._queue.pop(0)
        return _FakeTracks(np.array([[0, 0, 10, 10]]), np.array([1]))


def _patch_tracker_backend(monkeypatch):
    fake = _FakeByteTrack()
    monkeypatch.setattr(tracker_module.sv, "ByteTrack", lambda: fake)
    monkeypatch.setattr(tracker_module.sv, "Detections", lambda **kwargs: kwargs)
    return fake


def test_tracker_basic_and_empty_paths(monkeypatch):
    fake = _patch_tracker_backend(monkeypatch)
    trk = tracker_module.SmartTracker()
    assert trk.update([]) == []

    fake.queue(_FakeTracks(np.array([[10, 10, 20, 20]]), np.array([101])))
    out = trk.update([{"bbox": [10, 10, 20, 20], "confidence": 0.9}])
    assert len(out) == 1
    assert out[0]["global_id"] == 1
    assert out[0]["is_valid"] is False


def test_tracker_handles_none_tracker_id(monkeypatch):
    fake = _patch_tracker_backend(monkeypatch)
    trk = tracker_module.SmartTracker()
    fake.queue(_FakeTracks(np.array([[10, 10, 20, 20]]), None))
    out = trk.update([{"bbox": [10, 10, 20, 20], "confidence": 0.8}])
    assert out == []


def test_tracker_gid_recovery_and_direction_helpers(monkeypatch):
    _patch_tracker_backend(monkeypatch)
    trk = tracker_module.SmartTracker(entry_line=((0, 0), (0, 10)), inside_sign=1, crossing_cooldown_frames=0)
    trk.MIN_FRAMES = 0
    trk.MAX_DIST = 1000

    # First detection creates gid=1 at x<0 side.
    trk.tracker._queue = [_FakeTracks(np.array([[-10, 1, -2, 9]]), np.array([1]))]
    out1 = trk.update([{"bbox": [-10, 1, -2, 9], "confidence": 0.9}])
    assert out1[0]["crossed"] is False

    # New tracker id appears near previous point -> recovered gid=1.
    trk.tracker._queue = [_FakeTracks(np.array([[2, 1, 10, 9]]), np.array([2]))]
    out2 = trk.update([{"bbox": [2, 1, 10, 9], "confidence": 0.9}])
    assert out2[0]["global_id"] == 1
    assert out2[0]["crossed"] is True
    assert out2[0]["direction"] in ("ENTRY", "EXIT")

    assert trk.detect_direction({}) == "UNKNOWN"
    assert trk.detect_reentry({}) is False


def test_tracker_math_helpers(monkeypatch):
    _patch_tracker_backend(monkeypatch)
    trk = tracker_module.SmartTracker()
    assert trk._center((0, 0, 10, 10)) == (5, 5)
    assert int(trk._dist((0, 0), (3, 4))) == 5
    assert trk._side_of_line((1, 1), (0, 0), (2, 0)) != 0


class _FakeScalar:
    def __init__(self, value):
        self.value = value

    def __getitem__(self, _idx):
        return self.value


class _FakeXY:
    def __init__(self, vals):
        self.vals = vals

    def __getitem__(self, _idx):
        return self

    def tolist(self):
        return self.vals


class _FakeBox:
    def __init__(self, cls_id, conf, xyxy):
        self.cls = _FakeScalar(cls_id)
        self.conf = _FakeScalar(conf)
        self.xyxy = _FakeXY(xyxy)


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class _FakeYOLO:
    def __init__(self, _model_path):
        pass

    def __call__(self, _frame, conf):
        assert conf == 0.4
        return [
            _FakeResult(
                [
                    _FakeBox(0, 0.91, [1, 2, 11, 22]),  # person
                    _FakeBox(2, 0.75, [5, 6, 15, 26]),  # non-person, filtered
                ]
            )
        ]


def test_detector_detect_filters_person_class(monkeypatch):
    monkeypatch.setattr(detect_module, "YOLO", _FakeYOLO)
    det = detect_module.Detector(model_path="fake.pt", conf=0.4)
    out = det.detect(frame=np.zeros((10, 10, 3), dtype=np.uint8))
    assert len(out) == 1
    assert out[0]["bbox"] == [1, 2, 11, 22]
    assert out[0]["confidence"] == 0.91
    assert det.detect_staff(None) is False
