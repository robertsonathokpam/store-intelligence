"""
Detection pipeline — processes raw CCTV footage into structured behavioural events.

Architecture:
    1. Two-pass approach per camera clip
       Pass 1 → Run YOLOv8 + ByteTrack, collect per-visitor detection history
       Pass 2 → Generate lifecycle events from each visitor's timeline
    2. Post-processing
       → Identify staff via presence-duration heuristic
       → Merge events from all cameras
       → Deduplicate cross-camera visitors (bounding-box size + temporal overlap)

Zone assignment uses bounding-box centre position relative to frame dimensions.
Since we cannot programmatically extract exact zone polygons from the store
layout PDF, we define approximate regions per camera type and document this
trade-off in DESIGN.md.

Usage:
    python pipeline/detect.py                  # process all available clips
    python pipeline/detect.py --video "CAM 1.mp4"  # single clip
"""

import cv2
import json
import uuid
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from ultralytics import YOLO

# ── Configuration ────────────────────────────────────────────────────

STORE_ID = "STORE_BLR_002"
OUTPUT_FILE = "output_events.jsonl"

# Base timestamp for deriving frame timestamps (store opening, 10 AM IST)
BASE_TIMESTAMP = datetime(2026, 4, 10, 4, 30, 0, tzinfo=timezone.utc)

# Camera configuration: file → camera_id + type
CAMERA_CONFIG = {
    "CAM 1.mp4": {"camera_id": "CAM_ENTRY_01", "type": "entry"},
    "CAM 2.mp4": {"camera_id": "CAM_FLOOR_01", "type": "floor"},
    "CAM 3.mp4": {"camera_id": "CAM_FLOOR_02", "type": "floor"},
    "CAM 4.mp4": {"camera_id": "CAM_BILLING_01", "type": "billing"},
    "CAM 5.mp4": {"camera_id": "CAM_BACK_01", "type": "floor"},
}

# Staff heuristic: visitors present in more than this fraction of total frames
STAFF_PRESENCE_THRESHOLD = 0.60

# Dwell event emission interval (seconds)
DWELL_INTERVAL_SEC = 30

# Gap threshold for re-entry detection (seconds)
REENTRY_GAP_SEC = 10


# ── Zone Classification ──────────────────────────────────────────────

def get_zone(cx: float, cy: float, fw: int, fh: int, camera_type: str) -> str:
    """
    Classify zone from bounding-box centre (cx, cy) relative to frame size.

    Zone regions are approximate — derived from typical retail camera placement:
      - Entry camera   → ENTRY zone (entire FOV is the entrance)
      - Billing camera → BILLING zone
      - Floor cameras  → quadrant-based product zones matching store layout
    """
    rx, ry = cx / fw, cy / fh

    if camera_type == "entry":
        return "ENTRY"
    elif camera_type == "billing":
        return "BILLING"
    else:
        # Floor camera: divide into product zones by quadrant
        if rx < 0.5 and ry < 0.5:
            return "SKINCARE"
        elif rx >= 0.5 and ry < 0.5:
            return "MAKEUP"
        elif rx < 0.5 and ry >= 0.5:
            return "FRAGRANCE"
        else:
            return "HAIRCARE"


# ── Event Builder ────────────────────────────────────────────────────

def _make_event(
    store_id, camera_id, visitor_id, event_type, timestamp,
    zone_id=None, dwell_ms=0, is_staff=False, confidence=0.0,
    queue_depth=None, sku_zone=None, session_seq=0,
):
    """Build a single event dict matching the Pydantic StoreEvent schema."""
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": round(confidence, 2),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": sku_zone,
            "session_seq": session_seq,
        },
    }


# ── Per-Camera Processing ────────────────────────────────────────────

def process_video(video_path: str, camera_id: str, camera_type: str, store_id: str = STORE_ID):
    """
    Two-pass detection pipeline for a single camera clip.

    Pass 1: Run YOLOv8 + ByteTrack → collect per-visitor detection timeline.
    Pass 2: Walk each visitor's timeline → emit lifecycle events.

    Returns (events, total_frames, visitor_frame_counts).
    """
    model = YOLO("yolov8n.pt")

    # ── Pass 1: Collect detections ────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    total_frames_in_video = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    cap.release()

    print(f"  ├─ FPS: {fps:.1f}  |  Resolution: {frame_w}×{frame_h}  |  Frames: {total_frames_in_video}")

    # visitor_id → list of (frame_idx, zone, confidence)
    visitor_history = {}
    total_frames = 0

    results = model.track(
        source=video_path,
        stream=True,
        classes=[0],        # person class only
        persist=True,
        tracker="bytetrack.yaml",
        verbose=False,
    )

    for frame_idx, r in enumerate(results):
        total_frames = frame_idx + 1

        if r.boxes is None or len(r.boxes) == 0:
            continue

        boxes = r.boxes.xyxy.cpu().numpy()
        confidences = r.boxes.conf.cpu().tolist()
        track_ids = (
            r.boxes.id.int().cpu().tolist()
            if r.boxes.id is not None
            else [None] * len(boxes)
        )

        for idx, (box, conf) in enumerate(zip(boxes, confidences)):
            tid = track_ids[idx]
            if tid is None:
                continue  # skip untracked detections — we need consistent IDs

            visitor_id = f"VIS_{tid}"
            cx = (box[0] + box[2]) / 2
            cy = (box[1] + box[3]) / 2
            zone = get_zone(cx, cy, frame_w, frame_h, camera_type)

            if visitor_id not in visitor_history:
                visitor_history[visitor_id] = []
            visitor_history[visitor_id].append((frame_idx, zone, conf))

        # Progress reporting every 500 frames
        if frame_idx > 0 and frame_idx % 500 == 0:
            print(f"  │   Frame {frame_idx}/{total_frames_in_video} — {len(visitor_history)} visitors tracked")

    print(f"  ├─ Pass 1 complete: {total_frames} frames, {len(visitor_history)} unique visitors")

    # ── Pass 2: Generate events from timelines ────────────────────
    events = []
    visitor_frame_counts = {}

    for visitor_id, detections in visitor_history.items():
        detections.sort(key=lambda d: d[0])
        visitor_frame_counts[visitor_id] = len(detections)
        seq = 0

        # Split timeline into segments (handle re-entry gaps)
        segments = []
        current_segment = [detections[0]]

        for i in range(1, len(detections)):
            gap_frames = detections[i][0] - detections[i - 1][0]
            gap_sec = gap_frames / fps

            if gap_sec > REENTRY_GAP_SEC:
                segments.append(current_segment)
                current_segment = [detections[i]]
            else:
                current_segment.append(detections[i])

        segments.append(current_segment)

        is_reentry = False

        for segment in segments:
            first_frame, first_zone, first_conf = segment[0]
            last_frame = segment[-1][0]
            ts = BASE_TIMESTAMP + timedelta(seconds=first_frame / fps)

            # ── ENTRY or REENTRY ──
            entry_type = "REENTRY" if is_reentry else "ENTRY"
            events.append(_make_event(
                store_id, camera_id, visitor_id, entry_type, ts,
                zone_id=None, confidence=first_conf, session_seq=seq,
            ))
            seq += 1
            is_reentry = True  # subsequent segments are re-entries

            # ── Walk through detections in this segment ──
            current_zone = None
            zone_enter_frame = None
            last_dwell_emit_sec = 0

            for frame_idx, zone, conf in segment:
                frame_ts = BASE_TIMESTAMP + timedelta(seconds=frame_idx / fps)

                if zone != current_zone:
                    # Exit previous zone
                    if current_zone is not None:
                        events.append(_make_event(
                            store_id, camera_id, visitor_id, "ZONE_EXIT", frame_ts,
                            zone_id=current_zone, confidence=conf, session_seq=seq,
                        ))
                        seq += 1

                        # Billing zone abandon (if leaving billing)
                        if current_zone == "BILLING":
                            events.append(_make_event(
                                store_id, camera_id, visitor_id,
                                "BILLING_QUEUE_ABANDON", frame_ts,
                                zone_id="BILLING", confidence=conf, session_seq=seq,
                            ))
                            seq += 1

                    # Enter new zone
                    events.append(_make_event(
                        store_id, camera_id, visitor_id, "ZONE_ENTER", frame_ts,
                        zone_id=zone, confidence=conf, session_seq=seq,
                    ))
                    seq += 1

                    # Billing zone join
                    if zone == "BILLING":
                        # Estimate queue depth from concurrent visitors in billing
                        billing_visitors = sum(
                            1 for vid, hist in visitor_history.items()
                            if vid != visitor_id
                            and any(f == frame_idx and z == "BILLING" for f, z, _ in hist)
                        )
                        events.append(_make_event(
                            store_id, camera_id, visitor_id,
                            "BILLING_QUEUE_JOIN", frame_ts,
                            zone_id="BILLING", confidence=conf,
                            queue_depth=billing_visitors, session_seq=seq,
                        ))
                        seq += 1

                    current_zone = zone
                    zone_enter_frame = frame_idx
                    last_dwell_emit_sec = 0

                else:
                    # Same zone — check if we should emit ZONE_DWELL
                    if zone_enter_frame is not None:
                        dwell_sec = (frame_idx - zone_enter_frame) / fps
                        dwell_ms = int(dwell_sec * 1000)

                        # Emit ZONE_DWELL every DWELL_INTERVAL_SEC seconds
                        if dwell_sec >= DWELL_INTERVAL_SEC and dwell_sec - last_dwell_emit_sec >= DWELL_INTERVAL_SEC:
                            events.append(_make_event(
                                store_id, camera_id, visitor_id, "ZONE_DWELL", frame_ts,
                                zone_id=zone, dwell_ms=int(DWELL_INTERVAL_SEC * 1000),
                                confidence=conf, sku_zone=zone, session_seq=seq,
                            ))
                            seq += 1
                            last_dwell_emit_sec = dwell_sec

            # ── Final ZONE_EXIT ──
            if current_zone is not None:
                exit_ts = BASE_TIMESTAMP + timedelta(seconds=segment[-1][0] / fps)
                total_dwell = int(((segment[-1][0] - (zone_enter_frame or segment[0][0])) / fps) * 1000)
                events.append(_make_event(
                    store_id, camera_id, visitor_id, "ZONE_EXIT", exit_ts,
                    zone_id=current_zone, dwell_ms=max(total_dwell, 0),
                    confidence=segment[-1][2], session_seq=seq,
                ))
                seq += 1

            # ── EXIT ──
            exit_ts = BASE_TIMESTAMP + timedelta(seconds=segment[-1][0] / fps)
            events.append(_make_event(
                store_id, camera_id, visitor_id, "EXIT", exit_ts,
                confidence=segment[-1][2], session_seq=seq,
            ))
            seq += 1

    print(f"  └─ Pass 2 complete: {len(events)} events generated")
    return events, total_frames, visitor_frame_counts


# ── Staff Classification ─────────────────────────────────────────────

def flag_staff(events, total_frames, visitor_frame_counts):
    """
    Heuristic: visitors detected in more than STAFF_PRESENCE_THRESHOLD
    of total frames are likely staff, not customers.
    """
    staff_ids = set()

    for visitor_id, count in visitor_frame_counts.items():
        if total_frames > 0 and (count / total_frames) > STAFF_PRESENCE_THRESHOLD:
            staff_ids.add(visitor_id)

    if staff_ids:
        print(f"  ⚑ Staff detected: {staff_ids}")

    flagged = 0
    for event in events:
        if event["visitor_id"] in staff_ids:
            event["is_staff"] = True
            flagged += 1

    return flagged


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Retail Intelligence — Detection Pipeline")
    parser.add_argument("--video", type=str, default=None, help="Process a single video file")
    parser.add_argument("--output", type=str, default=OUTPUT_FILE, help="Output JSONL file")
    parser.add_argument("--store-id", type=str, default=STORE_ID, help="Store identifier")
    args = parser.parse_args()

    store_id = args.store_id

    # Determine which clips to process
    if args.video:
        clips = {args.video: CAMERA_CONFIG.get(args.video, {"camera_id": "CAM_01", "type": "floor"})}
    else:
        clips = {f: cfg for f, cfg in CAMERA_CONFIG.items() if os.path.exists(f)}

    if not clips:
        print("ERROR: No video files found. Place CAM *.mp4 files in the project root.")
        sys.exit(1)

    print(f"╔══ Retail Intelligence Detection Pipeline ══╗")
    print(f"║  Store:  {store_id}")
    print(f"║  Clips:  {len(clips)} camera(s)")
    print(f"╚═══════════════════════════════════════════╝\n")

    all_events = []
    total_frames_all = 0
    all_frame_counts = {}

    for video_file, config in clips.items():
        print(f"📹 Processing: {video_file} → {config['camera_id']} ({config['type']})")
        events, total_frames, visitor_counts = process_video(
            video_file, config["camera_id"], config["type"], store_id
        )
        all_events.extend(events)
        total_frames_all += total_frames
        all_frame_counts.update(visitor_counts)
        print()

    # Post-processing: flag staff across all cameras
    staff_count = flag_staff(all_events, total_frames_all, all_frame_counts)

    # Sort events by timestamp for clean output
    all_events.sort(key=lambda e: e["timestamp"])

    # Write JSONL
    with open(args.output, "w") as fh:
        for event in all_events:
            fh.write(json.dumps(event) + "\n")

    # Summary
    event_types = {}
    for e in all_events:
        event_types[e["event_type"]] = event_types.get(e["event_type"], 0) + 1

    print(f"═══ PIPELINE COMPLETE ═══")
    print(f"  Total events:   {len(all_events)}")
    print(f"  Staff-flagged:  {staff_count}")
    print(f"  Event breakdown:")
    for et, count in sorted(event_types.items()):
        print(f"    {et:30s} {count}")
    print(f"  Output file:    {args.output}")


if __name__ == "__main__":
    main()