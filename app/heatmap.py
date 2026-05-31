import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import StoreEvent
from typing import List, Dict


def calculate_heatmap(store_id: str, events: List[StoreEvent]) -> Dict:
    """
    Zone visit frequency + avg dwell, normalised 0–100 for grid rendering.
    Includes data_confidence flag if fewer than 20 unique sessions.
    
    Normalisation: the zone with the highest unique visitor count = 100,
    all other zones are scaled proportionally.
    """
    customer_events = [e for e in events if e.store_id == store_id and not e.is_staff]

    zone_visitors: Dict[str, set] = {}   # zone_id → set of visitor_ids
    zone_dwell_ms: Dict[str, int] = {}   # zone_id → total dwell milliseconds

    all_visitors = set()

    for event in customer_events:
        all_visitors.add(event.visitor_id)

        if not event.zone_id:
            continue

        zone = event.zone_id
        if zone not in zone_visitors:
            zone_visitors[zone] = set()
            zone_dwell_ms[zone] = 0

        zone_visitors[zone].add(event.visitor_id)
        if event.dwell_ms > 0:
            zone_dwell_ms[zone] += event.dwell_ms

    if not zone_visitors:
        return {
            "store_id": store_id,
            "zones": [],
            "data_confidence": "LOW",
        }

    max_visits = max(len(v) for v in zone_visitors.values())

    zones = []
    for zone_id in sorted(zone_visitors.keys()):
        visit_count = len(zone_visitors[zone_id])
        total_dwell = zone_dwell_ms.get(zone_id, 0)
        avg_dwell_sec = round((total_dwell / visit_count) / 1000, 2) if visit_count > 0 else 0.0
        normalised = round((visit_count / max_visits) * 100, 2) if max_visits > 0 else 0

        zones.append({
            "zone_id": zone_id,
            "visit_count": visit_count,
            "avg_dwell_seconds": avg_dwell_sec,
            "normalised_score": normalised,
        })

    zones.sort(key=lambda z: z["normalised_score"], reverse=True)

    return {
        "store_id": store_id,
        "zones": zones,
        "data_confidence": "LOW" if len(all_visitors) < 20 else "HIGH",
    }
