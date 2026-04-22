# Store Intelligence System

End-to-end store analytics pipeline from raw CCTV clips to a live dashboard.

This repository includes:
- a computer vision pipeline for person detection/tracking and event emission
- an Intelligence API for ingest, metrics, funnel, heatmap, anomalies, health
- a dashboard with live KPI updates, pipeline progress, and live entry-camera detections

## Architecture

1. `pipeline/run.py` reads multi-camera clips from `data/`
2. detections + tracking produce behavioral events
3. events are posted to `POST /events/ingest`
4. FastAPI computes store analytics from ingested events
5. dashboard polls API endpoints and renders live charts/cards
6. pipeline also posts camera progress and annotated frames for live preview

## Repository Layout

- `pipeline/`
  - `detect.py` YOLO person detector
  - `tracker.py` ByteTrack + lightweight global-id recovery + entry line crossing
  - `emit.py` event construction and per-camera emission logic
  - `run.py` orchestrates cameras and pushes events/progress/stream frames
- `app/`
  - `main.py` FastAPI app + routers
  - `ingestion.py` batch ingest with validation/idempotency behavior
  - `metrics.py`, `funnel.py`, `heatmap.py`, `anomalies.py`, `health.py`
  - `debug.py` + `progress.py` + `stream.py` for observability/live preview
- `dashboard/dashboard.html` live dashboard UI
- `docker-compose.yaml` one-command startup for api + pipeline + dashboard

## Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- Git

## Quick Start (5 Commands)

```bash
git clone <YOUR_REPO_URL>
cd store-intelligence-system
docker compose up --build -d
docker compose ps
docker compose logs -f pipeline
```

## Local URLs

- API: `http://localhost:8000`
- Dashboard: `http://localhost:5500/dashboard/dashboard.html`
- Health: `http://localhost:8000/health`
- Live entry stream: `http://localhost:8000/stream/CAM_ENTRY_01`

## Running the Detection Pipeline Against Clips

Pipeline camera mapping in `pipeline/run.py`:

- `CAM_ENTRY_01` -> `data/CAM 3.mp4`
- `CAM_FLOOR_01` -> `data/CAM 1.mp4`
- `CAM_FLOOR_02` -> `data/CAM 2.mp4`
- `CAM_BILLING_01` -> `data/CAM 5.mp4`
- `CAM_GODOWN_01` -> `data/CAM 4.mp4`

The pipeline:
- reads frames
- detects/tracks people
- emits events to `/events/ingest`
- emits progress to `/pipeline/progress`
- emits live annotated JPEG frames to `/stream/frame`

### Entry/Exit Logic

- Entry gate camera (`CAM_ENTRY_01`) uses threshold crossing (line-based) in tracker.
- Current gate line:
  - `((1357, 256), (627, 1078))`
- Side convention:
  - LEFT side of line = INSIDE
  - RIGHT side of line = OUTSIDE

## Useful API Endpoints

- `POST /events/ingest`
- `GET /stores/{store_id}/metrics`
- `GET /stores/{store_id}/funnel`
- `GET /stores/{store_id}/heatmap`
- `GET /stores/{store_id}/anomalies`
- `GET /stores/{store_id}/debug`
- `GET /stores/{store_id}/progress`
- `GET /stream/{camera_id}`
- `GET /health`

## Quick Verification

```bash
curl http://localhost:8000/health
curl http://localhost:8000/stores/STORE_BLR_002/metrics
curl http://localhost:8000/stores/STORE_BLR_002/funnel
curl http://localhost:8000/stores/STORE_BLR_002/progress
```

If dashboard appears but stream is blank:
- confirm `pipeline` service is running
- check `docker compose logs -f pipeline`
- verify `CAM_ENTRY_01` video path exists

## Run Without Docker

```bash
python -m venv .venv
# PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

In another terminal:

```bash
python pipeline/run.py
```

Serve dashboard:

```bash
python -m http.server 5500
```

## Notes

- Ingestion supports up to 500 events per request batch.
- Event ids are unique UUIDs generated at emission time.
- Non-entry cameras can emit fallback visitor IDs for MVP continuity.
- `events_output.jsonl` and experimental scripts are intentionally ignored by git.
