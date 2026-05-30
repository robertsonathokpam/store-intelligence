# Store Intelligence System Architecture

## Overview
This system is a real-time analytics pipeline designed to convert unstructured physical retail footage into structured, queryable business intelligence. The architecture is split into two decoupled layers to ensure scalability and fault tolerance:
1. **Detection Layer (Python/OpenCV/YOLO):** Processes video frames, tracks individuals using bounding boxes, and emits stateless JSON events.
2. **Intelligence API (FastAPI):** Ingests events, handles idempotency, deduplicates sessions, and computes real-time North Star metrics (conversion, dwell times).

### System Architecture Diagram

```mermaid
flowchart TD
    subgraph Edge [Detection Layer - Local Edge]
        Vid[📹 Raw CCTV Video] --> Yolo[🧠 YOLOv8 Model]
        Yolo --> Track[🔗 ByteTrack Re-ID]
        Track --> Json[📄 output_events.jsonl]
    end

    subgraph Cloud [Intelligence API Layer - Docker]
        Json -->|emit.py POST| Ingest[⚡ /events/ingest]
        Ingest -->|Idempotency Check| DB[(events_db)]
        DB --> Metrics[📊 /stores/{id}/metrics]
        Metrics --> Calc[⚙️ Metrics Engine]
        Calc --> |Unique Visitors, Dwell, Conversion| Output[📈 Final JSON Response]
    end
    
    Edge -->|Network| Cloud
```

## AI-Assisted Decisions
I utilized an LLM to accelerate the system design and enforce strict schema compliance:
* **Schema Validation:** I used AI to help map the complex nested JSON constraints from the problem statement into robust Pydantic models in FastAPI. *Result:* I agreed with the AI's approach as Pydantic automatically handles 400-level errors for malformed batch ingests.
* **Tracking Optimization:** I initially planned a custom distance-based Re-ID script. The AI suggested utilizing YOLOv8's native ByteTrack integration (`tracker="bytetrack.yaml"`). *Result:* I agreed and implemented this, as it significantly reduced processing latency and handled frame-to-frame occlusion much better than a custom Euclidean distance script.