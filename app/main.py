from fastapi import FastAPI
from app.db import init_db
from app.ingestion import router as ingestion_router
from app.metrics import router as metrics_router
from app.funnel import router as funnel_router
from app.heatmap import router as heatmap_router
from app.health import router as health_router
from app.anomalies import router as anomalies_router
from fastapi import FastAPI
from app.logging_middleware import logging_middleware




app = FastAPI()

init_db()
app.middleware("http")(logging_middleware)

app.include_router(health_router)
app.include_router(ingestion_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(anomalies_router)

app.include_router(heatmap_router)
























































