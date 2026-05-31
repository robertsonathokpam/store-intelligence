# Retail Intelligence System - Purplle Tech Challenge 2026

An end-to-end analytics pipeline that converts raw CCTV footage into structured, real-time business intelligence using YOLOv8, ByteTrack, and FastAPI. The ultimate business goal is measuring and optimizing the **Offline Store Conversion Rate**.

---

## Setup & Run

### 1. Start the Intelligence API (Docker)
Build and start the FastAPI service in the background:
```bash
docker compose up --build -d
```

### 2. Install Pipeline Dependencies
Set up the local environment to run the computer vision pipeline:
```bash
pip install ultralytics opencv-python-headless requests
```

### 3. Run the Detection Pipeline
Place your raw CCTV clips (`CAM 1.mp4` through `CAM 5.mp4`) in the root directory and run the detection and tracking script:
```bash
python pipeline/detect.py
```
This processes **all available camera clips**, runs YOLOv8 + ByteTrack tracking, classifies zones, detects staff, and outputs a structured event stream to `output_events.jsonl`.

To process a single clip:
```bash
python pipeline/detect.py --video "CAM 1.mp4"
```

### 4. Emit Events to the API
Stream the batched events (chunked to a maximum of 500 events per request) to the ingestion endpoint:
```bash
python pipeline/emit.py
```

### 5. View Live Analytics & Metrics
Open your browser and navigate to the analytics endpoints:

| Endpoint | URL |
|:---|:---|
| **Core Metrics** | http://127.0.0.1:8000/stores/STORE_BLR_002/metrics |
| **Conversion Funnel** | http://127.0.0.1:8000/stores/STORE_BLR_002/funnel |
| **Zone Heatmap** | http://127.0.0.1:8000/stores/STORE_BLR_002/heatmap |
| **Anomaly Detection** | http://127.0.0.1:8000/stores/STORE_BLR_002/anomalies |
| **Service Health** | http://127.0.0.1:8000/health |
| **API Documentation** | http://127.0.0.1:8000/docs |

---

##  API Endpoints

| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/events/ingest` | Batch ingest ≤500 events. Idempotent by `event_id`. |
| `GET` | `/stores/{id}/metrics` | Unique visitors, conversion rate, avg dwell per zone, queue abandonment |
| `GET` | `/stores/{id}/funnel` | Conversion funnel: Entry → Zone Visit → Billing Queue → Purchase |
| `GET` | `/stores/{id}/heatmap` | Zone visit frequency + avg dwell, normalised 0–100 |
| `GET` | `/stores/{id}/anomalies` | Active anomalies: queue spike, conversion drop, dead zone |
| `GET` | `/health` | Service status, last event per store, stale-feed warnings |

---

## Testing and Coverage

The test suite includes full integration and unit tests for all endpoints, idempotency, batch limits, staff filtering, conversion/dwell analytics, funnel logic, heatmap, anomalies, and edge cases.

### Run Tests inside the Docker Container
Verify all test cases pass and generate a test coverage report (which exceeds the **>70%** requirement):
```bash
docker compose exec api python -m pytest --cov=. tests/
```

### Run Tests Locally
```bash
pip install -r app/requirements.txt
cd app && python -m pytest --cov=. tests/
```

---

## 📁 Project Structure

```
retail-intelligence-system(purplle-tech-challenge-2026)/
├── pipeline/
│   ├── detect.py          # YOLOv8 + ByteTrack detection + event generation
│   ├── emit.py            # Batched event emitter to API
│   └── requirements.txt
├── app/
│   ├── main.py            # FastAPI entrypoint (all 6 endpoints + logging)
│   ├── models.py          # Pydantic event schema
│   ├── metrics.py         # Real-time metric computation
│   ├── funnel.py          # Conversion funnel logic
│   ├── heatmap.py         # Zone heatmap computation
│   ├── anomalies.py       # Anomaly detection engine
│   ├── pos_data.py        # POS transaction loader + correlator
│   └── requirements.txt
├── tests/
│   └── test_main.py       # Comprehensive test suite (prompt blocks included)
├── hackathon-resources/   # Store layout + POS data + problem statement
├── DESIGN.md              # Architecture + AI-assisted decisions
├── CHOICES.md             # 3 engineering decisions with full reasoning
├── Dockerfile
├── docker-compose.yml
└── README.md
```
