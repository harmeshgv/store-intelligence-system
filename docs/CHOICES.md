# CHOICES.md

This document records three concrete implementation choices for this take-home:
1. detection + tracking stack
2. event schema design
3. API architecture

For each decision, I show options considered, what AI suggested, what I chose, and why.

---

## Dataset Scope and Constraint Note

This implementation and benchmark evidence are based on the camera clips available in the working dataset package.

- No synthetic/fake side files were created to mimic missing artifacts.
- Decisions were optimized for clip-driven event quality, API stability, and explainability.
- Where richer side-data integration is relevant (for example tighter conversion attribution), that is documented as an explicit next-step path.

---

## Decision 1: Detection Model Selection

### Problem
I needed a practical pipeline that can detect people reliably enough for store analytics, keep IDs stable enough for session-level metrics, and still run fast enough to support live dashboard updates.

### Options Considered
- **Option A:** `yolov8s` + ByteTrack + distance-rule Re-ID
- **Option B:** `yolov8m` + ByteTrack + distance-rule Re-ID
- **Option C:** `yolov8s` + ByteTrack + histogram embedding Re-ID
- **Option D:** DeepSORT / StrongSORT family (considered for comparison path)

### What AI Suggested
AI suggested starting from YOLOv8 + ByteTrack baseline, then adding conservative rules before introducing heavy appearance Re-ID. It also suggested comparing `yolov8s` and `yolov8m` on the same clip with fixed frame budget and logging runtime + unique-count behavior.

### What I Implemented
Benchmark scripts under `experiments/`:
- `bench_configs.py`
- `bench_runner.py`
- `run_all_experiments.py`

Two saved result files (same configs, different scope):
- **Single-clip run:** `experiments/final_experiment_data.json` — quick sanity on entry-style clip (`data/CAM 3.mp4`), **450 frames**.
- **Multi-clip run:** `experiments/final_experiment_data_multi.json` — all five clips, **900 frames** each (generated `2026-04-22T21:41:19Z`).

### How to read the benchmark tables
Each row is one **(video × config)** run from `bench_runner.py`.

| Column | Meaning |
|--------|--------|
| **Config** | Experiment name: detector size (`yolov8s` / `yolov8m`), tracker mode (`distance_reid`, `hist_embedding_reid`), or optional trackers (`deepsort`, `strongsort`). |
| **Frames** | How many frames were processed in that run (fixed cap for fair comparison). |
| **Avg FPS** | Throughput: `processed_frames / runtime_sec`. Higher means the laptop can keep up better with live-ish processing. |
| **Detections** | Total person detections counted over the run (proxy for “how busy” the model thinks the scene is). |
| **Unique humans estimate** | Heuristic distinct global IDs from the benchmark harness — useful for **relative** comparison between configs, not ground-truth people count. |


---

### Benchmark A — single clip (fast check)
**File:** `experiments/final_experiment_data.json`  
**Video:** `data/CAM 3.mp4` only  
**Frames:** 450 per config

| Config | Frames | Avg FPS | Detections | Unique humans estimate | Notes |
|---|---:|---:|---:|---:|---|
| `yolov8s_distance_reid` | 450 | 10.257 | 113 | 4 | Fast baseline |
| `yolov8m_distance_reid` | 450 | 4.639 | 453 | 4 | More raw detections, much slower, same heuristic unique count |
| `yolov8s_hist_embedding_reid` | 450 | 10.269 | 113 | 7 | Similar FPS, higher unique estimate → identity fragmentation / inflation risk |

---

### Benchmark B — multi clip (stress across all cameras)
**File:** `experiments/final_experiment_data_multi.json`  
**Videos:** `data/CAM 1.mp4` … `data/CAM 5.mp4`  
**Frames:** 900 per (video × config)

Per-video summary (**Avg FPS / unique humans estimate**) for the three runnable configs:

| Video | `yolov8s_distance_reid` | `yolov8m_distance_reid` | `yolov8s_hist_embedding_reid` |
|--------|---------------------------|---------------------------|----------------------------------|
| CAM 1 | 9.643 / 8 | 4.355 / 7 | 9.344 / 13 |
| CAM 2 | 8.396 / 10 | 4.176 / 7 | 8.973 / 27 |
| CAM 3 | 8.561 / 6 | 4.019 / 6 | 9.638 / 10 |
| CAM 4 | 0.548 / 1 | 1.875 / 0 | 3.359 / 3 |
| CAM 5 | 3.083 / 3 | 1.692 / 3 | 3.352 / 6 |

**What this multi-clip table shows:**
- **`yolov8s_distance_reid`** keeps the best **FPS** on every clip vs `yolov8m`, which matters when several cameras run together (`pipeline/run.py`).
- **`yolov8m_distance_reid`** is often **2× slower or worse** for similar or lower unique estimates on the same clip (e.g. CAM 1–3).
- **`yolov8s_hist_embedding_reid`** repeatedly inflates **unique** vs distance mode on crowded floor clips (CAM 2: **27** vs **10**), which would hurt session-level analytics if used in production.
- CAM 4 `yolov8s` is an outlier on **FPS** in this run (~0.55 FPS over 900 frames); treat as **hardware + clip** sensitivity, not a reason to switch the whole stack to a heavier model without profiling.


---

### Final choice (what the repo actually runs)
**Implemented in the main pipeline:** **YOLOv8s** + **ByteTrack** + **distance-rule Re-ID** (`TTL`, `MAX_DIST`, `MIN_FRAMES`), plus **entry line-crossing** for `ENTRY` / `EXIT` / `REENTRY` semantics.

This matches the benchmark config name **`yolov8s_distance_reid`**.

### Why this choice (using both benchmarks above)
1. **Speed for multi-camera:** Multi-clip table shows `yolov8s` distance mode consistently beats `yolov8m` on FPS while we still need several threads feeding the API and dashboard.
2. **Stabler identity heuristic:** On the same clips, histogram embedding often **raises** unique estimates without a clear accuracy gain (CAM 2 is the clearest example). For store KPIs, **under-counting is bad, but runaway over-counting is worse** for conversion and funnel.
3. **`yolov8m` did not win on “unique” in a consistent way** on CAM 1–3 multi runs; it mainly costs latency. If we need more recall later, we would tune confidence / ROI / model size **after** measuring on held-out clips, not default to `m` for everything.
4. **Single-clip JSON** backs the same story on a smaller budget: `s` vs `m` matched on unique estimate for CAM 3 slice, with `m` much slower.

### Trade-offs
- Not perfect under long occlusions or dense overlaps.
- Cross-camera identity stitching is still heuristic.
- `yolov8m` could still be useful for a **single** hard camera after profiling; it is not the default for all five streams on this machine.

### Used vs Not Used (short recap)

| Approach | Verdict | Why |
|----------|---------|-----|
| **`yolov8s_distance_reid`** | **Used** | Best FPS vs alternatives on multi-clip runs; conservative unique estimate vs hist on busy clips. |
| **`yolov8m_distance_reid`** | Not default | Too slow for parallel cameras; did not clearly beat `s` on unique estimate across clips. |
| **`yolov8s_hist_embedding_reid`** | Not default | Similar or worse FPS with clear **unique inflation** on CAM 2. |
| **DeepSORT / StrongSORT** | Not run | Optional deps missing in this environment; left as future comparison. |


### VLM Usage
**Used VLM in final loop?** No.

I considered VLM support for staff/zone semantics, but did not use it in online inference because of latency, cost, and operational complexity for frame-by-frame execution. For this MVP, deterministic CV + rules was more stable. VLM can be added later for offline audit/classification assist.

---

## Decision 2: Event Schema Design Rationale

### Problem
I needed one schema that works for ingestion, live analytics, and debugging while keeping the API simple and idempotent.

### Options Considered
- **Option A:** Minimal event schema (few fields only)
- **Option B:** Unified rich schema with confidence and metadata
- **Option C:** Multiple event-specific payload shapes

### What AI Suggested
AI suggested a single canonical envelope with strict core fields plus flexible `metadata`, and using `event_id` as an idempotency key.

### Final Choice
**Chosen:** Unified event envelope with required core fields and extensible metadata.

### Why I Chose It
- One ingestion path for all event types keeps system simple.
- Supports metrics, funnel, heatmap, and anomalies from same storage model.
- Simplifies partial success behavior and duplicate handling.

### Key Fields Kept
- `event_id` (idempotency)
- `store_id`, `camera_id`, `visitor_id`
- `event_type`, `timestamp`, `zone_id`, `dwell_ms`
- `is_staff`, `confidence`
- `metadata` (`queue_depth`, `session_seq`, and source hints)

### Known Gaps
- Session semantics can be further tightened for cross-camera stitching.
- POS-linked purchase correlation needs stronger first-class representation in schema usage layer.

---

## Decision 3: API Architecture Choice

### Problem
The API needed to be easy to run (`docker compose up`), robust under bad input, and straightforward to test under deadline.

### Options Considered
- **Option A:** single-file FastAPI with inline logic
- **Option B:** modular routers with shared DB helpers
- **Option C:** heavier service/repository layering

### What AI Suggested
AI suggested modular routers for maintainability, structured DB degradation responses, and explicit ingest behavior (batch limits, duplicate handling, per-item validation).

### Final Choice
**Chosen:** Router-based FastAPI app with SQLite and shared DB utility.

### Why I Chose It
- Clear endpoint boundaries made it faster to test and debug.
- Error handling is explicit (e.g., structured `503` on DB failures).
- Good enough production-like structure for this challenge scope.

### Implemented Behaviors
- Idempotent ingest by `event_id`
- Partial success on malformed payload members
- Structured DB unavailability responses
- Health and anomaly surfaces for live operational view
- Optional POS-aware purchase correlation in metrics/funnel with safe event-based fallback
- Stronger session/event semantics in emission layer (`REENTRY`, zone lifecycle, billing abandon)

### Known Limitations
- Baseline/threshold anomaly logic can be further calibrated with richer historical data.
- Not yet a horizontally scaled architecture (fine for challenge MVP).

### Future work (aligned with DESIGN.md)
If this moves beyond the MVP window, the next investments would be:
- **GPU-backed inference** (PyTorch / CUDA) so multi-camera detection keeps up in real time without sacrificing model size.
- **Redis (or similar)** for shared cache, stream/progress fan-out, and lighter DB pressure when many stores hit the API at once.
- **More model/tracker trials** using the existing `experiments/` + `pipeline/` split so we only promote configs that beat the current `yolov8s_distance_reid` baseline on our own benchmarks.

---

## Evidence Index

- Experiment output (single clip): `experiments/final_experiment_data.json`
- Experiment output (multi clip, 5 videos): `experiments/final_experiment_data_multi.json`
- Entry gate calibration: `experiments/entry_line_calibrator.py`
- Detection/tracking path: `pipeline/detect.py`, `pipeline/tracker.py`, `pipeline/emit.py`, `pipeline/run.py`
- Ingestion/idempotency: `app/ingestion.py`, `app/db.py`
- Analytics endpoints: `app/metrics.py`, `app/funnel.py`, `app/heatmap.py`, `app/anomalies.py`, `app/health.py`
- Tests: `tests/test_pipeline.py`, `tests/test_metrics.py`, `tests/test_anomalies.py`, `tests/test_funnel.py`

---

## Requirement Mapping (What Is Completed)

- Detection + tracking + event emission pipeline from raw clips.
- Schema-shaped event ingestion with idempotency and partial-success behavior.
- Real-time analytics endpoints and operational health endpoint.
- Structured logs and graceful DB degradation path.
- Live dashboard connected to API and pipeline streams.
- Test coverage above 70% with challenge-relevant edge-case tests.
