# Engineering Choices

### 1. Detection Model Selection
**Options Considered:** MediaPipe, YOLOv8 + Custom DeepSORT, YOLOv8 + Native ByteTrack.
**What AI Suggested:** The LLM suggested YOLOv8 with its native ByteTrack implementation for the best balance of speed and tracking stability. 
**What I Chose and Why:** I selected YOLOv8 + ByteTrack. Retail edge devices rarely have massive GPU clusters. YOLOv8n (nano) runs efficiently on CPU/low-end hardware, and ByteTrack handles the Re-ID requirement (assigning consistent `visitor_id` tokens across frames) without needing a secondary, heavy feature-extraction model.


| Model | Hardware Requirement | Tracking Stability | Re-ID Support |
| :--- | :--- | :--- | :--- |
| **MediaPipe** | Low (CPU) | Low (Frame-by-frame) | Custom code required |
| **YOLOv8 + Custom DeepSORT** | High (GPU preferred) | High | Heavy pipeline overhead |
| **YOLOv8 + Native ByteTrack** | **Low/Medium** | **High** | **Native (Zero overhead)** |



### 2. Event Schema Design Rationale
**Options Considered:** Deeply nested hierarchical JSON vs. Flat event logs with metadata payloads.
**What AI Suggested:** A flat event structure where every single state change (e.g., `ZONE_DWELL`) is an independent, idempotent event.
**What I Chose and Why:** I chose the flat schema with a `metadata` dictionary. This makes the database layer highly scalable. If a batch ingest fails midway, the flat structure allows for safe retries without corrupting active visitor sessions. 

### 3. API Architecture Choice
**Options Considered:** Flask, Express.js, FastAPI.
**What AI Suggested:** FastAPI for its asynchronous capabilities and native JSON validation.
**What I Chose and Why:** I chose FastAPI. The challenge required strict data schemas and handling up to 500 events per batch. FastAPI's Pydantic integration meant I didn't have to write manual data validation loops, and its async routing ensures the `/events/ingest` endpoint won't block the `/metrics` endpoint during heavy foot-traffic periods in the store.
