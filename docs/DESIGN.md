# DESIGN.md

## 1) System Goal

This project's goal is to convert raw CCTV footage into a live, intelligent system.
The final goal is to make offline conversion measurable and operationally actionable using:
- a detection/tracking pipeline,
- a production-style ingestion API,
- analytics endpoints (`/metrics`, `/funnel`, `/heatmap`, `/anomalies`, `/health`),
- and a live dashboard.

---

## 2) Plain-Language Architecture Overview

1. First, we take raw CCTV camera clips, and each camera stream is processed separately in parallel.
2. A detector finds people, a tracker keeps temporal identity, and an event emitter creates structured events.
3. Events are posted in batches to `POST /events/ingest`.
4. The API validates each event, deduplicates by `event_id`, and stores accepted records.
5. Analytics endpoints compute store KPIs from the stored events using backend SQL queries.
6. The dashboard polls the API and renders live cards/charts.
7. The pipeline also sends progress updates and preview frames for real-time observability.

---

## 2.1) Dataset Availability and Assumptions

This build is implemented using the camera clips available in the working dataset package.

- The runtime path is clip-driven: detect -> track -> emit -> ingest -> analytics.
- No fake/synthetic external side files were introduced to force unsupported behaviors.
- If optional side artifacts are missing in a local package, the API still returns stable outputs from emitted events.
- The architecture keeps extension points open for tighter POS/layout correlation when those files are available.

---

## 3) Detection and Tracking Design

### Detection
- Model family: YOLOv8.
- Practical tuning focus: confidence thresholds and inference/runtime balance.

### Tracking and Identity
- Tracker baseline: ByteTrack.
- Identity continuity support: rule-based matching (distance and time window) plus stability rules.
- Key rules implemented in practice:
  - TTL for stale identities,
  - max spatial movement threshold (`MAX_DIST`),
  - minimum frame presence (`MIN_FRAMES`) to filter pass-by noise.

### Entry/Exit Semantics
- Entry camera uses explicit line-crossing logic.
- Crossing direction determines `ENTRY` vs `EXIT`.
- Non-entry cameras are used for behavioral context (zone/billing), not gate lifecycle creation.

---

## 4) Event Stream Design

The pipeline emits a unified event envelope containing:
- identity (`event_id`, `visitor_id`),
- context (`store_id`, `camera_id`, `event_type`, `timestamp`),
- behavior fields (`zone_id`, `dwell_ms`, `is_staff`, `confidence`),
- extensible metadata (`queue_depth`, `session_seq`, etc.).

Design intent:
- one canonical ingest path,
- idempotency-safe write behavior,
- compatibility with multiple downstream analytics surfaces.

Additional implementation details:
- Entry camera now emits `REENTRY` after a prior `EXIT` for the same tracked identity lifecycle.
- Floor and billing streams emit `ZONE_ENTER` / `ZONE_EXIT` in addition to dwell-style updates.
- Billing flow includes `BILLING_QUEUE_ABANDON` behavior when a queue participant leaves before completion.

---

## 5) Intelligence API Design

### Ingestion
- `POST /events/ingest` supports batch ingestion with per-item validation.
- Duplicate `event_id` handling is explicit (idempotent behavior).
- Partial success is supported (valid items inserted, malformed items reported).

### Analytics
- `/stores/{id}/metrics`: unique visitors, conversion, dwell, queue/abandonment signals.
- `/stores/{id}/funnel`: stage-wise progression and drop-off.
- `/stores/{id}/heatmap`: zone-normalized activity and dwell.
- `/stores/{id}/anomalies`: queue spike, conversion drop, dead-zone style alerts.
- `/health`: service/store feed status.

### Reliability
- Structured DB failure responses (HTTP 503 with structured body) for core endpoints.
- No raw stack traces in API responses.
- Optional POS-aware conversion path:
  - if POS data is present, conversion/purchase uses billing-window correlation around transactions,
  - otherwise fallback event-only logic is used to keep runtime stable in clip-only setups.

---

## 6) Dashboard and Live Validation

The dashboard displays:
- KPI cards and trend charts,
- anomaly banners,
- pipeline progress status,
- and a live entry-camera detection stream for visual validation.

This is used to prove real-time integration (pipeline -> API -> dashboard) rather than offline-only batch output.

---

## 7) Testing Strategy

Tests are organized by behavior domains:
- ingest contract and idempotency,
- metrics edge cases,
- anomaly scenarios,
- funnel re-entry behavior.

Prompt/changes headers were maintained in test files to document AI-assisted generation and human adjustments.

---

## 8) Limitations and Next Steps

Current MVP limitations:
- cross-camera identity stitching remains heuristic,
- staff classification can be improved,
- anomaly baselines can be richer with more historical depth,
- POS-correlation can be deepened for stronger conversion attribution.

Planned improvements:
- stronger multi-camera session stitching,
- expanded calibration per store/camera,
- improved re-entry robustness under heavy occlusion.

### Future work (what we could build next)

These are natural extensions on top of what already exists; they are not required for the MVP but would matter in a production rollout.

- **GPU + PyTorch inference path**  
  Today the stack is CPU-friendly for laptops and Docker defaults. Moving detection (and optional Re-ID) to **CUDA / PyTorch** on a GPU box would raise throughput a lot (higher FPS, more stable multi-camera `pipeline/run.py`). The same `experiments/` harness can be used to compare FPS and identity stability before swapping the main pipeline.

- **Redis (or similar) for hot state and fan-out**  
  SQLite + in-memory maps work for a single API instance. For many stores and concurrent writers, **Redis** helps with: caching latest metrics snapshots, progress/stream last-frame blobs, rate-limited idempotency keys, and pub/sub so dashboards or downstream services get updates without hammering the DB. It is a scalability and latency choice, not a correctness requirement for the take-home.

- **Model and tracker experiments behind the same pipeline**  
  We already have `experiments/run_all_experiments.py`, configs, and JSON outputs. Next step is to plug **other YOLO sizes, RT-DETR-style detectors, or DeepSORT/StrongSORT** (once deps are installed) into the same `pipeline/` contract (`detect` → `track` → `emit` → ingest) so every change is measured with the same clips and API surface.

---

## 9) Challenge Completion Snapshot

Completed in this submission:

- Detection pipeline from raw clips to structured events.
- Event ingestion with idempotency and partial-success handling.
- Analytics APIs for metrics, funnel, heatmap, anomalies, and health.
- Structured request logging middleware and health visibility.
- Dockerized services for API, pipeline, and dashboard.
- Live dashboard proving pipeline -> API -> UI connectivity.
- Automated tests covering required edge scenarios and >70% coverage.
- AI documentation artifacts (`PROMPT/CHANGES` in tests, this DESIGN doc, CHOICES doc).

Current known constraints (transparent):

- Session semantics and re-identification are heuristic in crowded/occluded scenes.
- Staff classification is baseline and can be improved.
- POS-linked conversion attribution can be deepened when stronger side-data integration is enabled.

---

## AI-Assisted Decisions

This section lists key places where an LLM shaped implementation direction and whether I agreed or overrode the suggestion.

### AI-Assisted Decision 1: Detection/Tracking Starting Point
- **AI suggested:** start with YOLOv8 + ByteTrack baseline, then add minimal post-rules before heavy Re-ID stacks.
- **My decision:** agreed with this path.
- **Why:** it gave a fast, testable baseline and reduced early complexity.

### AI-Assisted Decision 2: Entry/Exit Modeling
- **AI suggested:** use explicit threshold line-crossing on entry camera for direction instead of inferring from all cameras.
- **My decision:** agreed and implemented with calibrated line points and direction rules.
- **Why:** improved semantic clarity and reduced noisy direction inference.

### AI-Assisted Decision 3: Ingestion and Error Semantics
- **AI suggested:** enforce idempotency by `event_id`, support partial success, and return structured 503 on DB failures.
- **My decision:** agreed and implemented.
- **Why:** this directly aligned with production-readiness requirements and testability.

### AI-Assisted Suggestion I Overrode
- **AI suggested:** heavier/appearance-heavy Re-ID in the main loop earlier.
- **My decision:** partially overrode; kept rule-based approach as primary for MVP.
- **Why:** practical runtime and stability trade-off in the 48-hour scope.

