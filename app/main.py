from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.anomalies import router as anomalies_router
from app.db import init_db
from app.debug import router as debug_router
from app.funnel import router as funnel_router
from app.health import router as health_router
from app.heatmap import router as heatmap_router
from app.ingestion import router as ingestion_router
from app.logging_middleware import logging_middleware
from app.metrics import router as metrics_router
from app.progress import router as progress_router




app = FastAPI()

init_db()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(logging_middleware)

app.include_router(health_router)
app.include_router(ingestion_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(anomalies_router)
app.include_router(heatmap_router)
app.include_router(debug_router)
app.include_router(progress_router)

