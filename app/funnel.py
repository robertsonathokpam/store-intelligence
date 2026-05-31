import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import StoreEvent
from typing import List, Dict


def calculate_funnel(store_id: str, events: List[StoreEvent], converted_visitor_ids: set = None) -> Dict:
    """
    Calculate conversion funnel: Entry → Zone Visit → Billing Queue → Purchase.
    
    Session-based — each visitor is counted once regardless of how many events
    they generate. Re-entries do NOT double-count a visitor in any stage.
    
    Args:
        store_id: The store to compute funnel for.
        events: All ingested events.
        converted_visitor_ids: Set of visitor_ids confirmed as converted via POS correlation.
    """
    customer_events = [e for e in events if e.store_id == store_id and not e.is_staff]

    if converted_visitor_ids is None:
        converted_visitor_ids = set()

    # Track unique visitors at each funnel stage
    entered = set()
    zone_visited = set()
    billing_queue = set()
    abandoners = set()

    for event in customer_events:
        vid = event.visitor_id

        if event.event_type in ("ENTRY", "REENTRY"):
            entered.add(vid)

        if event.event_type in ("ZONE_ENTER", "ZONE_DWELL", "ZONE_EXIT"):
            zone_visited.add(vid)
            entered.add(vid)  # Implicit entry if we see zone activity

        if event.event_type == "BILLING_QUEUE_JOIN":
            billing_queue.add(vid)
            zone_visited.add(vid)
            entered.add(vid)

        if event.event_type == "BILLING_QUEUE_ABANDON":
            abandoners.add(vid)

    # Purchased = POS-correlated visitors, OR joined billing and didn't abandon
    purchased = converted_visitor_ids.copy()
    purchased |= (billing_queue - abandoners)

    # Fallback: if no explicit ENTRY events, every customer who appears entered
    if not entered:
        entered = set(e.visitor_id for e in customer_events)
    if not zone_visited:
        zone_visited = set(e.visitor_id for e in customer_events if e.zone_id)

    total = len(entered) if entered else 1

    def _pct(n):
        return round((n / total) * 100, 2) if total > 0 else 0.0

    stages = [
        {
            "stage": "Entry",
            "count": len(entered),
            "percentage": 100.0,
            "drop_off_percent": 0.0,
        },
        {
            "stage": "Zone Visit",
            "count": len(zone_visited),
            "percentage": _pct(len(zone_visited)),
            "drop_off_percent": _pct(len(entered) - len(zone_visited)),
        },
        {
            "stage": "Billing Queue",
            "count": len(billing_queue),
            "percentage": _pct(len(billing_queue)),
            "drop_off_percent": _pct(len(zone_visited) - len(billing_queue)),
        },
        {
            "stage": "Purchase",
            "count": len(purchased),
            "percentage": _pct(len(purchased)),
            "drop_off_percent": _pct(len(billing_queue) - len(purchased)),
        },
    ]

    return {
        "store_id": store_id,
        "total_sessions": len(entered),
        "stages": stages,
    }
