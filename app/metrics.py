import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import StoreEvent
from typing import List, Dict


def calculate_store_metrics(store_id: str, events: List[StoreEvent]) -> Dict:
    # Filter out staff - crucial requirement from the prompt
    customer_events = [e for e in events if e.store_id == store_id and not e.is_staff]
    
    unique_visitors = set()
    zone_dwell_times = {}
    zone_visitors = {}
    queue_joins = 0
    queue_abandons = 0
    
    # Keep track of which visitors joined or abandoned the billing queue
    queue_joiners = set()
    queue_abandoners = set()

    for event in customer_events:
        unique_visitors.add(event.visitor_id)
        
        # Calculate average dwell time per zone
        if event.zone_id and event.dwell_ms > 0:
            zone_dwell_times[event.zone_id] = zone_dwell_times.get(event.zone_id, 0) + event.dwell_ms
            if event.zone_id not in zone_visitors:
                zone_visitors[event.zone_id] = set()
            zone_visitors[event.zone_id].add(event.visitor_id)
            
        # Track abandonment rate
        if event.event_type == "BILLING_QUEUE_JOIN":
            queue_joins += 1
            queue_joiners.add(event.visitor_id)
        elif event.event_type == "BILLING_QUEUE_ABANDON":
            queue_abandons += 1
            queue_abandoners.add(event.visitor_id)

    # Format the dwell times into averages (converting ms to seconds, averaged over unique visitors in that zone)
    avg_dwell_per_zone = {}
    for zone, total_ms in zone_dwell_times.items():
        num_zone_visitors = len(zone_visitors.get(zone, set()))
        if num_zone_visitors > 0:
            avg_dwell_per_zone[zone] = round((total_ms / num_zone_visitors) / 1000, 2)
        else:
            avg_dwell_per_zone[zone] = 0.0

    # Calculate abandonment rate safely
    abandonment_rate = 0.0
    if queue_joins > 0:
        abandonment_rate = round((queue_abandons / queue_joins) * 100, 2)

    # Calculate inferred conversion rate (joined billing queue and didn't abandon)
    converted_visitors = queue_joiners - queue_abandoners
    total_sessions = len(unique_visitors)
    conversion_rate = 0.0
    if total_sessions > 0:
        conversion_rate = round((len(converted_visitors) / total_sessions) * 100, 2)

    return {
        "store_id": store_id,
        "unique_visitors": total_sessions,
        "avg_dwell_per_zone_seconds": avg_dwell_per_zone,
        "queue_abandonment_rate_percent": abandonment_rate,
        "conversion_rate": conversion_rate,
        # The prompt requires this flag if sessions < 20
        "data_confidence": "LOW" if total_sessions < 20 else "HIGH"
    }

