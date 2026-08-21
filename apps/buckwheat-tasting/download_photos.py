#!/usr/bin/env python3
"""Download buckwheat-tasting site photos from Unsplash + Wikimedia Commons."""
import urllib.request
import urllib.error
import os
import concurrent.futures
import time

OUT = "C:/Users/bubakazouba/sahmoud-private-infra/apps/buckwheat-tasting/static/img"

UNSPLASH_PHOTOS = [
    # (photo_id, filename, description)
    ("F6MYFCT4hIs", "hero-buckwheat-field.jpg",        "Hero: wheat field golden hour - Joshua Humpfer"),
    ("iM4QGHo0wKc", "cultivar-featured-grains.jpg",   "Featured cultivar: pomegranate seeds + cereals in ceramic"),
    ("2r8BzVYZIeo", "cultivar-grain-overhead.jpg",    "Cultivar grid: overhead seeds/spices in bowls - Joanie Simon"),
    ("pzP3k_gw4-M", "region-rolling-fields.jpg",      "Regions hero: aerial farm rolling hills Germany - autumn"),
    ("OjRKbRVlSyU", "region-tartary-highlands.jpg",   "Regions: terraced rice fields misty mountain - Khanh Do"),
    ("PRPiDF0fPf8", "region-hokkaido.jpg",             "Regions: soba noodles Japanese - Kouji Tsuru"),
    ("22vc1BkjPOQ", "region-volga-basin.jpg",          "Regions: Russian countryside field with church - Victor Antonov"),
    ("zDlusnb3G3Q", "visit-cellar-barrels.jpg",       "Visit: wine barrels cave cellar - Jim Harris"),
    ("2AfvYZz4khw", "visit-tasting-room.jpg",          "Visit: wine tasting materials on table"),
    ("vHds06aM3c8", "visit-vineyard-rows.jpg",         "Visit: sunset over vineyard rows - Anita Austvika"),
    ("rrYF1RfotSM", "concours-tasting-glasses.jpg",   "Concours: group holding footed glasses - Scott Warman"),
    ("SZ4eZDSCqN0", "cultivar-alpine-grains.jpg",     "Cultivar: village in mountain autumn - Ales Krivec"),
]

WIKIMEDIA_PHOTOS = [
    (
        "https://upload.wikimedia.org/wikipedia/commons/2/25/Fagopyrum_esculentum_Sturm64.jpg",
        "botanical-fagopyrum-sturm.jpg",
        "Botanical illustration: Fagopyrum esculentum, Sturm 1796, public domain"
    ),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Buckwheat Spectator photo pipeline; contact@bubakazouba.com)",
}

def download_unsplash(photo_id, filename, desc):
    url = f"https://unsplash.com/photos/{photo_id}/download?force=true&w=1600"
    dest = os.path.join(OUT, filename)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(dest, "wb") as f:
            f.write(data)
        size_kb = len(data) // 1024
        print(f"  OK  {filename} ({size_kb} KB) — {desc}")
        return (filename, url, desc, size_kb)
    except urllib.error.HTTPError as e:
        print(f"  ERR {filename}: HTTP {e.code} — {e.reason}")
        return None
    except Exception as e:
        print(f"  ERR {filename}: {e}")
        return None

def download_wikimedia(src_url, filename, desc):
    dest = os.path.join(OUT, filename)
    try:
        req = urllib.request.Request(src_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(dest, "wb") as f:
            f.write(data)
        size_kb = len(data) // 1024
        print(f"  OK  {filename} ({size_kb} KB) — {desc}")
        return (filename, src_url, desc, size_kb)
    except Exception as e:
        print(f"  ERR {filename}: {e}")
        return None

results = []
print("Downloading Unsplash photos...")
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    futs = [ex.submit(download_unsplash, pid, fn, desc) for pid, fn, desc in UNSPLASH_PHOTOS]
    for f in concurrent.futures.as_completed(futs):
        r = f.result()
        if r:
            results.append(r)

print("\nDownloading Wikimedia photos...")
for src_url, fn, desc in WIKIMEDIA_PHOTOS:
    r = download_wikimedia(src_url, fn, desc)
    if r:
        results.append(r)

print(f"\n{len(results)} photos downloaded successfully.")
total_kb = sum(r[3] for r in results)
print(f"Total size: {total_kb} KB ({total_kb/1024:.1f} MB)")

# Print credits summary
print("\n--- CREDITS ---")
for fn, url, desc, kb in results:
    print(f"  {fn}: {url}")
