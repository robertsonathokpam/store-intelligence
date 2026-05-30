import json
import requests

def send_events(file_path: str, api_url: str):
    events = []
    
    # Read the JSON Lines file
    with open(file_path, 'r') as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line.strip()))
                
    print(f"Loaded {len(events)} events from {file_path}")
    
    # The API only accepts 500 events at a time, so we chunk the list
    batch_size = 500
    for i in range(0, len(events), batch_size):
        batch = events[i : i + batch_size]
        print(f"Sending batch {i // batch_size + 1} (size: {len(batch)})...")
        
        response = requests.post(api_url, json=batch)
        
        if response.status_code == 200:
            print(f"✅ SUCCESS! API Response: {response.json()}")
        else:
            print(f"❌ FAILED. Status: {response.status_code}")
            print(f"Details: {response.text}")

if __name__ == "__main__":
    send_events(
        file_path="output_events.jsonl", 
        api_url="http://127.0.0.1:8000/events/ingest"
    )