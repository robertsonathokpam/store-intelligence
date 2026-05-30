import cv2
import json
import uuid
from datetime import datetime, timezone
from ultralytics import YOLO

# Initialize the model
model = YOLO('yolov8n.pt') 

def process_video(video_path: str, store_id: str, camera_id: str, output_file: str):
    events = []
    
    # Run tracking with explicit ByteTrack configuration for better stability
    results = model.track(source=video_path, stream=True, classes=[0], persist=True, tracker="bytetrack.yaml")

    for frame_idx, r in enumerate(results):
        # If no detections at all in this frame, skip
        if r.boxes is None or len(r.boxes) == 0:
            continue
            
        boxes = r.boxes.xyxy.cpu().numpy()
        confidences = r.boxes.conf.cpu().tolist()
        
        # Safe extraction of tracking IDs; fallback to a default if tracking is dropped
        if r.boxes.id is not None:
            track_ids = r.boxes.id.int().cpu().tolist()
        else:
            track_ids = [None] * len(boxes)
        
        for idx, (box, conf) in enumerate(zip(boxes, confidences)):
            track_id = track_ids[idx]
            
            # Generate a reliable visitor ID string
            visitor_str = f"VIS_{track_id}" if track_id is not None else f"DET_UNTRACKED_{frame_idx}_{idx}"
            
            # Construct the event payload matching the Pydantic schema
            event = {
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": camera_id,
                "visitor_id": visitor_str,
                "event_type": "ZONE_DWELL",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "zone_id": "MAIN_FLOOR",
                "dwell_ms": 1000,  # Baseline estimation per frame hit
                "is_staff": False,
                "confidence": round(conf, 2),
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": None,
                    "session_seq": frame_idx
                }
            }
            events.append(event)
            
        # Optional: Prevent log explosion during development by capping events per run
        if len(events) >= 500:
            break

    # Write out the structural JSON Lines format
    with open(output_file, 'w') as f:
        for event in events:
            f.write(json.dumps(event) + '\n')
            
    print(f"--- SUCCESS ---")
    print(f"Processed {len(events)} bounding boxes.")
    print(f"Saved logs to: {output_file}")

if __name__ == "__main__":
    process_video(
        video_path=r"CAM 1.mp4", 
        store_id="STORE_001", 
        camera_id="CAM_01", 
        output_file="output_events.jsonl"
    )

    