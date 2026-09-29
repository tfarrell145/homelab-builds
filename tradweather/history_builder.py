#!/usr/bin/env python3
"""Full-history backfill for the Ambient Weather station -> /config/history.csv
One row per local calendar day: date,temp_hi,temp_lo,temp_avg,rain_in,wind_avg_mph,wind_gust_mph

Usage:
  python3 history_builder.py             # full backfill, as far back as the station has data
  python3 history_builder.py --days 90   # only the last 90 days

Paginates backwards from now until the API returns a short/empty page (start of history).
Rate-limited to 1 req/sec per Ambient's API terms. Checkpoints history.csv every 20 pages
so it's safe to interrupt and resume (though a resumed run re-walks from "now" again since
we don't track a resume cursor -- cheap given the 1 req/sec cap is the real constraint, not
compute).
"""
import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RIG = Path(os.environ.get("TRADWEATHER_DIR") or os.environ.get("ROOST_DIR") or "/config")
CONFIG = RIG / "config.json"
CSV_PATH = RIG / "history.csv"
_CFG = json.loads((RIG / "config.json").read_text()) if (RIG / "config.json").exists() else {}
TZ = ZoneInfo(_CFG.get("timezone") or "America/New_York")
AMBIENT_BASE = "https://rt.ambientweather.net/v1"
FIELDS = ["date", "temp_hi", "temp_lo", "temp_avg", "rain_in", "wind_avg_mph", "wind_gust_mph"]


def fetch_page(cfg, end_ms=None, limit=288, retries=6):
    url = (f"{AMBIENT_BASE}/devices/{cfg['device_mac']}"
           f"?applicationKey={cfg['application_key']}&apiKey={cfg['api_key']}&limit={limit}")
    if end_ms:
        url += f"&endDate={end_ms}"
    req = urllib.request.Request(url)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 2 ** (attempt + 2)  # 4, 8, 16, 32, 64s
                print(f"  429 rate limited, backing off {wait}s (attempt {attempt + 1}/{retries})", flush=True)
                time.sleep(wait)
                continue
            raise


def local_day(dateutc_ms):
    return datetime.fromtimestamp(dateutc_ms / 1000, tz=timezone.utc).astimezone(TZ).date().isoformat()


def load_csv():
    if not CSV_PATH.exists():
        return {}
    with open(CSV_PATH) as f:
        return {row["date"]: row for row in csv.DictReader(f)}


def save_csv(rows):
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for d in sorted(rows):
            w.writerow(rows[d])


def merge(existing, acc):
    out = dict(existing)
    for dkey, e in acc.items():
        if not e["temps"] and not e["wind"]:
            continue
        out[dkey] = {
            "date": dkey,
            "temp_hi": round(max(e["temps"]), 2) if e["temps"] else "",
            "temp_lo": round(min(e["temps"]), 2) if e["temps"] else "",
            "temp_avg": round(sum(e["temps"]) / len(e["temps"]), 2) if e["temps"] else "",
            "rain_in": round(e["rain"], 2) if e["rain"] is not None else "",
            "wind_avg_mph": round(sum(e["wind"]) / len(e["wind"]), 2) if e["wind"] else "",
            "wind_gust_mph": round(max(e["gust"]), 2) if e["gust"] else "",
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="limit backfill to the last N days")
    ap.add_argument("--max-pages", type=int, default=5000, help="safety cap on API calls")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text())
    existing = load_csv()
    acc = {}

    cutoff_ms = None
    if args.days:
        cutoff_ms = int((datetime.now(TZ) - timedelta(days=args.days)).timestamp() * 1000)

    cursor = None
    page_count = 0
    total_records = 0

    while page_count < args.max_pages:
        page = fetch_page(cfg, end_ms=cursor, limit=288)
        page_count += 1
        if not page:
            print("no more data - reached start of station history", flush=True)
            break
        for r in page:
            ts = r.get("dateutc")
            if ts is None:
                continue
            if cutoff_ms and ts < cutoff_ms:
                continue
            dkey = local_day(ts)
            e = acc.setdefault(dkey, {"temps": [], "rain": None, "wind": [], "gust": []})
            if r.get("tempf") is not None:
                e["temps"].append(r["tempf"])
            if r.get("windspeedmph") is not None:
                e["wind"].append(r["windspeedmph"])
            if r.get("windgustmph") is not None:
                e["gust"].append(r["windgustmph"])
            if r.get("dailyrainin") is not None:
                e["rain"] = max(e["rain"], r["dailyrainin"]) if e["rain"] is not None else r["dailyrainin"]
        total_records += len(page)
        oldest = min(r["dateutc"] for r in page)
        stop = (cutoff_ms and oldest < cutoff_ms) or len(page) < 288
        if page_count % 20 == 0 or stop:
            print(f"  {page_count} pages, {total_records} records, back to {local_day(oldest)}", flush=True)
            save_csv(merge(existing, acc))
        if stop:
            break
        cursor = oldest - 1
        time.sleep(2.5)  # Ambient rate limit is 1 req/sec; leave headroom since the
                         # render container is also polling this key every 60s

    merged = merge(existing, acc)
    save_csv(merged)
    print(f"done - {len(merged)} days in {CSV_PATH.name}, {total_records} records over {page_count} pages", flush=True)


if __name__ == "__main__":
    main()
