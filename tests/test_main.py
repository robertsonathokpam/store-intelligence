# PROMPT: "Generate comprehensive pytest tests for a FastAPI Retail Intelligence API with endpoints:
# GET /health, POST /events/ingest (batch ≤500, idempotent), GET /stores/{id}/metrics,
# GET /stores/{id}/funnel, GET /stores/{id}/heatmap, GET /stores/{id}/anomalies.
# Cover: schema validation, idempotency, staff filtering, conversion/dwell calculations,
# funnel drop-off, heatmap normalisation, anomaly detection, edge cases (empty store,
# all-staff clip, zero purchases, re-entry in funnel), and data confidence thresholds."
# CHANGES MADE: I manually verified all expected metric values by hand-calculating from
# the test event payloads. Added targeted edge-case tests for empty stores, all-staff
# clips, zero purchases, re-entry deduplication, and high-confidence thresholds. Also
# added tests for the three new endpoints (funnel, heatmap, anomalies) and the enhanced
# health endpoint.

import pytest
from fastapi.testclient import TestClient
try:
    from app.main import app, events_db, last_event_ts
except ModuleNotFoundError:
    from main import app, events_db, last_event_ts


client = TestClient(app)


def _clear_state():
    """Reset in-memory state between tests that require isolation."""
    events_db.clear()
    last_event_ts.clear()


# ═══════════════════════════════════════════════════════════════════════
#  Health Endpoint
# ═══════════════════════════════════════════════════════════════════════

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "stores" in data
    assert "total_events_ingested" in data


# ═══════════════════════════════════════════════════════════════════════
#  Event Ingestion
# ═══════════════════════════════════════════════════════════════════════

def test_ingest_events_success():
    _clear_state()
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

    # Test Idempotency: sending the same event again → 0 inserted, 1 ignored
    response_dup = client.post("/events/ingest", json=[valid_event])
    assert response_dup.status_code == 200
    assert response_dup.json()["ignored_duplicates"] == 1
    assert response_dup.json()["inserted"] == 0


def test_ingest_events_batch_limit():
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

    # 501 events must be rejected
    massive_batch = [dummy_event for _ in range(501)]
    response = client.post("/events/ingest", json=massive_batch)
    assert response.status_code == 400
    assert "Batch size exceeds 500" in response.json()["detail"]


def test_ingest_invalid_event_type():
    bad_event = {
        "event_id": "test-bad-type",
        "store_id": "STORE_001",
        "camera_id": "CAM_01",
        "visitor_id": "VIS_1",
        "event_type": "INVALID_TYPE",
        "timestamp": "2026-03-03T14:22:10Z",
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.95,
        "metadata": {"session_seq": 1}
    }
    response = client.post("/events/ingest", json=[bad_event])
    assert response.status_code == 422  # Pydantic validation error


# ═══════════════════════════════════════════════════════════════════════
#  Metrics Endpoint
# ═══════════════════════════════════════════════════════════════════════

def test_store_metrics_empty():
    """Empty store: no events ingested for this store_id."""
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
    _clear_state()

    events = [
        # Customer 1: Joins queue, doesn't abandon → Converted
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
        # Customer 2: Joins queue, abandons → Not converted
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
        # Customer 3: Zone dwell only → Not converted
        {
            "event_id": "evt-c3-1", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "CUST_3", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:15Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 2000, "is_staff": False, "confidence": 0.88,
            "metadata": {"session_seq": 1}
        },
        # Staff member: must be EXCLUDED from all customer metrics
        {
            "event_id": "evt-staff-1", "store_id": "STORE_002", "camera_id": "CAM_01",
            "visitor_id": "STAFF_1", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 10000, "is_staff": True, "confidence": 0.99,
            "metadata": {"session_seq": 1}
        }
    ]

    response = client.post("/events/ingest", json=events)
    assert response.status_code == 200

    response_metrics = client.get("/stores/STORE_002/metrics")
    assert response_metrics.status_code == 200
    data = response_metrics.json()

    # 3 unique customers (staff excluded)
    assert data["unique_visitors"] == 3

    # Avg dwell: MAIN_FLOOR → (3000 + 5000 + 2000) / 3 visitors = 3333.33 ms = 3.33 sec
    assert data["avg_dwell_per_zone_seconds"]["MAIN_FLOOR"] == 3.33

    # Abandonment: 1 abandon / 2 joins = 50%
    assert data["queue_abandonment_rate_percent"] == 50.0

    # Conversion: 1 converted (CUST_1) / 3 total = 33.33%
    assert data["conversion_rate"] == 33.33

    # < 20 visitors → LOW confidence
    assert data["data_confidence"] == "LOW"


def test_store_metrics_high_confidence():
    _clear_state()

    events = []
    for i in range(20):
        events.append({
            "event_id": f"evt-conf-{i}", "store_id": "STORE_CONF", "camera_id": "CAM_01",
            "visitor_id": f"CUST_CONF_{i}", "event_type": "ZONE_DWELL",
            "timestamp": "2026-03-03T14:22:10Z",
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


def test_store_metrics_all_staff():
    """Edge case: every visitor is staff → 0 customer metrics."""
    _clear_state()

    events = [
        {
            "event_id": "evt-allstaff-1", "store_id": "STORE_STAFF", "camera_id": "CAM_01",
            "visitor_id": "STAFF_A", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 5000, "is_staff": True, "confidence": 0.95,
            "metadata": {"session_seq": 1}
        },
        {
            "event_id": "evt-allstaff-2", "store_id": "STORE_STAFF", "camera_id": "CAM_01",
            "visitor_id": "STAFF_B", "event_type": "ENTRY", "timestamp": "2026-03-03T14:23:10Z",
            "zone_id": None, "dwell_ms": 0, "is_staff": True, "confidence": 0.92,
            "metadata": {"session_seq": 1}
        },
    ]

    client.post("/events/ingest", json=events)
    resp = client.get("/stores/STORE_STAFF/metrics")
    data = resp.json()

    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
    assert data["data_confidence"] == "LOW"


def test_store_metrics_zero_purchases():
    """Edge case: visitors enter and dwell but nobody reaches billing."""
    _clear_state()

    events = [
        {
            "event_id": "evt-nopurch-1", "store_id": "STORE_NP", "camera_id": "CAM_01",
            "visitor_id": "VIS_NP_1", "event_type": "ENTRY", "timestamp": "2026-03-03T14:22:10Z",
            "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
            "metadata": {"session_seq": 1}
        },
        {
            "event_id": "evt-nopurch-2", "store_id": "STORE_NP", "camera_id": "CAM_01",
            "visitor_id": "VIS_NP_1", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:25:10Z",
            "zone_id": "SKINCARE", "dwell_ms": 12000, "is_staff": False, "confidence": 0.88,
            "metadata": {"session_seq": 2}
        },
        {
            "event_id": "evt-nopurch-3", "store_id": "STORE_NP", "camera_id": "CAM_01",
            "visitor_id": "VIS_NP_1", "event_type": "EXIT", "timestamp": "2026-03-03T14:30:10Z",
            "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.85,
            "metadata": {"session_seq": 3}
        },
    ]

    client.post("/events/ingest", json=events)
    resp = client.get("/stores/STORE_NP/metrics")
    data = resp.json()

    assert data["unique_visitors"] == 1
    assert data["conversion_rate"] == 0.0
    assert data["queue_abandonment_rate_percent"] == 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Funnel Endpoint
# ═══════════════════════════════════════════════════════════════════════

def test_funnel_empty_store():
    resp = client.get("/stores/STORE_EMPTY_FUNNEL/funnel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["store_id"] == "STORE_EMPTY_FUNNEL"
    assert data["total_sessions"] == 0
    assert len(data["stages"]) == 4


def test_funnel_full_journey():
    _clear_state()

    events = [
        # Visitor A: full journey → ENTRY → ZONE → BILLING → (no abandon = purchase)
        {"event_id": "fun-a1", "store_id": "STORE_FUN", "camera_id": "CAM_01",
         "visitor_id": "VA", "event_type": "ENTRY", "timestamp": "2026-03-03T14:00:00Z",
         "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 1}},
        {"event_id": "fun-a2", "store_id": "STORE_FUN", "camera_id": "CAM_01",
         "visitor_id": "VA", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:05:00Z",
         "zone_id": "SKINCARE", "dwell_ms": 5000, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 2}},
        {"event_id": "fun-a3", "store_id": "STORE_FUN", "camera_id": "CAM_01",
         "visitor_id": "VA", "event_type": "BILLING_QUEUE_JOIN", "timestamp": "2026-03-03T14:10:00Z",
         "zone_id": "BILLING", "dwell_ms": 1000, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 3}},

        # Visitor B: drops off at zone visit (never reaches billing)
        {"event_id": "fun-b1", "store_id": "STORE_FUN", "camera_id": "CAM_01",
         "visitor_id": "VB", "event_type": "ENTRY", "timestamp": "2026-03-03T14:01:00Z",
         "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.85,
         "metadata": {"session_seq": 1}},
        {"event_id": "fun-b2", "store_id": "STORE_FUN", "camera_id": "CAM_01",
         "visitor_id": "VB", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:06:00Z",
         "zone_id": "MAKEUP", "dwell_ms": 3000, "is_staff": False, "confidence": 0.85,
         "metadata": {"session_seq": 2}},

        # Visitor C: enters but leaves immediately (drops off before zone visit)
        {"event_id": "fun-c1", "store_id": "STORE_FUN", "camera_id": "CAM_01",
         "visitor_id": "VC", "event_type": "ENTRY", "timestamp": "2026-03-03T14:02:00Z",
         "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.8,
         "metadata": {"session_seq": 1}},
        {"event_id": "fun-c2", "store_id": "STORE_FUN", "camera_id": "CAM_01",
         "visitor_id": "VC", "event_type": "EXIT", "timestamp": "2026-03-03T14:03:00Z",
         "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.8,
         "metadata": {"session_seq": 2}},
    ]

    client.post("/events/ingest", json=events)
    resp = client.get("/stores/STORE_FUN/funnel")
    data = resp.json()

    assert data["total_sessions"] == 3

    stages = {s["stage"]: s for s in data["stages"]}
    assert stages["Entry"]["count"] == 3
    assert stages["Zone Visit"]["count"] == 2      # VA, VB
    assert stages["Billing Queue"]["count"] == 1   # VA only
    assert stages["Purchase"]["count"] == 1        # VA (joined, didn't abandon)


def test_funnel_reentry_no_double_count():
    """A re-entering visitor should NOT be double-counted in the funnel."""
    _clear_state()

    events = [
        {"event_id": "re-a1", "store_id": "STORE_RE", "camera_id": "CAM_01",
         "visitor_id": "VIS_RE", "event_type": "ENTRY", "timestamp": "2026-03-03T14:00:00Z",
         "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 1}},
        {"event_id": "re-a2", "store_id": "STORE_RE", "camera_id": "CAM_01",
         "visitor_id": "VIS_RE", "event_type": "EXIT", "timestamp": "2026-03-03T14:10:00Z",
         "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 2}},
        {"event_id": "re-a3", "store_id": "STORE_RE", "camera_id": "CAM_01",
         "visitor_id": "VIS_RE", "event_type": "REENTRY", "timestamp": "2026-03-03T14:20:00Z",
         "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.88,
         "metadata": {"session_seq": 3}},
        {"event_id": "re-a4", "store_id": "STORE_RE", "camera_id": "CAM_01",
         "visitor_id": "VIS_RE", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:25:00Z",
         "zone_id": "SKINCARE", "dwell_ms": 5000, "is_staff": False, "confidence": 0.88,
         "metadata": {"session_seq": 4}},
    ]

    client.post("/events/ingest", json=events)
    resp = client.get("/stores/STORE_RE/funnel")
    data = resp.json()

    # Only 1 unique visitor — ENTRY + REENTRY should NOT produce 2
    assert data["total_sessions"] == 1
    stages = {s["stage"]: s for s in data["stages"]}
    assert stages["Entry"]["count"] == 1
    assert stages["Zone Visit"]["count"] == 1


# ═══════════════════════════════════════════════════════════════════════
#  Heatmap Endpoint
# ═══════════════════════════════════════════════════════════════════════

def test_heatmap_empty_store():
    resp = client.get("/stores/STORE_EMPTY_HEAT/heatmap")
    assert resp.status_code == 200
    data = resp.json()
    assert data["zones"] == []
    assert data["data_confidence"] == "LOW"


def test_heatmap_normalisation():
    _clear_state()

    events = [
        # SKINCARE: 3 unique visitors
        {"event_id": "hm-1", "store_id": "STORE_HM", "camera_id": "CAM_01",
         "visitor_id": "V1", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:00:00Z",
         "zone_id": "SKINCARE", "dwell_ms": 2000, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 1}},
        {"event_id": "hm-2", "store_id": "STORE_HM", "camera_id": "CAM_01",
         "visitor_id": "V2", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:01:00Z",
         "zone_id": "SKINCARE", "dwell_ms": 3000, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 1}},
        {"event_id": "hm-3", "store_id": "STORE_HM", "camera_id": "CAM_01",
         "visitor_id": "V3", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:02:00Z",
         "zone_id": "SKINCARE", "dwell_ms": 4000, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 1}},
        # MAKEUP: 1 unique visitor
        {"event_id": "hm-4", "store_id": "STORE_HM", "camera_id": "CAM_01",
         "visitor_id": "V1", "event_type": "ZONE_DWELL", "timestamp": "2026-03-03T14:05:00Z",
         "zone_id": "MAKEUP", "dwell_ms": 1000, "is_staff": False, "confidence": 0.9,
         "metadata": {"session_seq": 2}},
    ]

    client.post("/events/ingest", json=events)
    resp = client.get("/stores/STORE_HM/heatmap")
    data = resp.json()

    assert len(data["zones"]) == 2

    zones_by_id = {z["zone_id"]: z for z in data["zones"]}

    # SKINCARE has max visitors (3) → normalised = 100
    assert zones_by_id["SKINCARE"]["normalised_score"] == 100.0
    assert zones_by_id["SKINCARE"]["visit_count"] == 3
    # Avg dwell: (2000+3000+4000)/3 = 3000 ms = 3.0 sec
    assert zones_by_id["SKINCARE"]["avg_dwell_seconds"] == 3.0

    # MAKEUP has 1 visitor → normalised = 33.33
    assert zones_by_id["MAKEUP"]["normalised_score"] == 33.33
    assert zones_by_id["MAKEUP"]["visit_count"] == 1

    assert data["data_confidence"] == "LOW"


# ═══════════════════════════════════════════════════════════════════════
#  Anomalies Endpoint
# ═══════════════════════════════════════════════════════════════════════

def test_anomalies_empty_store():
    resp = client.get("/stores/STORE_EMPTY_ANOM/anomalies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["anomaly_count"] == 0
    assert data["anomalies"] == []


def test_anomalies_queue_spike():
    _clear_state()

    events = [
        {
            "event_id": "anom-q1", "store_id": "STORE_ANOM", "camera_id": "CAM_01",
            "visitor_id": "VQ1", "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-03-03T14:00:00Z",
            "zone_id": "BILLING", "dwell_ms": 1000, "is_staff": False, "confidence": 0.9,
            "metadata": {"queue_depth": 12, "session_seq": 1}
        },
    ]

    client.post("/events/ingest", json=events)
    resp = client.get("/stores/STORE_ANOM/anomalies")
    data = resp.json()

    # queue_depth=12 → CRITICAL spike
    queue_anomalies = [a for a in data["anomalies"] if a["type"] == "BILLING_QUEUE_SPIKE"]
    assert len(queue_anomalies) == 1
    assert queue_anomalies[0]["severity"] == "CRITICAL"
    assert "suggested_action" in queue_anomalies[0]


def test_anomalies_conversion_drop():
    _clear_state()

    # 10 visitors, 0 billing queue joins → 0% conversion → CRITICAL drop
    events = []
    for i in range(10):
        events.append({
            "event_id": f"anom-cd-{i}", "store_id": "STORE_CDROP", "camera_id": "CAM_01",
            "visitor_id": f"VCD_{i}", "event_type": "ZONE_DWELL",
            "timestamp": "2026-03-03T14:00:00Z",
            "zone_id": "MAIN_FLOOR", "dwell_ms": 2000, "is_staff": False, "confidence": 0.9,
            "metadata": {"session_seq": 1}
        })

    client.post("/events/ingest", json=events)
    resp = client.get("/stores/STORE_CDROP/anomalies")
    data = resp.json()

    conv_anomalies = [a for a in data["anomalies"] if a["type"] == "CONVERSION_DROP"]
    assert len(conv_anomalies) == 1
    assert conv_anomalies[0]["severity"] == "CRITICAL"


# ═══════════════════════════════════════════════════════════════════════
#  Health Enhanced
# ═══════════════════════════════════════════════════════════════════════

def test_health_tracks_stores():
    _clear_state()

    event = {
        "event_id": "health-track-1", "store_id": "STORE_HEALTH_TEST", "camera_id": "CAM_01",
        "visitor_id": "VH1", "event_type": "ENTRY", "timestamp": "2026-03-03T14:00:00Z",
        "zone_id": None, "dwell_ms": 0, "is_staff": False, "confidence": 0.9,
        "metadata": {"session_seq": 1}
    }
    client.post("/events/ingest", json=[event])

    resp = client.get("/health")
    data = resp.json()

    assert "STORE_HEALTH_TEST" in data["stores"]
    store_info = data["stores"]["STORE_HEALTH_TEST"]
    assert "last_event" in store_info
    assert "lag_seconds" in store_info
    assert store_info["status"] in ("OK", "STALE_FEED")


# ═══════════════════════════════════════════════════════════════════════
#  Root redirect
# ═══════════════════════════════════════════════════════════════════════

def test_root_redirects_to_docs():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert "/docs" in response.headers.get("location", "")