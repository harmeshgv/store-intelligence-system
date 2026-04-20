# app/logging_middleware.py
import time
import uuid
import json
from fastapi import Request

async def logging_middleware(request: Request, call_next):
    start_time = time.time()

    # 🔑 trace id (from header or generate)
    trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))

    # 🔎 store_id (from path if present)
    store_id = request.path_params.get("store_id")

    # 📦 event_count (only for ingest)
    event_count = None
    if request.url.path.endswith("/events/ingest"):
        try:
            body = await request.json()
            if isinstance(body, list):
                event_count = len(body)
        except:
            event_count = None

    # ➡️ process request
    response = await call_next(request)

    # ⏱ latency
    latency_ms = int((time.time() - start_time) * 1000)

    # 📊 structured log
    log = {
        "trace_id": trace_id,
        "store_id": store_id,
        "endpoint": request.url.path,
        "method": request.method,
        "latency_ms": latency_ms,
        "event_count": event_count,
        "status_code": response.status_code
    }

    print(json.dumps(log))  # structured log

    return response