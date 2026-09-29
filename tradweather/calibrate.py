#!/usr/bin/env python3
"""Builds /config/calibration.json and /config/wind_run_dist.json from history.csv
by grading Open-Meteo's archived model forecasts against the station's own record,
per the method in the TradWeather README:

  a) monthly wind ratio: median(daily observed avg mph / forecast mean mph) per month
  b) directional anomaly: median ratio per 8-point sector (speed-weighted forecast
     direction), normalized against the overall ratio; sectors with n<20 default to 1.0
  c) gust factor: one flat median(obs daily max gust / forecast daily max gust)
  d) temp bias: mean(forecast hi - obs hi) and mean(forecast lo - obs lo), caption only
  e) precip model verification: gfs_seamless vs ecmwf_ifs025 summed totals vs the gauge
  f) wind-run distribution: daily wind run (avg mph * 24) -> percentiles 1-99

Run once history.csv has a meaningful span (a few months minimum; a record of two
years or more is what makes the factors precise -- expect wider/noisier results on a
shorter record, and re-run this periodically as more history accumulates.
"""
import csv
import json
import statistics
import time
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

RIG = Path(os.environ.get("TRADWEATHER_DIR") or os.environ.get("ROOST_DIR") or "/config")
CONFIG = RIG / "config.json"
HISTORY_CSV = RIG / "history.csv"
CALIBRATION = RIG / "calibration.json"
WIND_RUN_DIST = RIG / "wind_run_dist.json"

# Archived-forecast queries must use the station's own zone or the daily
# aggregates land in the wrong buckets.
_CFG = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
TZ_URL = urllib.parse.quote(_CFG.get("timezone") or "America/New_York", safe="")

SECTORS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _get_json(url, timeout=30):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def load_history():
    rows = {}
    with open(HISTORY_CSV) as f:
        for row in csv.DictReader(f):
            rows[row["date"]] = {
                "temp_hi": float(row["temp_hi"]) if row["temp_hi"] else None,
                "temp_lo": float(row["temp_lo"]) if row["temp_lo"] else None,
                "rain_in": float(row["rain_in"]) if row["rain_in"] else 0.0,
                "wind_avg_mph": float(row["wind_avg_mph"]) if row["wind_avg_mph"] else None,
                "wind_gust_mph": float(row["wind_gust_mph"]) if row["wind_gust_mph"] else None,
            }
    return rows


def fetch_model_archive(lat, lon, start, end):
    """Chunk into ~1-year requests per the README; returns the merged hourly dict."""
    merged = {}
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=364), end)
        url = (f"https://historical-forecast-api.open-meteo.com/v1/forecast"
               f"?latitude={lat}&longitude={lon}"
               f"&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m"
               f"&start_date={cur.isoformat()}&end_date={chunk_end.isoformat()}"
               f"&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone={TZ_URL}")
        print(f"  fetching model archive {cur} .. {chunk_end}", flush=True)
        data = _get_json(url)
        h = data["hourly"]
        for i, t in enumerate(h["time"]):
            merged[t] = {
                "wind": h["wind_speed_10m"][i],
                "gust": h["wind_gusts_10m"][i],
                "dir": h["wind_direction_10m"][i],
                "temp": h["temperature_2m"][i],
            }
        cur = chunk_end + timedelta(days=1)
        time.sleep(1)
    return merged


def daily_from_hourly(hourly):
    """Aggregate hourly model data into per-day: mean wind, max gust, hi/lo temp, speed-weighted dir."""
    by_day = {}
    for t, v in hourly.items():
        d = t[:10]
        e = by_day.setdefault(d, {"winds": [], "gusts": [], "temps": [], "u": 0.0, "v": 0.0})
        if v["wind"] is not None:
            e["winds"].append(v["wind"])
        if v["gust"] is not None:
            e["gusts"].append(v["gust"])
        if v["temp"] is not None:
            e["temps"].append(v["temp"])
        if v["wind"] is not None and v["dir"] is not None:
            import math
            e["u"] += v["wind"] * math.sin(math.radians(v["dir"]))
            e["v"] += v["wind"] * math.cos(math.radians(v["dir"]))
    out = {}
    import math
    for d, e in by_day.items():
        if not e["winds"]:
            continue
        deg = math.degrees(math.atan2(e["u"], e["v"])) % 360 if (e["u"] or e["v"]) else None
        sector = SECTORS[int((deg / 45) + 0.5) % 8] if deg is not None else None
        out[d] = {
            "wind_mean": sum(e["winds"]) / len(e["winds"]),
            "gust_max": max(e["gusts"]) if e["gusts"] else None,
            "temp_hi": max(e["temps"]) if e["temps"] else None,
            "temp_lo": min(e["temps"]) if e["temps"] else None,
            "sector": sector,
        }
    return out


def fetch_precip_verification(lat, lon, start, end):
    url = (f"https://historical-forecast-api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}&daily=precipitation_sum"
           f"&models=gfs_seamless,ecmwf_ifs025"
           f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
           f"&precipitation_unit=inch&timezone={TZ_URL}")
    data = _get_json(url)
    daily = data["daily"]
    return {
        "gfs_total": sum(v for v in daily.get("precipitation_sum_gfs_seamless", []) if v is not None),
        "ecmwf_total": sum(v for v in daily.get("precipitation_sum_ecmwf_ifs025", []) if v is not None),
        "days": {t: {"gfs": g, "ecmwf": e} for t, g, e in zip(
            daily["time"],
            daily.get("precipitation_sum_gfs_seamless", [None] * len(daily["time"])),
            daily.get("precipitation_sum_ecmwf_ifs025", [None] * len(daily["time"])))},
    }


def main():
    cfg = json.loads(CONFIG.read_text())
    lat, lon = cfg["latitude"], cfg["longitude"]
    obs = load_history()
    if len(obs) < 14:
        print(f"only {len(obs)} days of history -- need at least ~2 weeks before calibrating. "
              "Run history_builder.py first (or wait for it to accumulate more days) and re-run this.")
        return

    dates = sorted(obs)
    start, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    print(f"station record: {start} .. {end} ({len(obs)} days)", flush=True)

    hourly = fetch_model_archive(lat, lon, start, end)
    model_daily = daily_from_hourly(hourly)

    # a) monthly wind ratio
    month_ratios = {m: [] for m in range(1, 13)}
    dir_ratios = {s: [] for s in SECTORS}
    gust_ratios = []
    hi_bias, lo_bias = [], []
    all_ratios = []

    for d, o in obs.items():
        m = model_daily.get(d)
        if not m or o["wind_avg_mph"] is None or not m["wind_mean"]:
            continue
        ratio = o["wind_avg_mph"] / m["wind_mean"]
        month = int(d[5:7])
        month_ratios[month].append(ratio)
        all_ratios.append(ratio)
        if m["sector"]:
            dir_ratios[m["sector"]].append(ratio)
        if o["wind_gust_mph"] is not None and m["gust_max"]:
            gust_ratios.append(o["wind_gust_mph"] / m["gust_max"])
        if o["temp_hi"] is not None and m["temp_hi"] is not None:
            hi_bias.append(m["temp_hi"] - o["temp_hi"])
        if o["temp_lo"] is not None and m["temp_lo"] is not None:
            lo_bias.append(m["temp_lo"] - o["temp_lo"])

    wind_monthly = {}
    overall_median = statistics.median(all_ratios) if all_ratios else 0.2
    for m in range(1, 13):
        vals = month_ratios[m]
        wind_monthly[str(m)] = round(statistics.median(vals), 3) if vals else round(overall_median, 3)

    dir_anom = {}
    for s in SECTORS:
        vals = dir_ratios[s]
        if len(vals) >= 20:
            dir_anom[s] = round(statistics.median(vals) / overall_median, 3) if overall_median else 1.0
        # sectors with n<20 simply omitted; render.py defaults missing sectors to 1.0

    gust_factor = round(statistics.median(gust_ratios), 3) if gust_ratios else 0.5

    # e) precip model verification
    precip = fetch_precip_verification(lat, lon, start, end)
    gauge_total = sum(o["rain_in"] for o in obs.values())
    gfs_pct = round(100 * precip["gfs_total"] / gauge_total, 1) if gauge_total else None
    ecmwf_pct = round(100 * precip["ecmwf_total"] / gauge_total, 1) if gauge_total else None
    precip_model = "ecmwf_ifs025" if (ecmwf_pct is None or gfs_pct is None or
                                       abs((ecmwf_pct or 0) - 100) <= abs((gfs_pct or 0) - 100)) else "gfs_seamless"

    calibration = {
        "computed": datetime.now().isoformat(timespec="seconds"),
        "record_span": f"{start}..{end} ({len(obs)} days)",
        "wind_monthly": wind_monthly,
        "dir_anom": dir_anom,
        "gust_factor": gust_factor,
        "temp_bias": {
            "hi_f": round(statistics.mean(hi_bias), 2) if hi_bias else None,
            "lo_f": round(statistics.mean(lo_bias), 2) if lo_bias else None,
        },
        "precip_verification": {"gfs_pct_of_gauge": gfs_pct, "ecmwf_pct_of_gauge": ecmwf_pct},
        "precip_model": precip_model,
    }
    CALIBRATION.write_text(json.dumps(calibration, indent=2))
    print(json.dumps(calibration, indent=2))

    # g) wind-run distribution
    runs = sorted(o["wind_avg_mph"] * 24 for o in obs.values() if o["wind_avg_mph"] is not None)
    if runs:
        pctls = {}
        for p in range(1, 100):
            idx = min(len(runs) - 1, int(round(p / 100 * (len(runs) - 1))))
            pctls[str(p)] = round(runs[idx], 1)
        WIND_RUN_DIST.write_text(json.dumps({"percentiles": pctls, "n_days": len(runs)}, indent=2))
        print(f"wind-run distribution written ({len(runs)} days)")

    print("\ncalibration.json and wind_run_dist.json written -- render.py will pick these up next run.")


if __name__ == "__main__":
    main()
