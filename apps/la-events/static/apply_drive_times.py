"""
Fill drive_time_min (and refresh distance_miles) for every event in events.json
using Google Maps Platform **Routes API** (new).

Requires these APIs enabled on the GCP project:
  - Routes API
  - Billing (Maps Platform needs a billing account)

Usage:
  1. Save an API key at:
       C:/Users/bubakazouba/chat-assistant/credentials/google_maps_key.txt
  2. python apply_drive_times.py

Departure time: next Saturday 11:00am local — used for traffic-aware estimate.
"""
import json, os, sys, datetime, urllib.request

HOME = "1299 Cordova St, Pasadena, CA"
KEY_PATH = r"C:\Users\bubakazouba\chat-assistant\credentials\google_maps_key.txt"
ENDPOINT = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

def next_sat_11am_utc():
    now = datetime.datetime.now().astimezone()
    days_until_sat = (5 - now.weekday()) % 7 or 7
    sat = (now + datetime.timedelta(days=days_until_sat)).replace(
        hour=11, minute=0, second=0, microsecond=0)
    return sat.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def compute_matrix(key, origins, destinations, departure):
    body = {
        "origins": [{"waypoint": {"address": o}} for o in origins],
        "destinations": [{"waypoint": {"address": d}} for d in destinations],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": departure,
    }
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,condition",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def main():
    if not os.path.exists(KEY_PATH):
        print(f"No key at {KEY_PATH} — aborting.", file=sys.stderr)
        sys.exit(1)
    key = open(KEY_PATH).read().strip()

    with open("events.json", encoding="utf-8") as f:
        data = json.load(f)

    departure = next_sat_11am_utc()
    print(f"Departure time for traffic estimate: {departure}")

    # Collect all events with a resolvable venue. Skip non-geocodable placeholder
    # venues ("secret location", "TBA", "address revealed to ticket holders") —
    # one bad waypoint 400s the whole Routes batch, so filter them out up front
    # and null their drive fields rather than abort the entire run.
    import re
    SKIP_VENUE = re.compile(r"secret|\btba\b|to be announced|revealed|disclosed|undisclosed|address.*(before|holder)|location.*(before|holder)", re.I)
    all_events = []
    skipped = 0
    for wk in data["weekends"]:
        for ev in wk.get("events", []) or []:
            v = ev.get("venue") or ""
            if v and not SKIP_VENUE.search(v):
                all_events.append(ev)
            elif v:
                ev["distance_miles"] = None
                ev["drive_time_min"] = None
                skipped += 1
    print(f"{len(all_events)} events to process ({skipped} skipped: non-geocodable venue)")

    # Routes API: 1 origin + N destinations; total origins+destinations <= 50,
    # so max 49 destinations per call. Chunk accordingly.
    CHUNK = 49
    dests = [ev["venue"] + ", Los Angeles, CA" for ev in all_events]
    all_results = {}  # global_index -> result row
    for chunk_start in range(0, len(dests), CHUNK):
        chunk_dests = dests[chunk_start:chunk_start + CHUNK]
        try:
            rows = compute_matrix(key, [HOME], chunk_dests, departure)
        except Exception as e:
            try:
                body = e.read().decode()[:300]
            except Exception:
                body = str(e)
            print(f"[warn] Routes API call failed ({e}); leaving drive times unchanged. {body}")
            return
        for r in rows:
            all_results[chunk_start + r["destinationIndex"]] = r

    for i, ev in enumerate(all_events):
        r = all_results.get(i)
        if not r:
            print(f"SKIP {ev['id']} (no result)")
            continue
        if "distanceMeters" in r and "duration" in r:
            ev["distance_miles"] = round(r["distanceMeters"] / 1609.344, 1)
            # duration comes as "1234s" — strip the s
            secs = int(r["duration"].rstrip("s"))
            ev["drive_time_min"] = round(secs / 60)
            print(f"{ev['id']}: {ev['distance_miles']} mi / {ev['drive_time_min']} min")
        else:
            print(f"SKIP {ev['id']} (cond={r.get('condition')})")

    data["updated"] = datetime.datetime.now().astimezone().isoformat(timespec="minutes")
    data["distance_method"] = "driving miles + traffic-aware drive time via Google Routes API (next Sat 11am local departure)."
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("saved")

if __name__ == "__main__":
    main()
