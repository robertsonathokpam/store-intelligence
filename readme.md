# Store Intelligence System - Purplle Tech Challenge 2026

An end-to-end analytics pipeline that converts raw CCTV footage into structured, real-time business intelligence using YOLOv8, ByteTrack, and FastAPI. The ultimate business goal is measuring and optimizing the **Offline Store Conversion Rate**.

---

##  Setup & Run (5 Simple Steps)

### 1. Start the Intelligence API (Docker)
Build and start the FastAPI service in the background:
```bash
docker compose up --build -d
```

### 2. Install Pipeline Dependencies
Set up the local environment to run the computer vision pipeline:
```bash
pip install -r app/requirements.txt
pip install ultralytics opencv-python-headless requests
```

### 3. Run the Detection Pipeline
Place your raw CCTV clips (e.g., `CAM 1.mp4`) in the root directory and run the detection and tracking script:
```bash
python pipeline/detect.py
```
This processes the footage and outputs a stateless event stream to `output_events.jsonl`.

### 4. Emit Events to the API
Stream the batched events (chunked to a maximum of 500 events per request) to the ingestion endpoint:
```bash
python pipeline/emit.py
```

### 5. View Live Analytics & Metrics
Open your browser and navigate to the real-time analytics endpoint to view metrics for your store:
```http
http://127.0.0.1:8000/stores/STORE_001/metrics
```

---

##  Testing and Coverage

The test suite includes full integration and unit tests for endpoints, idempotency, batch limits, staff filtering, and conversion/dwell analytics.

### Run Tests inside the Docker Container
Verify all test cases pass and generate a test coverage report (which exceeds the **>70%** requirement):
```bash
docker compose exec api python -m pytest --cov=. tests/
```
