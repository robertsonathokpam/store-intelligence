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

**Where I Disagreed with AI:** The LLM suggested using a VLM (GPT-4V / Gemini Vision) for zone classification by passing frames to the model and asking "what zone is this person in?" I rejected this for three reasons: (1) latency — a VLM API call per-frame would make the pipeline orders of magnitude slower, (2) cost — at 30fps across 5 cameras, API costs would be enormous, and (3) reliability — the quadrant-based heuristic I implemented is deterministic and explainable, even if approximate. For a production system I would invest in proper zone polygon calibration, not VLM inference on every frame.


### 2. Event Schema Design Rationale
**Options Considered:** Deeply nested hierarchical JSON vs. Flat event logs with metadata payloads.
**What AI Suggested:** A flat event structure where every single state change (e.g., `ZONE_DWELL`) is an independent, idempotent event.
**What I Chose and Why:** I chose the flat schema with a `metadata` dictionary. This makes the database layer highly scalable. If a batch ingest fails midway, the flat structure allows for safe retries without corrupting active visitor sessions. Each event is keyed by a UUID `event_id`, which makes idempotent replay safe — the same batch can be POSTed multiple times without side effects. The flat design also simplifies the `/funnel` computation: I can filter by `event_type` and `visitor_id` without traversing nested session trees.

**Trade-off Acknowledged:** The flat schema means the API must reconstruct visitor sessions at query time (e.g., grouping by `visitor_id` and ordering by `session_seq`). This is O(n) per request for an in-memory store but would need indexing in a production database. I accepted this trade-off because the challenge scope is single-store, single-day data where n is small enough.

### 3. API Architecture Choice
**Options Considered:** Flask, Express.js, FastAPI.
**What AI Suggested:** FastAPI for its asynchronous capabilities and native JSON validation.
**What I Chose and Why:** I chose FastAPI. The challenge required strict data schemas and handling up to 500 events per batch. FastAPI's Pydantic integration meant I didn't have to write manual data validation loops — malformed events automatically receive a 422 response with structured error details. Its async routing ensures the `/events/ingest` endpoint won't block the `/metrics` endpoint during heavy foot-traffic periods in the store.

**Storage Decision:** I used an in-memory Python dict keyed by `event_id` for O(1) idempotency checks. The AI suggested SQLite for persistence, but I chose in-memory for simplicity within the challenge scope. The dict approach means the API restarts clean, which is actually desirable for a demo — the detection pipeline re-emits from the JSONL file at any time. For production, I would use PostgreSQL with a unique constraint on `event_id`.
