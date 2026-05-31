import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import StoreEvent
from typing import List, Dict
from datetime import timedelta


def detect_anomalies(store_id: str, events: List[StoreEvent]) -> Dict:
    """
    Detect operational anomalies across three categories:

    1. BILLING_QUEUE_SPIKE  — queue_depth exceeds threshold
    2. CONVERSION_DROP      — conversion rate significantly below expected baseline
    3. DEAD_ZONE            — a zone receives no visits for 30+ minutes

    Each anomaly carries a severity (INFO / WARN / CRITICAL) and a
    human-readable suggested_action string for the ops team.
    """
    customer_events = [e for e in events if e.store_id == store_id and not e.is_staff]

    anomalies = []

    # ── 1. BILLING_QUEUE_SPIKE ────────────────────────────────────────
    max_queue_depth = 0
    for event in customer_events:
        if event.metadata and event.metadata.queue_depth is not None:
            max_queue_depth = max(max_queue_depth, event.metadata.queue_depth)

    if max_queue_depth >= 5:
        if max_queue_depth >= 10:
            severity = "CRITICAL"
        elif max_queue_depth >= 7:
            severity = "WARN"
        else:
            severity = "INFO"

        anomalies.append({
            "type": "BILLING_QUEUE_SPIKE",
            "severity": severity,
            "details": f"Queue depth reached {max_queue_depth} visitors",
            "suggested_action": "Open additional billing counter or deploy floor staff to manage queue",
        })

    # ── 2. CONVERSION_DROP ────────────────────────────────────────────
    unique_visitors = set()
    queue_joiners = set()
    queue_abandoners = set()

    for event in customer_events:
        unique_visitors.add(event.visitor_id)
        if event.event_type == "BILLING_QUEUE_JOIN":
            queue_joiners.add(event.visitor_id)
        elif event.event_type == "BILLING_QUEUE_ABANDON":
            queue_abandoners.add(event.visitor_id)

    if len(unique_visitors) >= 5:
        converted = queue_joiners - queue_abandoners
        conversion_rate = (len(converted) / len(unique_visitors)) * 100

        # Retail baseline: flag if conversion is below 20%
        if conversion_rate < 20:
            severity = "CRITICAL" if conversion_rate < 5 else "WARN"
            anomalies.append({
                "type": "CONVERSION_DROP",
                "severity": severity,
                "details": f"Conversion rate is {round(conversion_rate, 2)}% — below 20% baseline",
                "suggested_action": "Review product placement and staff engagement in high-traffic zones",
            })

    # ── 3. DEAD_ZONE ─────────────────────────────────────────────────
    zone_last_seen = {}
    latest_event_time = None

    for event in customer_events:
        if event.zone_id:
            prev = zone_last_seen.get(event.zone_id)
            if prev is None or event.timestamp > prev:
                zone_last_seen[event.zone_id] = event.timestamp
        if latest_event_time is None or event.timestamp > latest_event_time:
            latest_event_time = event.timestamp

    if latest_event_time and zone_last_seen:
        for zone_id, last_seen in zone_last_seen.items():
            gap_seconds = (latest_event_time - last_seen).total_seconds()
            if gap_seconds > 1800:  # 30 minutes
                anomalies.append({
                    "type": "DEAD_ZONE",
                    "severity": "INFO",
                    "details": f"Zone '{zone_id}' has had no visits for {int(gap_seconds // 60)} minutes",
                    "suggested_action": f"Investigate if zone '{zone_id}' signage or product display needs refresh",
                })

    return {
        "store_id": store_id,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
    }
