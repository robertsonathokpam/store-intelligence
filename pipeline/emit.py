"""
Event emitter — streams batched events from output_events.jsonl to the API.

Chunks to a maximum of 500 events per request (API constraint).
Includes basic retry logic for transient failures.
"""

import json
import sys
import time
import requests


def send_events(file_path: str, api_url: str, batch_size: int = 500, max_retries: int = 3):
    events = []

    with open(file_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                events.append(json.loads(stripped))

    print(f"Loaded {len(events)} events from {file_path}")

    if not events:
        print("No events to send.")
        return

    total_inserted = 0
    total_ignored = 0
    total_batches = (len(events) + batch_size - 1) // batch_size

    for i in range(0, len(events), batch_size):
        batch = events[i : i + batch_size]
        batch_num = i // batch_size + 1
        print(f"Sending batch {batch_num}/{total_batches} (size: {len(batch)})...")

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(api_url, json=batch, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    total_inserted += data.get("inserted", 0)
                    total_ignored += data.get("ignored_duplicates", 0)
                    print(f"  [OK] Batch {batch_num} SUCCESS: {data}")
                    break
                else:
                    print(f"  [FAIL] Batch {batch_num} FAILED (status {response.status_code})")
                    print(f"     Details: {response.text[:200]}")
                    if attempt < max_retries:
                        print(f"     Retrying ({attempt}/{max_retries})...")
                        time.sleep(1)
                    break  # Don't retry 4xx errors

            except requests.exceptions.RequestException as exc:
                print(f"  [WARN] Batch {batch_num} connection error: {exc}")
                if attempt < max_retries:
                    print(f"     Retrying in 2s ({attempt}/{max_retries})...")
                    time.sleep(2)
                else:
                    print(f"  [FAIL] Batch {batch_num} FAILED after {max_retries} retries")

    print(f"\n═══ EMIT COMPLETE ═══")
    print(f"  Total inserted:   {total_inserted}")
    print(f"  Total duplicates: {total_ignored}")
    print(f"  Total events:     {len(events)}")


if __name__ == "__main__":
    send_events(
        file_path="output_events.jsonl",
        api_url="https://store-intelligence-api-x283.onrender.com/events/ingest",
    )