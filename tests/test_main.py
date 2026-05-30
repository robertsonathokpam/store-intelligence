# PROMPT: "Generate pytest unit tests for a FastAPI application with two endpoints: GET /health and POST /events/ingest. The ingest endpoint accepts a list of Pydantic StoreEvent models but must reject payloads larger than 500 events with a 400 status code. Use httpx AsyncClient for testing."
# CHANGES MADE: I manually added the exact StoreEvent schema payload to match my Pydantic models, and ensured the idempotency check was validated by sending the same event twice.

import pytest
from fastapi.testclient import TestClient
try:
    from app.main import app
except ModuleNotFoundError:
    from main import app


client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_ingest_events_success():
    # Valid payload matching our Pydantic schema
    valid_event = {
        "event_id": "test-uuid-1",
        "store_id": "STORE_001",
        "camera_id": "CAM_01",
        "visitor_id": "VIS_1",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.95,
        "metadata": {
            "queue_depth": None,
            "sku_zone": None,
            "session_seq": 1
        }
    }
    
    response = client.post("/events/ingest", json=[valid_event])
    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    
    # Test Idempotency (Sending it again should result in 0 inserted, 1 ignored)
    response_duplicate = client.post("/events/ingest", json=[valid_event])
    assert response_duplicate.status_code == 200
    assert response_duplicate.json()["ignored_duplicates"] == 1

def test_ingest_events_batch_limit():
    # Create a dummy event
    dummy_event = {
        "event_id": "test-uuid-batch",
        "store_id": "STORE_001",
        "camera_id": "CAM_01",
        "visitor_id": "VIS_2",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.95,
        "metadata": {"session_seq": 1}
    }
    
    # Generate an array of 501 events
    massive_batch = [dummy_event for _ in range(501)]
    
    # The API must reject this per the challenge constraints
    response = client.post("/events/ingest", json=massive_batch)
    assert response.status_code == 400
    assert "Batch size exceeds 500" in response.json()["detail"]

def test_store_metrics_empty():
    response = client.get("/stores/STORE_999/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["store_id"] == "STORE_999"
    assert data["unique_visitors"] == 0
    assert data["avg_dwell_per_zone_seconds"] == {}
    assert data["queue_abandonment_rate_percent"] == 0.0
    assert data["conversion_rate"] == 0.0
    assert data["data_confidence"] == "LOW"

def test_store_metrics_full_calculation():
    # Setup multiple events for STORE_002
    events = [
        # Customer 1: Joins queue, doesn't abandon (Converted)
        # Zone Dwell: 3000 ms in MAIN_FLOOR
        {
            "event_id": "evt-c1-1", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "CUST_1", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 3000, "is_staff": False, "confidence": 0.9,
            "metadata": {"session_seq": 1}
        },
        {
            "event_id": "evt-c1-2", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "CUST_1", "event_type": "BILLING_QUEUE_JOIN", "timestamp": "2026-03-03T14:23:10Z",
            "zone_id": "BILLING", "dwell_ms": 1000, "is_staff": False, "confidence": 0.9,
            "metadata": {"session_seq": 2}
        },
        # Customer 2: Joins queue, abandons (Not Converted)
        # Zone Dwell: 5000 ms in MAIN_FLOOR
        {
            "event_id": "evt-c2-1", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "CUST_2", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:12Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 5000, "is_staff": False, "confidence": 0.95,
            "metadata": {"session_seq": 1}
        },
        {
            "event_id": "evt-c2-2", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "CUST_2", "event_type": "BILLING_QUEUE_JOIN", "timestamp": "2026-03-03T14:24:10Z",
            "zone_id": "BILLING", "dwell_ms": 2000, "is_staff": False, "confidence": 0.92,
            "metadata": {"session_seq": 2}
        },
        {
            "event_id": "evt-c2-3", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "CUST_2", "event_type": "BILLING_QUEUE_ABANDON", "timestamp": "2026-03-03T14:25:10Z",
            "zone_id": "BILLING", "dwell_ms": 500, "is_staff": False, "confidence": 0.91,
            "metadata": {"session_seq": 3}
        },
        # Customer 3: Zone dwell only (Not Converted)
        # Zone Dwell: 2000 ms in MAIN_FLOOR
        {
            "event_id": "evt-c3-1", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "CUST_3", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:15Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 2000, "is_staff": False, "confidence": 0.88,
            "metadata": {"session_seq": 1}
        },
        # Staff member: Should be ignored entirely in metrics
        {
            "event_id": "evt-staff-1", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "STAFF_1", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 10000, "is_staff": True, "confidence": 0.99,
            "metadata": {"session_seq": 1}
        }
    ]
    
    # Ingest events
    response = client.post("/events/ingest", json=events)
    assert response.status_code == 200
    
    # Request metrics for STORE_002
    response_metrics = client.get("/stores/STORE_002/metrics")
    assert response_metrics.status_code == 200
    data = response_metrics.json()
    
    # Assert unique customer visitors (excluding staff) = 3 (CUST_1, CUST_2, CUST_3)
    assert data["unique_visitors"] == 3
    
    # Assert Average Dwell Time:
    # Total MAIN_FLOOR dwell: 3000 (CUST_1) + 5000 (CUST_2) + 2000 (CUST_3) = 10000 ms.
    # Total unique visitors in MAIN_FLOOR = 3.
    # Average MAIN_FLOOR dwell = 10000 / 3 = 3333.33 ms = 3.33 seconds.
    assert data["avg_dwell_per_zone_seconds"]["MAIN_FLOOR"] == 3.33
    
    # Abandonment Rate:
    # Queue Joins = 2 (CUST_1, CUST_2)
    # Queue Abandons = 1 (CUST_2)
    # Abandonment Rate = 1 / 2 = 50.0%
    assert data["queue_abandonment_rate_percent"] == 50.0
    
    # Conversion Rate:
    # Converted = CUST_1 (joined queue, didn't abandon)
    # Total unique visitors = 3
    # Conversion Rate = 1 / 3 = 33.33%
    assert data["conversion_rate"] == 33.33
    
    # Data Confidence:
    # Unique visitors = 3 < 20, so LOW
    assert data["data_confidence"] == "LOW"

def test_store_metrics_high_confidence():
    # Setup 20 unique visitors to verify HIGH data confidence
    events = []
    for i in range(20):
        events.append({
            "event_id": f"evt-conf-{i}", "store_id": "STORE_CONF", "camera_id": "CAM_01",
            "visitor_id": f"CUST_CONF_{i}", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 1000, "is_staff": False, "confidence": 0.9,
            "metadata": {"session_seq": 1}
        })
        
    response = client.post("/events/ingest", json=events)
    assert response.status_code == 200
    
    response_metrics = client.get("/stores/STORE_CONF/metrics")
    assert response_metrics.status_code == 200
    data = response_metrics.json()
    
    assert data["unique_visitors"] == 20
    assert data["data_confidence"] == "HIGH"