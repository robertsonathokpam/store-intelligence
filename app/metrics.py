import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import StoreEvent
from typing import List, Dict, Set


def calculate_store_metrics(
    store_id: str,
    events: List[StoreEvent],
    converted_visitor_ids: Set[str] = None,
) -> Dict:
    """
    Compute real-time store metrics from ingested events.

    Metrics returned:
        - unique_visitors      (excluding staff)
        - conversion_rate      (POS-correlated when available, else billing-queue based)
        - avg_dwell_per_zone_seconds
        - queue_abandonment_rate_percent
        - data_confidence      (LOW if < 20 sessions)

    Args:
        store_id:  Target store identifier.
        events:    Full list of ingested StoreEvent objects.
        converted_visitor_ids:  Optional set of visitor_ids confirmed converted
                                via POS transaction correlation.  Falls back to
                                billing-queue heuristic when None / empty.
    """
    # Filter out staff — crucial requirement from the prompt
    customer_events = [e for e in events if e.store_id == store_id and not e.is_staff]

    unique_visitors = set()
    zone_dwell_times: Dict[str, int] = {}
    zone_visitors: Dict[str, set] = {}
    queue_joins = 0
    queue_abandons = 0

    queue_joiners: set = set()
    queue_abandoners: set = set()

    for event in customer_events:
        unique_visitors.add(event.visitor_id)

        # Accumulate dwell per zone
        if event.zone_id and event.dwell_ms > 0:
            zone_dwell_times[event.zone_id] = zone_dwell_times.get(event.zone_id, 0) + event.dwell_ms
            if event.zone_id not in zone_visitors:
                zone_visitors[event.zone_id] = set()
            zone_visitors[event.zone_id].add(event.visitor_id)

        # Track billing-queue flow
        if event.event_type == "BILLING_QUEUE_JOIN":
            queue_joins += 1
            queue_joiners.add(event.visitor_id)
        elif event.event_type == "BILLING_QUEUE_ABANDON":
            queue_abandons += 1
            queue_abandoners.add(event.visitor_id)

    # Average dwell per zone (ms → seconds, averaged over unique visitors)
    avg_dwell_per_zone: Dict[str, float] = {}
    for zone, total_ms in zone_dwell_times.items():
        n = len(zone_visitors.get(zone, set()))
        avg_dwell_per_zone[zone] = round((total_ms / n) / 1000, 2) if n > 0 else 0.0

    # Queue abandonment rate
    abandonment_rate = 0.0
    if queue_joins > 0:
        abandonment_rate = round((queue_abandons / queue_joins) * 100, 2)

    # Conversion rate — prefer POS-correlated, fall back to billing-queue heuristic
    total_sessions = len(unique_visitors)
    conversion_rate = 0.0

    if converted_visitor_ids and total_sessions > 0:
        # POS-correlated conversion (primary)
        store_converted = converted_visitor_ids & unique_visitors
        conversion_rate = round((len(store_converted) / total_sessions) * 100, 2)
    elif total_sessions > 0:
        # Billing-queue heuristic (fallback)
        inferred_converted = queue_joiners - queue_abandoners
        conversion_rate = round((len(inferred_converted) / total_sessions) * 100, 2)

    return {
        "store_id": store_id,
        "unique_visitors": total_sessions,
        "avg_dwell_per_zone_seconds": avg_dwell_per_zone,
        "queue_abandonment_rate_percent": abandonment_rate,
        "conversion_rate": conversion_rate,
        # The prompt requires this flag if sessions < 20
        "data_confidence": "LOW" if total_sessions < 20 else "HIGH",
    }
