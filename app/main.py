"""
Retail Intelligence API — FastAPI entrypoint.

Endpoints:
    GET  /                              → Redirect to /docs
    GET  /health                        → Service health + stale-feed detection
    POST /events/ingest                 → Batch event ingestion (≤500, idempotent)
    GET  /stores/{store_id}/metrics     → Real-time KPIs (conversion, dwell, queue)
    GET  /stores/{store_id}/funnel      → Conversion funnel with drop-off %
    GET  /stores/{store_id}/heatmap     → Zone heatmap normalised 0–100
    GET  /stores/{store_id}/anomalies   → Active operational anomalies
"""

import os
import sys
import uuid
import time
import logging
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from datetime import datetime, timezone

from models import StoreEvent
from metrics import calculate_store_metrics
from funnel import calculate_funnel
from heatmap import calculate_heatmap
from anomalies import detect_anomalies
from pos_data import load_pos_transactions, get_converted_visitors

# ── Structured Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("store_intelligence")

# In-memory event store (keyed by event_id for O(1) idempotency checks)
events_db = {}

# POS transactions (loaded once at startup)
pos_transactions: list = []

# Track last-event timestamp per store for /health staleness detection
last_event_ts: dict = {}


@asynccontextmanager
async def lifespan(app):
    """Load POS data on startup so /metrics can use POS-correlated conversion."""
    global pos_transactions
    pos_transactions = load_pos_transactions()
    logger.info("pos_data_loaded | transaction_count=%d", len(pos_transactions))
    yield


# ── Application ──────────────────────────────────────────────────────
app = FastAPI(title="Retail Intelligence API", lifespan=lifespan)

# Allow CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Middleware: structured request logging ────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()

    # Attach trace_id so downstream handlers can reference it
    request.state.trace_id = trace_id

    response = await call_next(request)

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    store_id = request.path_params.get("store_id", "-")
    logger.info(
        "trace_id=%s | endpoint=%s %s | store_id=%s | status=%d | latency_ms=%.2f",
        trace_id,
        request.method,
        request.url.path,
        store_id,
        response.status_code,
        latency_ms,
    )
    response.headers["X-Trace-ID"] = trace_id
    return response


# ── Endpoints ─────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Redirect to interactive API documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health_check():
    """
    Service health endpoint.
    Reports last event timestamp per store and emits STALE_FEED warnings
    for any store whose most recent event is older than 10 minutes.
    """
    now = datetime.now(timezone.utc)
    store_status = {}

    for sid, ts in last_event_ts.items():
        lag_seconds = (now - ts).total_seconds()
        store_status[sid] = {
            "last_event": ts.isoformat(),
            "lag_seconds": round(lag_seconds, 1),
            "status": "STALE_FEED" if lag_seconds > 600 else "OK",
        }

    return {
        "status": "healthy",
        "timestamp": now.isoformat(),
        "stores": store_status,
        "total_events_ingested": len(events_db),
    }


@app.post("/events/ingest")
async def ingest_events(events: List[StoreEvent]):
    """
    Batch-ingest up to 500 events.  Idempotent by event_id (duplicates
    are silently ignored).  Returns counts of inserted vs. ignored events.
    """
    if len(events) > 500:
        raise HTTPException(
            status_code=400,
            detail="Batch size exceeds 500 events limit.",
        )

    inserted = 0
    ignored = 0

    for event in events:
        if event.event_id not in events_db:
            events_db[event.event_id] = event
            inserted += 1

            # Track latest event timestamp per store
            prev = last_event_ts.get(event.store_id)
            if prev is None or event.timestamp > prev:
                last_event_ts[event.store_id] = event.timestamp
        else:
            ignored += 1

    logger.info(
        "ingest | inserted=%d | ignored_duplicates=%d | total_in_db=%d",
        inserted,
        ignored,
        len(events_db),
    )

    return {
        "status": "success",
        "inserted": inserted,
        "ignored_duplicates": ignored,
    }


@app.get("/stores/{store_id}/metrics")
async def get_metrics(store_id: str):
    """
    Real-time store metrics:
      • unique_visitors, conversion_rate, avg_dwell_per_zone_seconds
      • queue_abandonment_rate_percent, data_confidence
    """
    all_events = list(events_db.values())

    # POS-correlated conversion (if POS data was loaded)
    converted_ids = set()
    if pos_transactions:
        converted_ids = get_converted_visitors(pos_transactions, all_events, store_id)

    metrics = calculate_store_metrics(store_id, all_events, converted_ids or None)

    if "conversion_rate" not in metrics:
        metrics["conversion_rate"] = 0.0

    return metrics


@app.get("/stores/{store_id}/funnel")
async def get_funnel(store_id: str):
    """
    Conversion funnel: Entry → Zone Visit → Billing Queue → Purchase.
    Session-based — re-entries do not double-count a visitor.
    """
    all_events = list(events_db.values())

    converted_ids = set()
    if pos_transactions:
        converted_ids = get_converted_visitors(pos_transactions, all_events, store_id)

    return calculate_funnel(store_id, all_events, converted_ids)


@app.get("/stores/{store_id}/heatmap")
async def get_heatmap(store_id: str):
    """
    Zone visit frequency + avg dwell, normalised 0–100 for heatmap rendering.
    Includes data_confidence flag when session count < 20.
    """
    all_events = list(events_db.values())
    return calculate_heatmap(store_id, all_events)


@app.get("/stores/{store_id}/anomalies")
async def get_anomalies(store_id: str):
    """
    Active anomalies: queue spike, conversion drop, dead zone.
    Each anomaly includes severity (INFO / WARN / CRITICAL) and
    a suggested_action for the operations team.
    """
    all_events = list(events_db.values())
    return detect_anomalies(store_id, all_events)