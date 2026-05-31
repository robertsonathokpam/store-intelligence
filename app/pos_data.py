"""
POS transaction loader and visitor-session correlator.

The raw CSV from Brigade_Bangalore uses columns like order_id, order_date,
order_time, invoice_number, store_id (ST1008), total_amount.  This module
normalises that into the challenge-standard schema:

    store_id, transaction_id, timestamp, basket_value_inr

Conversion correlation: a visitor who was detected in the BILLING zone
within a configurable time window (default 5 min) *before* a POS
transaction counts as a converted visitor for that session.
"""

import csv
import os
import glob
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set

# Mapping from raw CSV store_id to challenge store_id
STORE_ID_MAP = {
    "ST1008": "STORE_BLR_002",
}

# Default time-window for POS ↔ visitor correlation (seconds)
CORRELATION_WINDOW_SEC = 5 * 60  # 5 minutes


def _find_pos_csv() -> str | None:
    """Search well-known paths for the POS CSV file."""
    search_dirs = [
        os.path.join(os.path.dirname(__file__), "data"),
        os.path.join(os.path.dirname(__file__), "..", "hackathon-resources"),
        os.path.join(os.path.dirname(__file__), "..", "data"),
    ]
    for d in search_dirs:
        pattern = os.path.join(d, "*.csv")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


def load_pos_transactions(file_path: str = None) -> List[Dict]:
    """
    Load and normalise POS transactions.

    Returns a list of dicts:
        {store_id, transaction_id, timestamp (datetime), basket_value_inr}
    """
    if file_path is None:
        file_path = _find_pos_csv()
    if not file_path or not os.path.exists(file_path):
        return []

    aggregated: Dict[str, Dict] = {}

    try:
        with open(file_path, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                invoice = row.get("invoice_number", "").strip()
                if not invoice:
                    continue

                order_date = row.get("order_date", "").strip()
                order_time = row.get("order_time", "").strip()
                try:
                    dt = datetime.strptime(f"{order_date} {order_time}", "%d-%m-%Y %H:%M:%S")
                    dt = dt.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue

                raw_store = row.get("store_id", "").strip()
                store_id = STORE_ID_MAP.get(raw_store, raw_store)

                try:
                    amount = float(row.get("total_amount", 0))
                except (ValueError, TypeError):
                    amount = 0.0

                if invoice not in aggregated:
                    aggregated[invoice] = {
                        "store_id": store_id,
                        "transaction_id": invoice,
                        "timestamp": dt,
                        "basket_value_inr": 0.0,
                    }
                aggregated[invoice]["basket_value_inr"] += amount
    except Exception:
        return []

    return list(aggregated.values())


def get_converted_visitors(
    pos_transactions: List[Dict],
    events,
    store_id: str = None,
    window_sec: int = CORRELATION_WINDOW_SEC,
) -> Set[str]:
    """
    Correlate POS transactions with visitor sessions.

    A visitor detected in the BILLING zone within `window_sec` seconds
    *before* a POS transaction timestamp counts as converted.
    """
    converted: Set[str] = set()

    billing_events = []
    for e in events:
        if hasattr(e, "is_staff") and e.is_staff:
            continue
        if store_id and hasattr(e, "store_id") and e.store_id != store_id:
            continue
        zone = getattr(e, "zone_id", None) or ""
        if "BILLING" in zone.upper():
            billing_events.append(e)

    for txn in pos_transactions:
        if store_id and txn.get("store_id") != store_id:
            continue

        txn_time = txn["timestamp"]
        if isinstance(txn_time, str):
            txn_time = datetime.fromisoformat(txn_time.replace("Z", "+00:00"))

        for event in billing_events:
            evt_time = event.timestamp
            diff = (txn_time - evt_time).total_seconds()
            # Visitor must be seen BEFORE the transaction, within the window
            if 0 <= diff <= window_sec:
                converted.add(event.visitor_id)

    return converted
