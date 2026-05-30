import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from typing import List
from models import StoreEvent
from metrics import calculate_store_metrics
from datetime import datetime, timezone


app = FastAPI(title="Store Intelligence API")

# Temporary in-memory database 
events_db = {}

from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    # Redirects the blank homepage straight to the documentation
    return RedirectResponse(url="/docs")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/events/ingest")
async def ingest_events(events: List[StoreEvent]):
    if len(events) > 500:
        raise HTTPException(status_code=400, detail="Batch size exceeds 500 events limit.")
    
    inserted = 0
    ignored = 0
    for event in events:
        if event.event_id not in events_db:
            events_db[event.event_id] = event
            inserted += 1
        else:
            ignored += 1
            
    return {"status": "success", "inserted": inserted, "ignored_duplicates": ignored}

# --- NEW ENDPOINT BELOW ---

@app.get("/stores/{store_id}/metrics")
async def get_metrics(store_id: str):
    # Get all events from our mock database as a list
    all_events = list(events_db.values())
    
    # Run the analytics engine
    metrics = calculate_store_metrics(store_id, all_events)
    
    # Ensure conversion_rate is always present (fallback to 0.0 if not computed)
    if "conversion_rate" not in metrics:
        metrics["conversion_rate"] = 0.0
    
    return metrics