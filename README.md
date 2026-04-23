# Store Intelligence Challenge Submission

## Setup (5 commands)

```bash
git clone <YOUR_REPO_URL>
cd store-intelligence-system
docker compose up --build -d
docker compose ps
docker compose logs -f pipeline
```

## Run Detection Pipeline Against Clips and Feed API

The pipeline is started by `docker compose up` via service `pipeline` (`python pipeline/run.py`).

Camera mapping in `pipeline/run.py`:
- `CAM_ENTRY_01` -> `data/CAM 3.mp4`
- `CAM_FLOOR_01` -> `data/CAM 1.mp4`
- `CAM_FLOOR_02` -> `data/CAM 2.mp4`
- `CAM_BILLING_01` -> `data/CAM 5.mp4`
- `CAM_GODOWN_01` -> `data/CAM 4.mp4`

Pipeline flow:
- reads clips
- runs detection + tracking
- emits structured events
- sends batches to `POST /events/ingest`

## Local URLs

- API: `http://localhost:8000`
- Dashboard (Part E): `http://localhost:5500/dashboard/dashboard.html`

## Basic Verification

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stores/STORE_BLR_002/metrics
```

## Dataset Scope Used

This implementation is based on the CCTV clips available in the provided working dataset (4-5 clips used in the current run flow).

- No synthetic/fake external files were added.
- If optional artifacts (for example POS/layout side files) are missing in a local package, the system still runs with clip-driven event analytics.
- Core API and dashboard behavior stays stable in this mode.

## What Is Completed from Challenge

- End-to-end pipeline: clip -> detection/tracking -> structured events -> ingest API.
- Required analytics surfaces: metrics, funnel, heatmap, anomalies, health.
- Idempotent ingest with partial success and structured error handling.
- Event semantics upgraded for stronger challenge alignment:
  - `REENTRY` handling after prior `EXIT` on entry camera
  - `ZONE_ENTER` / `ZONE_EXIT` lifecycle on floor and billing streams
  - `BILLING_QUEUE_ABANDON` on billing leave behavior
- Optional POS-aware conversion/funnel purchase correlation:
  - if `data/pos_transactions.csv` exists, 5-minute billing-window matching is used
  - if not present, safe fallback proxy logic is used
- Dockerized run with API + pipeline + dashboard.
- Live dashboard with focused camera stream, all-camera streams, and live metric polling.
- Automated tests with prompt/change headers and coverage above 70%.
- Submission docs included: `docs/DESIGN.md` and `docs/CHOICES.md`.



## Stop

```bash
docker compose down
```
