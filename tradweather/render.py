#!/usr/bin/env python3
"""tradweather — renders public/index.html from an Ambient Weather station every
minute, with the public forecast models calibrated against the station's own
history. Self-contained (stdlib only).

Config, caches and calibration data live beside the script in TRADWEATHER_DIR (default
/config, which is where the container mounts the project). Only TRADWEATHER_DIR/public
is ever served: the config file holds API keys and sits outside it deliberately.
"""
import csv
import json
import math
import os
import shutil
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import basicview
import icons
import wxicons

# Query string on every icon reference, moved by icons.DESIGN. The filenames have to
# stay put (they are what an installed PWA already points at), so without this a
# redrawn icon sits on disk behind a cached copy indefinitely.
ICON_V = f"?v={icons.DESIGN}"

# Everything lives beside the script. /config is where the container mounts it;
# TRADWEATHER_DIR (formerly ROOST_DIR) lets the same code run from a home directory under systemd or launchd
# with no edits.
RIG = Path(os.environ.get("TRADWEATHER_DIR") or os.environ.get("ROOST_DIR") or "/config")
CONFIG = RIG / "config.json"
OUT = RIG / "public" / "index.html"
ARCHIVE_CACHE = RIG / ".archive24_cache.json"
HISTORY30 = RIG / "history30.json"
FORECAST_CACHE = RIG / ".forecast_cache.json"
GRID_CACHE = RIG / ".nws_grid_cache.json"
WEATHER_JSON = RIG / "public" / "weather.json"
CALIBRATION = RIG / "calibration.json"
MONTHLY = RIG / "monthly_totals.json"
YTDREF = RIG / "ytd_reference.json"
WIND_RUN_DIST = RIG / "wind_run_dist.json"

# Third-party CSS/JS/fonts, served from public/vendor/ rather than CDNs (see
# vendor/README.md). Bump VENDOR_V when anything in vendor/ changes: it is both the
# cache-buster on every URL and the stamp that tells sync_vendor() to recopy.
VENDOR_V = "1"
VENDOR_SRC = RIG / "vendor"
CDN_ASSETS = {
    "fonts": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&amp;family=JetBrains+Mono:wght@400;500&amp;family=Montserrat:wght@300;400;600;700&amp;family=Lato:wght@300;400;700&amp;display=swap",
    "mdi": "https://cdn.jsdelivr.net/npm/@mdi/font@7.4.47/css/materialdesignicons.min.css",
    "leaflet_css": "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css",
    "leaflet_js": "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js",
    "chart_js": "https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js",
}
LOCAL_ASSETS = {
    "fonts": "vendor/fonts/fonts.css",
    "mdi": "vendor/mdi/css/materialdesignicons.min.css",
    "leaflet_css": "vendor/leaflet/leaflet.css",
    "leaflet_js": "vendor/leaflet/leaflet.js",
    "chart_js": "vendor/chartjs/chart.umd.js",
}


def sync_vendor(public_dir):
    """Copy vendor/ into public/vendor/ when it is missing or stale, and return the
    asset URLs to use. Falls back to the CDN URLs if vendor/ is absent (a partial
    deploy that copied only the .py files), so a missing folder degrades to the old
    behaviour instead of a page with no charts, map or fonts."""
    dst = public_dir / "vendor"
    stamp = dst / ".vendor_v"
    try:
        if not VENDOR_SRC.is_dir():
            raise FileNotFoundError(VENDOR_SRC)
        if not stamp.exists() or stamp.read_text().strip() != VENDOR_V:
            shutil.copytree(VENDOR_SRC, dst, dirs_exist_ok=True)
            stamp.write_text(VENDOR_V)
        return {k: f"{v}?v={VENDOR_V}" for k, v in LOCAL_ASSETS.items()}
    except Exception as e:
        print(f"vendor assets unavailable, using CDNs: {e}")
        return dict(CDN_ASSETS)
HISTORY_CSV = RIG / "history.csv"

def load_cfg():
    return json.loads(CONFIG.read_text())


_CFG = load_cfg() if CONFIG.exists() else {}

# Every timestamp on the page is local to the station, not to whoever is looking
# at it, so the zone is a property of the install. Set "timezone" in config.json
# to any IANA name.
TZ = ZoneInfo(_CFG.get("timezone") or "America/New_York")
TZ_URL = urllib.parse.quote(str(TZ), safe="")

# NWS blocks requests without a User-Agent that carries a contact, and asks that
# it be a real one. It is a config value so the repo carries no address.
NWS_UA = {"User-Agent": "tradweather ({})".format(
    _CFG.get("contact_email") or "set contact_email in config.json")}
ARCHIVE_MAX_AGE = 600      # 10 min
FC_CACHE_MAX_AGE = 1800    # 30 min
GRID_CACHE_MAX_AGE = 30 * 86400  # NWS gridpoint almost never changes
AMBIENT_BASE = "https://rt.ambientweather.net/v1"

# Column order of history.csv -- must match history_builder.py and calibrate.py.
HISTORY_FIELDS = ["date", "temp_hi", "temp_lo", "temp_avg",
                  "rain_in", "wind_avg_mph", "wind_gust_mph"]

SAIL = ["#F5C63C", "#F3A83B", "#EE8434", "#E1552A", "#C93A2E"]
SAIL_BLUE = "#3E63A8"

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


# ---------------------------------------------------------------- data layer



def _get_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_current(cfg):
    url = f"{AMBIENT_BASE}/devices?applicationKey={cfg['application_key']}&apiKey={cfg['api_key']}"
    devices = _get_json(url)
    dev = next(d for d in devices if d["macAddress"] == cfg["device_mac"])
    return dev["lastData"]


def fetch_history_page(cfg, end_ms=None, limit=288, retries=4):
    url = (f"{AMBIENT_BASE}/devices/{cfg['device_mac']}"
           f"?applicationKey={cfg['application_key']}&apiKey={cfg['api_key']}&limit={limit}")
    if end_ms:
        url += f"&endDate={end_ms}"
    for attempt in range(retries):
        try:
            return _get_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** (attempt + 2))  # 4, 8, 16s
                continue
            raise


def fetch_archive_24h(cfg):
    """5-min records covering the last 24h, cached 10 min."""
    if ARCHIVE_CACHE.exists() and time.time() - ARCHIVE_CACHE.stat().st_mtime < ARCHIVE_MAX_AGE:
        cached = json.loads(ARCHIVE_CACHE.read_text())
        if cached.get("v") == 1:
            return cached["recs"]
    recs = fetch_history_page(cfg, limit=288)
    cutoff = time.time() * 1000 - 86_400_000
    oldest = min((r["dateutc"] for r in recs), default=None)
    tries = 0
    while recs and oldest and oldest > cutoff and tries < 4:
        time.sleep(1)  # Ambient rate limit: 1 req/sec
        more = fetch_history_page(cfg, end_ms=oldest - 1, limit=288)
        if not more:
            break
        recs.extend(more)
        oldest = min(r["dateutc"] for r in more)
        tries += 1
    recs = sorted((r for r in recs if r["dateutc"] >= cutoff), key=lambda r: r["dateutc"])
    ARCHIVE_CACHE.write_text(json.dumps({"v": 1, "recs": recs}))
    return recs


def _history_csv_days():
    """Dates already present in the permanent station record."""
    if not HISTORY_CSV.exists():
        return set()
    with HISTORY_CSV.open() as f:
        return {row["date"] for row in csv.DictReader(f)}


def _upsert_history_csv(rows):
    """Merge daily rows into history.csv, newly-computed values winning.

    This is the file calibrate.py reads, so it is append-only and never pruned --
    the record grows for as long as the container runs. Written via a temp file and
    an atomic replace, since calibrate.py may be reading it by hand at any moment.
    """
    existing = {}
    if HISTORY_CSV.exists():
        with HISTORY_CSV.open() as f:
            existing = {row["date"]: row for row in csv.DictReader(f)}
    existing.update(rows)
    # Never record the current day: it is still in progress, and because only
    # completed days are ever re-fetched, a partial row would be frozen for good.
    existing.pop(date.today().isoformat(), None)
    tmp = HISTORY_CSV.with_name(HISTORY_CSV.name + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        w.writeheader()
        for d in sorted(existing):
            w.writerow(existing[d])
    tmp.replace(HISTORY_CSV)


def refresh_history30(cfg):
    """Top up the 30-day chart cache *and* the permanent station record.

    One fetch per missing day already pulls every 5-minute record for that day, so
    both files are filled from the same call at no extra API cost. history30.json is
    pruned to the chart's 30-day window; history.csv keeps everything forever.
    """
    hist = json.loads(HISTORY30.read_text()) if HISTORY30.exists() else {}
    yesterday = date.today() - timedelta(days=1)
    wanted = [(yesterday - timedelta(days=i)).isoformat() for i in range(30)]
    on_record = _history_csv_days()
    missing = [d for d in wanted if d not in hist or d not in on_record]
    fresh = {}
    for dstr in missing[:5]:  # a handful of days per render run to catch up without hammering the API
        y, m, dd = map(int, dstr.split("-"))
        day = date(y, m, dd)
        start = datetime(day.year, day.month, day.day, tzinfo=TZ)
        end = start + timedelta(days=1)
        try:
            page = fetch_history_page(cfg, end_ms=int(end.timestamp() * 1000), limit=288)
        except Exception:
            break
        recs = [r for r in page if start.timestamp() * 1000 <= r["dateutc"] < end.timestamp() * 1000]
        if recs:
            temps = [r["tempf"] for r in recs if r.get("tempf") is not None]
            winds = [r["windspeedmph"] for r in recs if r.get("windspeedmph") is not None]
            gusts = [r["windgustmph"] for r in recs if r.get("windgustmph") is not None]
            # dailyrainin resets at local midnight and Ambient returns newest-first, so
            # the day's total is the running maximum. Taking recs[-1] reads the OLDEST
            # record -- 00:05, just after the reset -- and reports 0 for every day.
            rain = max((r["dailyrainin"] for r in recs
                        if r.get("dailyrainin") is not None), default=0)
            hist[dstr] = {"hi": max(temps) if temps else None,
                          "lo": min(temps) if temps else None,
                          "rain": rain}
            fresh[dstr] = {
                "date": dstr,
                "temp_hi": round(max(temps), 2) if temps else "",
                "temp_lo": round(min(temps), 2) if temps else "",
                "temp_avg": round(sum(temps) / len(temps), 2) if temps else "",
                "rain_in": round(rain, 2),
                "wind_avg_mph": round(sum(winds) / len(winds), 2) if winds else "",
                "wind_gust_mph": round(max(gusts), 2) if gusts else "",
            }
        time.sleep(1)
    # Rewrite when there are new rows, or to evict a current-day row left behind by
    # a manual history_builder run (which does not know about the completed-day rule).
    if fresh or date.today().isoformat() in on_record:
        _upsert_history_csv(fresh)
    hist = {k: v for k, v in hist.items() if k in wanted}
    HISTORY30.write_text(json.dumps(hist))
    return [(d, hist[d]) for d in sorted(hist)]


def nws_grid(lat, lon):
    """Cached NWS gridpoint lookup -> (gridId, gridX, gridY, cwa)."""
    if GRID_CACHE.exists() and time.time() - GRID_CACHE.stat().st_mtime < GRID_CACHE_MAX_AGE:
        return json.loads(GRID_CACHE.read_text())
    lat4, lon4 = round(lat, 4), round(lon, 4)  # NWS rejects >4 decimals
    pt = _get_json(f"https://api.weather.gov/points/{lat4},{lon4}", NWS_UA)["properties"]
    info = {"gridId": pt["gridId"], "gridX": pt["gridX"], "gridY": pt["gridY"], "cwa": pt["cwa"]}
    GRID_CACHE.write_text(json.dumps(info))
    return info




def fetch_forecast(cfg):
    """Multi-model 7-day (Open-Meteo) + NWS 7-day, alerts, and the local AFD. Cached 30 min."""
    if FORECAST_CACHE.exists() and time.time() - FORECAST_CACHE.stat().st_mtime < FC_CACHE_MAX_AGE:
        cached = json.loads(FORECAST_CACHE.read_text())
        if cached.get("v") == 3:
            return cached
    lat, lon = cfg["latitude"], cfg["longitude"]
    fc = {"v": 3}   # bump when the shape changes; discards stale caches
    try:
        om = _get_json(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,dew_point_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation"
            "&models=gfs_seamless,ecmwf_ifs025,gfs_hrrr"
            "&forecast_days=7&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&precipitation_unit=inch&timezone={TZ_URL}")
        fc["om"] = om["hourly"]
    except Exception:
        pass
    try:
        grid = nws_grid(lat, lon)
        periods = _get_json(
            f"https://api.weather.gov/gridpoints/{grid['gridId']}/{grid['gridX']},{grid['gridY']}/forecast",
            NWS_UA)["properties"]["periods"][:14]
        fc["periods"] = [{"name": p["name"], "temp": p["temperature"], "short": p["shortForecast"],
                          "pop": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                          "detailed": p.get("detailedForecast", ""),
                          "day": p["isDaytime"], "date": p["startTime"][:10]} for p in periods]
        fc["cwa"] = grid["cwa"]
    except Exception:
        pass
    try:
        grid = nws_grid(lat, lon)
        # Hourly, not the day/night periods: the Basic view folds these into named
        # parts of the day, which needs finer granularity than "Today"/"Tonight".
        fc["hourly"] = _get_json(
            f"https://api.weather.gov/gridpoints/{grid['gridId']}/{grid['gridX']},"
            f"{grid['gridY']}/forecast/hourly", NWS_UA)["properties"]["periods"][:120]
    except Exception:
        pass
    try:
        alerts = _get_json(f"https://api.weather.gov/alerts/active?point={lat},{lon}", NWS_UA)["features"]
        fc["alerts"] = [{"event": a["properties"]["event"], "headline": a["properties"].get("headline", "")}
                        for a in alerts]
    except Exception:
        pass
    try:
        cwa = fc.get("cwa", "BTV")
        latest = _get_json(f"https://api.weather.gov/products/types/AFD/locations/{cwa}", NWS_UA)["@graph"][0]
        prod = _get_json(latest["@id"], NWS_UA)
        fc["afd"] = {"time": latest["issuanceTime"], "text": prod["productText"]}
    except Exception:
        pass
    if len(fc) > 1:
        FORECAST_CACHE.write_text(json.dumps(fc))
    return fc


def load_calibration():
    default = {"wind_monthly": {}, "gust_factor": None, "dir_anom": {}, "precip_model": "ecmwf_ifs025",
              "temp_bias": None, "computed": None}
    if CALIBRATION.exists():
        return {**default, **json.loads(CALIBRATION.read_text())}
    return default


# Kept out of the page f-string so the JS braces need no escaping.
REFRESH_JS = """<script>
/* Refresh without the page jumping.

   This replaced the old 60-second meta-refresh, which on a phone threw away the
   scroll position, restarted the radar animation mid-loop, and re-fetched the whole
   document every minute even with the screen off. Instead: reload only while the
   tab is actually visible, and carry the scroll position across. */
(function () {
  var KEY = "roost:scroll";
  try {
    var y = sessionStorage.getItem(KEY);
    if (y !== null) { window.scrollTo(0, parseFloat(y)); sessionStorage.removeItem(KEY); }
  } catch (e) {}

  function reload() {
    try { sessionStorage.setItem(KEY, String(window.scrollY)); } catch (e) {}
    location.reload();
  }

  var due = false;
  setInterval(function () {
    if (document.hidden) { due = true; return; }   // catch up on return instead
    reload();
  }, 60000);

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && due) { due = false; reload(); }
  });
})();
</script>
"""


# Kept out of the page f-string so the JS braces need no escaping.
BOOT_JS = """<script>
/* Runs before the stylesheet, and before every other script, to establish two
   facts the first painted frame depends on.

   1. The theme. THEME_JS lives at the end of the body, so until 2026-09-12 the
      page painted in light and then snapped to the saved theme -- a flash of the
      wrong palette on every single load, most visible on dark and retro.

   2. Whether this is a cold start. sessionStorage survives location.reload(),
      which is how REFRESH_JS refreshes every 60 seconds, but iOS clears it when
      it terminates a standalone web app. Empty therefore means launched, not
      refreshed -- exactly the distinction the splash needs so it appears once on
      open and never again while the app stays resident. */
(function () {
  var root = document.documentElement;
  var HEAD = { light: "#FFFFFF", dark: "#05070A", retro: "#241B44", paper: "#FFFFFF", minimal: "#FFFFFF" };
  var t = null;
  try {
    t = localStorage.getItem("roost:theme");
    if (t === "tjf") t = "paper";  // renamed 2026-09; keep an old saved choice
    if (t === "light" || t === "dark" || t === "retro" || t === "paper" || t === "minimal") {
      root.setAttribute("data-theme", t);
      var m = document.querySelector('meta[name="theme-color"]');
      if (m) m.setAttribute("content", HEAD[t]);
    }
  } catch (e) {}
  try {
    if (!sessionStorage.getItem("roost:booted")) {
      root.classList.add("cold");
      sessionStorage.setItem("roost:booted", "1");
    }
  } catch (e) {}
})();
</script>"""


SPLASH_JS = """<script>
/* Retire the cold-start splash. Returns immediately unless BOOT_JS set `cold`,
   so a 60-second refresh never sees it.

   Runs last in the body, so the server-rendered conditions are already parsed by
   the time it executes. Charts and radar tiles are deliberately not waited on --
   they fill in behind a page that is already readable. */
(function () {
  var root = document.documentElement;
  var el = document.getElementById("splash");
  if (!el || !root.classList.contains("cold")) return;

  var MIN = 420;    /* below this it reads as a flicker rather than a splash */
  var MAX = 3000;   /* failsafe: never trap the reader behind it */
  var start = Date.now();
  var done = false;

  function hide() {
    if (done) return;
    done = true;
    el.classList.add("gone");
    setTimeout(function () {
      root.classList.remove("cold");
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 260);
  }

  setTimeout(hide, MAX);

  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      setTimeout(hide, Math.max(0, MIN - (Date.now() - start)));
    });
  });
})();
</script>"""


MODE_JS = """<script>
/* Current | Radar | Detailed | Discussion, and Detailed's own four sub-panes.

   Every view is baked into the page, so switching costs no network round trip.
   The stored mode key is still "basic" for the first tab -- renaming the label
   must not sign everyone out of the tab they had chosen.

   There is exactly one radar map. It now lives only in the Radar tab: Detailed
   used to carry a second slot and the block was re-parented between them, which
   is machinery that stops earning its keep once Radar is one tap away.

   Charts build lazily per pane, because a chart constructed inside a hidden
   container measures itself as zero. CHARTS maps a pane to its initialiser;
   started[] records which have fired so a theme change can rebuild exactly
   those and no others. */
(function () {
  var KEY = "roost:mode";
  var SUBKEY = "roost:detail";
  var MODES = ["basic", "radar", "detail", "afd"];
  var views = { basic: "view-basic", radar: "view-radar",
               detail: "view-detail", afd: "view-afd" };
  var SUBS = ["now", "24h", "fc", "alm"];
  // Each initialiser is isolated. They used to share one try/catch per pane,
  // which meant a throw in the first silently took the rest of the pane with
  // it -- exactly how a missing __chartDefaults() call in initForecastChart
  // killed all three Forecast charts rather than one.
  function guard() {
    var fns = arguments;
    return function () {
      for (var i = 0; i < fns.length; i++) {
        try { fns[i](); }
        catch (e) { if (window.console) console.error("chart init failed:", e); }
      }
    };
  }
  var CHARTS = {
    "24h": guard(initCharts24),
    "fc":  guard(initForecastChart, initChartsFc),
    "alm": guard(initChartsAlm)
  };
  var started = {};
  var radarStarted = false;

  if (!document.getElementById(views.basic)) return;

  function ensure(pane) {
    if (started[pane] || !CHARTS[pane]) return;
    started[pane] = true;
    CHARTS[pane]();
  }

  window.__initStarted = function () {
    Object.keys(started).forEach(function (p) {
      if (started[p]) { CHARTS[p](); }
    });
  };

  function placeRadar(mode) {
    if (mode !== "radar") return;
    if (!radarStarted) { radarStarted = true; try { initRadar(); } catch (e) {} }
    var block = document.getElementById("radarblock");
    var slot = document.getElementById("radar-slot-radar");
    if (!block || !slot || block.parentNode === slot) return;
    slot.appendChild(block);
    if (window.__radar && window.__radar.map) {
      // Leaflet caches container size; after a move it must re-measure or the tiles
      // render against the old dimensions.
      setTimeout(function () { try { window.__radar.map.invalidateSize(); } catch (e) {} }, 30);
    }
  }

  var sub = "now";

  function applySub(pane, save) {
    if (SUBS.indexOf(pane) < 0) pane = "now";
    sub = pane;
    SUBS.forEach(function (p) {
      var el = document.getElementById("pane-" + p);
      if (el) el.hidden = (p !== pane);
      var b = document.getElementById("sub-" + p);
      if (b) b.setAttribute("aria-selected", String(p === pane));
    });
    ensure(pane);
    if (save) { try { localStorage.setItem(SUBKEY, pane); } catch (e) {} }
  }

  function apply(mode, save) {
    if (MODES.indexOf(mode) < 0) mode = "basic";
    MODES.forEach(function (m) {
      var v = document.getElementById(views[m]);
      if (v) v.hidden = (m !== mode);
      var b = document.getElementById("mode-" + m);
      if (b) b.setAttribute("aria-selected", String(m === mode));
    });
    placeRadar(mode);
    // A pane only measures correctly once its view is on screen, so Detailed
    // builds its current pane's charts when Detailed itself is shown.
    if (mode === "detail") ensure(sub);
    if (save) { try { localStorage.setItem(KEY, mode); } catch (e) {} }
  }

  var savedSub = "now";
  try { savedSub = localStorage.getItem(SUBKEY) || "now"; } catch (e) {}
  // Lays out the panes without building anything: Detailed is still hidden here,
  // and ensure() inside apply() does the building once it is not.
  if (SUBS.indexOf(savedSub) < 0) savedSub = "now";
  sub = savedSub;
  SUBS.forEach(function (p) {
    var el = document.getElementById("pane-" + p);
    if (el) el.hidden = (p !== sub);
    var b = document.getElementById("sub-" + p);
    if (b) b.setAttribute("aria-selected", String(p === sub));
  });

  var saved = "basic";
  try { saved = localStorage.getItem(KEY) || "basic"; } catch (e) {}
  apply(saved, false);

  MODES.forEach(function (m) {
    var b = document.getElementById("mode-" + m);
    if (b) b.addEventListener("click", function () { apply(m, true); });
  });
  SUBS.forEach(function (p) {
    var b = document.getElementById("sub-" + p);
    if (b) b.addEventListener("click", function () { applySub(p, true); });
  });
})();
</script>
"""


# Kept out of the page f-string so the JS braces need no escaping.
THEME_JS = """<script>
/* Theme: light | dark | retro.

   Every colour is a CSS custom property, so switching is one attribute write --
   except for the two things that cache colour at construction time: Chart.js
   instances (destroyed and rebuilt) and the Leaflet basemap (tile URL swapped).
   Retro reuses the dark tiles and tints them blue in CSS. */
(function () {
  var KEY = "roost:theme";
  var THEMES = ["light", "dark", "retro", "paper", "minimal"];
  var root = document.documentElement;
  var HEAD = { light: "#FFFFFF", dark: "#05070A", retro: "#241B44", paper: "#FFFFFF", minimal: "#FFFFFF" };

  // The Material Design Icons webfont is ~400KB for the full set, which is not
  // worth loading for four themes that never draw a single glyph from it. It is
  // injected the first time `minimal` is selected and cached from then on; the
  // drawn SVGs stay visible until it lands, so there is no icon-shaped hole.
  function ensureMdi() {
    if (document.getElementById("mdi-css")) return;
    var l = document.createElement("link");
    l.id = "mdi-css";
    l.rel = "stylesheet";
    l.href = "__MDI_CSS__";
    document.head.appendChild(l);
  }

  function apply(theme, save) {
    if (THEMES.indexOf(theme) < 0) theme = "light";
    if (theme === "minimal") ensureMdi();
    root.setAttribute("data-theme", theme);

    var sel = document.getElementById("themesel");
    if (sel && sel.value !== theme) sel.value = theme;

    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", HEAD[theme] || HEAD.light);

    if (window.__radar && window.__radar.base) {
      try {
        window.__radar.base.setUrl(window.__radar.baseUrl());
        var r = window.__radar;
        if (r.marker) r.marker.setStyle({ color: r.tok("--panel"), fillColor: r.tok("--accent") });
      } catch (e) {}
    }
    if (window.__charts && window.__charts.length) {
      try {
        window.__charts.forEach(function (c) { c.destroy(); });
        window.__charts.length = 0;
        // Rebuild only the views whose charts were built in the first place --
        // rebuilding a hidden view's charts would size them all to zero.
        if (window.__initStarted) { window.__initStarted(); } else { initCharts(); }
      } catch (e) {}
    }
    if (save) { try { localStorage.setItem(KEY, theme); } catch (e) {} }
  }

  var saved = "light";
  try { saved = localStorage.getItem(KEY) || "light"; } catch (e) {}
  if (saved === "tjf") saved = "paper";  // renamed 2026-09; keep an old saved choice
  apply(saved, false);

  var sel = document.getElementById("themesel");
  if (sel) sel.addEventListener("change", function () { apply(sel.value, true); });
  window.__applyTheme = apply;
})();
</script>
"""


# --------------------------------------------------------------- rendering

WEATHER_JSON_SCHEMA = 1


def chart_fig(canvas_id, height, cap, under="", scroll=False):
    """One chart as a single bordered figure: plot, anything under it, caption.

    The caption used to sit outside the box, so every chart read as two loose
    objects with a gap between them. Inside the frame it belongs to its plot, and
    the wind chart's direction strip lands between the two rather than floating.
    """
    if scroll:
        # The axes cannot live in the canvas: the canvas is what scrolls, so they
        # would slide off and the chart would be unreadable two days in. The
        # canvas draws its gridlines but no tick labels, and the labels are DOM
        # in two opaque gutters pinned outside the scroller.
        plot = (f'<div class="plotwrap">'
                f'<div class="chartplot chartscroll" style="height:{height}px;">'
                f'<div class="chartwide"><canvas id="{canvas_id}"></canvas></div></div>'
                f'<div class="axgut axgut-l" id="{canvas_id}-axl" aria-hidden="true"></div>'
                f'<div class="axgut axgut-r" id="{canvas_id}-axr" aria-hidden="true"></div>'
                f'</div>')
    else:
        plot = (f'<div class="chartplot" style="height:{height}px;">'
                f'<canvas id="{canvas_id}"></canvas></div>')
    return (f'<div class="chartfig">{plot}{under}'
            f'<div class="cap">{cap}</div>'
            f'</div>')


def wind_dir_strip(wr, arrows=12):
    """An aligned row of arrows under the wind chart: where the wind came from.

    Direction is circular and speed is not, so the two do not belong on one plot.
    A fixed number of arrows across the same 24 hours reads at a glance and, being
    a heading rather than a number on an axis, has no wrap discontinuity at north.

    Each arrow points the way the wind was blowing (origin + 180) and is tinted by
    the speed at that moment, so a calm sector and a windy one are distinguishable
    without reading the chart above.
    """
    usable = [r for r in wr if r.get("winddir") is not None]
    if len(usable) < arrows:
        return ""
    step = len(usable) / float(arrows)
    cells = []
    for i in range(arrows):
        r = usable[min(len(usable) - 1, int(i * step + step / 2))]
        spd = r.get("windspeedmph") or 0
        dt = datetime.fromtimestamp(r["dateutc"] / 1000, tz=timezone.utc).astimezone(TZ)
        col = SAIL[min(len(SAIL) - 1, int(spd // 4))] if spd >= 0.5 else "var(--faint)"
        if spd < 0.5:
            # Calm has no direction to report. A dot says so; an arrow would invent one.
            glyph = ('<svg viewBox="0 0 24 24" width="20" height="20">'
                     f'<circle cx="12" cy="12" r="2.6" fill="{col}"></circle></svg>')
        else:
            rot = (r["winddir"] + 180) % 360
            glyph = (f'<svg viewBox="0 0 24 24" width="20" height="20" '
                     f'style="transform:rotate({rot:.0f}deg);">'
                     f'<path d="M12 3 L12 21 M12 21 L7.5 15.5 M12 21 L16.5 15.5" '
                     f'fill="none" stroke="{col}" stroke-width="2.4" '
                     f'stroke-linecap="round" stroke-linejoin="round"></path></svg>')
        cells.append(f'<div class="dcell" title="{COMPASS[int((r["winddir"] % 360) / 22.5 + 0.5) % 16]}'
                     f' at {spd:.1f} mph">{glyph}'
                     f'<div class="dhr">{dt.strftime("%-I%p").lower()[:-1]}</div></div>')
    return f'<div class="dirstrip">{"".join(cells)}</div>'


def daily_from_periods(periods):
    """Fold NWS day/night periods into one row per calendar date.

    A period carries a single temperature, which is the high for a daytime
    period and the low for a nighttime one. Folding them is what turns 14
    periods into the 7 "Tomorrow 75/51" rows a dashboard actually wants.
    """
    days = {}
    for p in periods or []:
        day = days.setdefault(p["date"], {"date": p["date"], "high_f": None,
                                          "low_f": None, "short": None, "pop": None,
                                          "condition": None})
        if p.get("day"):
            day["high_f"] = p.get("temp")
            day["short"] = p.get("short")          # daytime wording wins
            day["condition"] = wxicons.ha_condition(p.get("short"), True)
        else:
            day["low_f"] = p.get("temp")
            if day["short"] is None:
                day["short"] = p.get("short")
                day["condition"] = wxicons.ha_condition(p.get("short"), False)
        pop = p.get("pop")
        if pop is not None:
            day["pop"] = pop if day["pop"] is None else max(day["pop"], pop)
    return [days[k] for k in sorted(days)]


PRECIP_CONDITIONS = ("rainy", "pouring", "snowy", "snowy-rainy", "lightning-rainy", "hail")


def current_hourly_period(fc, now):
    """The NWS hourly period covering `now`, or None."""
    for p in fc.get("hourly") or []:
        try:
            start = datetime.fromisoformat(p["startTime"])
            end = datetime.fromisoformat(p["endTime"])
        except (KeyError, ValueError):
            continue
        if start <= now < end:
            return p
    return None


def station_condition(d, fc, now):
    """Home Assistant condition token for right now, or None if unknown.

    Sky cover is a model read: the station has no sky sensor, so the base is
    the current NWS hourly period, keyword-matched through the same table the
    wall display's icons use. What the station knows first-hand is whether it
    is raining and whether it is fogged in, and those override the model.

    None rather than a guess when the hourly forecast is missing: a consumer
    can fall back to its own weather provider, which is better than pinning a
    wrong sky to the roof.
    """
    p = current_hourly_period(fc, now)
    base = wxicons.ha_condition(p.get("shortForecast"), p.get("isDaytime", True)) if p else None

    # hourlyrainin is the station's rain rate: rain in the last 60 minutes.
    rate = d.get("hourlyrainin") or 0
    if rate > 0:
        # Frozen precipitation still reads as rain to a tipping bucket, so the
        # forecast wording decides what kind it is.
        if base in ("snowy", "snowy-rainy"):
            return base
        return "pouring" if rate >= 0.3 else "rainy"

    # Saturated air is also what steady rain looks like to a hygrometer, so the
    # fog call only stands when the forecast is not already calling for
    # precipitation. Otherwise a wet hour between bucket tips reads as fog.
    temp, dew, hum = d.get("tempf"), d.get("dewPoint"), d.get("humidity")
    if (base not in PRECIP_CONDITIONS and hum is not None and hum >= 98
            and temp is not None and dew is not None and temp - dew <= 1.0):
        return "fog"

    return base


def build_weather_payload(d, fc, now, forecast_fetched=None):
    """The machine-readable contract: station observations plus forecast.

    Pure, so it can be tested without the station API. Consumers (the Family
    Dashboard, Home Assistant) read this instead of scraping the HTML or the
    private forecast cache. Anything that later replaces TradWeather only has
    to emit this same shape.

    Both timestamps are absolute. Staleness is the consumer's decision, not
    ours: current conditions and the forecast go stale at very different rates.
    """
    obs_dt = (datetime.fromtimestamp(d["dateutc"] / 1000, tz=timezone.utc).astimezone(TZ)
              if d.get("dateutc") else None)
    wdir_deg = d.get("winddir")
    payload = {
        "schema_version": WEATHER_JSON_SCHEMA,
        "generated": now.isoformat(timespec="seconds"),
        "station": {
            "observed": obs_dt.isoformat(timespec="seconds") if obs_dt else None,
            "age_seconds": int((now - obs_dt).total_seconds()) if obs_dt else None,
            "temp_f": d.get("tempf"),
            "feels_like_f": d.get("feelsLike") or d.get("tempf"),
            "dew_point_f": d.get("dewPoint"),
            "humidity": d.get("humidity"),
            "wind_mph": d.get("windspeedmph"),
            "gust_mph": d.get("windgustmph"),
            "wind_dir_deg": wdir_deg,
            "wind_dir": COMPASS[int((wdir_deg / 22.5) + 0.5) % 16] if wdir_deg is not None else None,
            "pressure_in": d.get("baromrelin"),
            "rain_today_in": d.get("dailyrainin"),
            "uv": d.get("uv"),
            "solar_wm2": d.get("solarradiation"),
            # Home Assistant condition token. Station-corrected, see station_condition().
            "condition": station_condition(d, fc, now),
        },
        "forecast": {
            "source": "NWS " + fc.get("cwa", "?") + " + Open-Meteo",
            "fetched": forecast_fetched.isoformat(timespec="seconds") if forecast_fetched else None,
            "age_seconds": int((now - forecast_fetched).total_seconds()) if forecast_fetched else None,
            "days": daily_from_periods(fc.get("periods")),
            # Same token on every forecast period, so a template weather entity
            # can be built from this file without re-parsing NWS prose.
            "periods": [dict(p, condition=wxicons.ha_condition(p.get("short"), p.get("day", True)))
                        for p in fc.get("periods", [])],
        },
        "alerts": fc.get("alerts", []),
    }
    return payload


def write_weather_json(d, fc, now=None):
    """Write public/weather.json. Never fatal: the wall display outranks the API."""
    try:
        fetched = None
        if FORECAST_CACHE.exists():
            fetched = datetime.fromtimestamp(FORECAST_CACHE.stat().st_mtime, tz=TZ)
        payload = build_weather_payload(d, fc, now or datetime.now(TZ), fetched)
        WEATHER_JSON.parent.mkdir(parents=True, exist_ok=True)
        tmp = WEATHER_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1))
        tmp.replace(WEATHER_JSON)   # atomic, so a reader never sees half a file
    except Exception as e:
        print(f"weather.json failed: {e}")


def beaufort(mph):
    for limit, name in [(1, "calm"), (3, "light air"), (7, "light breeze"),
                        (12, "gentle breeze"), (18, "moderate breeze"), (24, "fresh breeze"),
                        (31, "strong breeze"), (38, "near gale")]:
        if mph < limit:
            return name
    return "gale"


def bar_words(rel):
    """No trend field from Ambient's lastData; qualitative words need a 3h-ago sample instead."""
    return ""


def wind_rose_svg(recs, cur_dir, cur_speed):
    bins = [0.0] * 16
    calm = 0
    total = 0
    for r in recs:
        spd = r.get("windspeedmph")
        d = r.get("winddir")
        if spd is None:
            continue
        total += 1
        if spd < 0.5 or d is None:
            calm += 1
            continue
        bins[int((d / 22.5) + 0.5) % 16] += spd
    mx = max(bins) or 1.0
    calm_pct = round(100 * calm / total) if total else 0

    cx, cy, R, r0 = 110, 110, 92, 8
    parts = ['<svg viewBox="0 0 220 220" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:240px;">']
    for f in (0.33, 0.66, 1.0):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r0 + (R - r0) * f:.1f}" fill="none" stroke="var(--dial-track)" stroke-width="1"/>')
    for i, v in enumerate(bins):
        if v <= 0:
            continue
        length = r0 + (R - r0) * (v / mx)
        a0 = math.radians(i * 22.5 - 9.5 - 90)
        a1 = math.radians(i * 22.5 + 9.5 - 90)
        x0i, y0i = cx + r0 * math.cos(a0), cy + r0 * math.sin(a0)
        x1i, y1i = cx + r0 * math.cos(a1), cy + r0 * math.sin(a1)
        x0o, y0o = cx + length * math.cos(a0), cy + length * math.sin(a0)
        x1o, y1o = cx + length * math.cos(a1), cy + length * math.sin(a1)
        color = SAIL[min(int(v / mx * len(SAIL)), len(SAIL) - 1)]
        parts.append(f'<path d="M{x0i:.1f},{y0i:.1f} L{x0o:.1f},{y0o:.1f} A{length:.1f},{length:.1f} 0 0 1 {x1o:.1f},{y1o:.1f} L{x1i:.1f},{y1i:.1f} Z" fill="{color}" fill-opacity="0.92" stroke="var(--dial-ink)" stroke-width="0.8"/>')
    for i, lab in enumerate(["N", "E", "S", "W"]):
        a = math.radians(i * 90 - 90)
        x, y = cx + (R + 11) * math.cos(a), cy + (R + 11) * math.sin(a)
        parts.append(f'<text x="{x:.0f}" y="{y + 4:.0f}" text-anchor="middle" font-size="12" font-weight="800" fill="var(--dial-ink)">{lab}</text>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r0}" fill="var(--dial-ink)"/>')
    if cur_speed and cur_speed > 0.2 and cur_dir is not None:
        rot = (cur_dir + 180) % 360
        parts.append(f'<g transform="rotate({rot} {cx} {cy})"><path d="M{cx},{cy - 6.5} L{cx + 3.5},{cy + 4.5} L{cx},{cy + 2} L{cx - 3.5},{cy + 4.5} Z" fill="var(--accent)"/></g>')
    else:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="var(--accent)"/>')
    parts.append("</svg>")
    return "".join(parts), calm_pct


def wind_gauge_svg(now, gust, peak_today, wdir_label):
    """MWO-style speedometer: needle = current, orange band = current->gust, red tick = today's peak gust."""
    gmax = max(20, int(math.ceil((peak_today or 10) / 10.0)) * 10)
    cx, cy, R = 110, 104, 88

    def pt(v, r):
        a = math.radians(-120 + 240 * min(v, gmax) / gmax)
        return cx + r * math.sin(a), cy - r * math.cos(a)

    parts = ['<svg viewBox="0 0 220 182" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:240px;">']
    tx0, ty0 = pt(0, R - 4)
    tx1, ty1 = pt(gmax, R - 4)
    parts.append(f'<path d="M{tx0:.1f},{ty0:.1f} A{R - 4},{R - 4} 0 1 1 {tx1:.1f},{ty1:.1f}" fill="none" stroke="var(--dial-track)" stroke-width="7" stroke-linecap="round"/>')
    step = 5 if gmax <= 40 else 10
    v = 0
    while v <= gmax:
        major = v % (step * 2) == 0
        x1, y1 = pt(v, R)
        x2, y2 = pt(v, R - (10 if major else 5))
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="var(--dial-ink)" stroke-width="{2 if major else 1}"/>')
        if major:
            lx, ly = pt(v, R - 20)
            parts.append(f'<text x="{lx:.1f}" y="{ly + 3.5:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="var(--muted)">{v}</text>')
        v += step
    if now is not None and gust is not None and gust > now:
        x1, y1 = pt(now, R - 4)
        x2, y2 = pt(gust, R - 4)
        large = 1 if (gust - now) / gmax * 240 > 180 else 0
        parts.append(f'<path d="M{x1:.1f},{y1:.1f} A{R - 4},{R - 4} 0 {large} 1 {x2:.1f},{y2:.1f}" fill="none" stroke="var(--accent)" stroke-width="7" stroke-linecap="round" stroke-opacity="0.55"/>')
    if peak_today:
        x1, y1 = pt(peak_today, R - 12)
        x2, y2 = pt(peak_today, R + 2)
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="var(--alert)" stroke-width="3"/>')
    nv = now or 0
    tx, ty = pt(nv, R - 26)
    a = math.radians(-120 + 240 * min(nv, gmax) / gmax)
    px, py = math.cos(a) * 4, math.sin(a) * 4
    parts.append(f'<polygon points="{tx:.1f},{ty:.1f} {cx - px:.1f},{cy - py:.1f} {cx + px:.1f},{cy + py:.1f}" fill="var(--dial-ink)"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="var(--dial-ink)"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="2" fill="var(--accent)"/>')
    parts.append(f'<text x="{cx}" y="{cy + 52}" text-anchor="middle" font-size="30" font-weight="800" fill="var(--dial-ink)">{esc(now)}</text>')
    parts.append(f'<text x="{cx}" y="{cy + 68}" text-anchor="middle" font-size="11" font-weight="700" fill="var(--accent)" letter-spacing="1">MPH FROM {wdir_label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def esc(x, nd=None):
    """Render a station value. nd is decimal places.

    nd=0 gives an integer, not 58.0. A positive nd keeps trailing zeros, so a tile
    reads 29.98 and 30.00 rather than jittering between 29.98 and 30.
    """
    if x is None:
        return "?"
    if nd is None or not isinstance(x, (int, float)):
        return x
    if nd == 0:
        return int(round(x))
    return f"{x:.{nd}f}"


SCHLYTER_EPOCH = datetime(1999, 12, 31, 0, 0, tzinfo=timezone.utc)
J2000 = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)


def sun_times(lat, lon, when):
    n = when.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1 + 0.5)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat_r = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
              - math.tan(lat_r) * math.tan(decl))
    if abs(cos_ha) > 1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    base = datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
    rise = (base + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)).astimezone(TZ)
    sett = (base + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)).astimezone(TZ)
    return rise, sett


def _moon_radec(dj):
    rad = math.radians
    N = rad((125.1228 - 0.0529538083 * dj) % 360)
    i = rad(5.1454)
    w = rad((318.0634 + 0.1643573223 * dj) % 360)
    e = 0.054900
    M = rad((115.3654 + 13.0649929509 * dj) % 360)
    Ms = rad((356.0470 + 0.9856002585 * dj) % 360)
    ws = rad((282.9404 + 0.0000470935 * dj) % 360)
    E = M + e * math.sin(M) * (1 + e * math.cos(M))
    for _ in range(4):
        E = E - (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    xv = math.cos(E) - e
    yv = math.sqrt(1 - e * e) * math.sin(E)
    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)
    xh = r * (math.cos(N) * math.cos(v + w) - math.sin(N) * math.sin(v + w) * math.cos(i))
    yh = r * (math.sin(N) * math.cos(v + w) + math.cos(N) * math.sin(v + w) * math.cos(i))
    zh = r * (math.sin(v + w) * math.sin(i))
    lon = math.atan2(yh, xh)
    lat = math.atan2(zh, math.sqrt(xh * xh + yh * yh))
    Ls = Ms + ws
    Lm = M + w + N
    D = Lm - Ls
    F = Lm - N
    lon += rad(-1.274) * math.sin(M - 2 * D) + rad(0.658) * math.sin(2 * D) \
        + rad(-0.186) * math.sin(Ms) + rad(-0.059) * math.sin(2 * M - 2 * D) \
        + rad(-0.057) * math.sin(M - 2 * D + Ms) + rad(0.053) * math.sin(M + 2 * D)
    lat += rad(-0.173) * math.sin(F - 2 * D)
    ecl = rad(23.4393 - 3.563e-7 * dj)
    x = math.cos(lon) * math.cos(lat)
    y = math.sin(lon) * math.cos(lat)
    z = math.sin(lat)
    xe, ye, ze = x, y * math.cos(ecl) - z * math.sin(ecl), y * math.sin(ecl) + z * math.cos(ecl)
    ra = math.atan2(ye, xe)
    dec = math.atan2(ze, math.sqrt(xe * xe + ye * ye))
    sun_lon = Ls + rad(1.915) * math.sin(Ms) + rad(0.020) * math.sin(2 * Ms)
    return ra, dec, lon, sun_lon


def _moon_alt(dt_utc, lat, lon):
    dj = (dt_utc - SCHLYTER_EPOCH).total_seconds() / 86400.0
    ra, dec, _, _ = _moon_radec(dj)
    d2000 = (dt_utc - J2000).total_seconds() / 86400.0
    lst = math.radians((280.46061837 + 360.98564736629 * d2000 + lon) % 360)
    ha = lst - ra
    lat_r = math.radians(lat)
    return math.degrees(math.asin(math.sin(lat_r) * math.sin(dec) + math.cos(lat_r) * math.cos(dec) * math.cos(ha)))


def moon_info(lat, lon, when):
    start = datetime(when.year, when.month, when.day, tzinfo=TZ)
    h0, rise, sett = 0.125, None, None
    prev_alt = _moon_alt(start.astimezone(timezone.utc), lat, lon) - h0
    for step in range(1, 241):
        t = start + timedelta(minutes=6 * step)
        alt = _moon_alt(t.astimezone(timezone.utc), lat, lon) - h0
        if prev_alt < 0 <= alt and rise is None:
            frac = prev_alt / (prev_alt - alt)
            rise = t - timedelta(minutes=6 * (1 - frac))
        if prev_alt >= 0 > alt and sett is None:
            frac = prev_alt / (prev_alt - alt)
            sett = t - timedelta(minutes=6 * (1 - frac))
        prev_alt = alt
    dj = (start.astimezone(timezone.utc) - SCHLYTER_EPOCH).total_seconds() / 86400.0 + 0.5
    _, _, mlon, slon = _moon_radec(dj)
    elong = (mlon - slon) % (2 * math.pi)
    illum = round((1 - math.cos(elong)) / 2 * 100)
    age = elong / (2 * math.pi)
    names = ["new moon", "waxing crescent", "first quarter", "waxing gibbous",
             "full moon", "waning gibbous", "last quarter", "waning crescent"]
    phase = names[int(((age * 8) + 0.5) % 8)]
    fmt = lambda t: t.strftime("%-I:%M%p").lower()[:-1] if t else "&mdash;"
    return fmt(rise), fmt(sett), phase, illum


def moon_icon_svg(illum_pct, waxing):
    f = max(0.0, min(1.0, illum_pct / 100.0))
    r, c = 10.0, 12.0
    rx = abs(2 * f - 1) * r
    if waxing:
        outer = f"M{c},{c - r} A{r},{r} 0 0 1 {c},{c + r}"
        sweep = 1 if f >= 0.5 else 0
    else:
        outer = f"M{c},{c - r} A{r},{r} 0 0 0 {c},{c + r}"
        sweep = 0 if f >= 0.5 else 1
    term = f"A{rx:.2f},{r} 0 0 {sweep} {c},{c - r}"
    return (f'<svg viewBox="0 0 24 24" width="30" height="30" xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{c}" cy="{c}" r="{r}" fill="var(--dial-ink)"/>'
            f'<path d="{outer} {term} Z" fill="#F5C63C"/>'
            f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="var(--dial-ink)" stroke-width="1.5"/></svg>')


def _rgba(hexcol, a):
    r, g, b = int(hexcol[1:3], 16), int(hexcol[3:5], 16), int(hexcol[5:7], 16)
    return f"rgba({r},{g},{b},{a})"


MODELS = [("gfs_seamless", "GFS", "#E1552A", []), ("ecmwf_ifs025", "ECMWF", "#3E63A8", []),
          ("gfs_hrrr", "HRRR", "#C98A12", [])]


def model_ds(series, width, ghost=False, subdued=False):
    parts_js = []
    for i, (key, nm, col, dash) in enumerate(MODELS):
        if not series.get(key):
            continue
        data = json.dumps(series.get(key, []))
        if ghost:
            colr = f"__RGBA({i},0.4)"
            parts_js.append(f'{{ type: "line", label: "{nm} gust", data: {data}, borderColor: {colr}, backgroundColor: {colr}, tension: 0.3, pointRadius: 0, borderWidth: 1.2, borderDash: [2, 3], spanGaps: true, yAxisID: "y" }}')
        elif subdued:
            colr = f"__RGBA({i},0.75)"
            parts_js.append(f'{{ type: "line", label: "{nm}", data: {data}, borderColor: {colr}, backgroundColor: {colr}, tension: 0.3, pointRadius: 0, borderWidth: 1.5, borderDash: [5, 4], spanGaps: true, yAxisID: "y" }}')
        else:
            dashjs = f', borderDash: {json.dumps(dash)}' if dash else ""
            parts_js.append(f'{{ type: "line", label: "{nm}", data: {data}, borderColor: S.m[{i}], backgroundColor: S.m[{i}], tension: 0.3, pointRadius: 0, borderWidth: {width}, spanGaps: true{dashjs}, yAxisID: "y" }}')
    return ",".join(parts_js)


# --------------------------------------------------------------------- main

def main():
    cfg = load_cfg()
    lat, lon = cfg["latitude"], cfg["longitude"]
    calib = load_calibration()

    d = fetch_current(cfg)
    try:
        recs = fetch_archive_24h(cfg)
    except Exception:
        recs = []
    try:
        hist30 = refresh_history30(cfg)
    except Exception:
        hist30 = []

    obs_local = datetime.fromtimestamp(d["dateutc"] / 1000, tz=timezone.utc).astimezone(TZ)
    # Date and time are shown in different places now -- the date above the Basic
    # hero temperature, the time pinned to the masthead corner -- so they are
    # formatted separately. Deliberately not a live JS clock: this is the
    # observation time, and it freezing is the signal that the render loop died.
    ts_date = obs_local.strftime("%A, %B %-d")
    ts_time = obs_local.strftime("%-I:%M %p")
    wdir_deg = d.get("winddir")
    wdir = COMPASS[int(((wdir_deg or 0) / 22.5) + 0.5) % 16]
    feels = d.get("feelsLike") or d.get("tempf")

    rose_svg, calm_pct = wind_rose_svg(recs, d.get("winddir"), d.get("windspeedmph"))
    gust24 = max((r for r in recs if r.get("windgustmph") is not None),
                 key=lambda r: r["windgustmph"], default=None)
    gust_line = ""
    if gust24:
        gt = datetime.fromtimestamp(gust24["dateutc"] / 1000, tz=timezone.utc).astimezone(TZ).strftime("%-I:%M %p")
        gd = COMPASS[int(((gust24.get("winddir") or 0) / 22.5) + 0.5) % 16]
        gust_line = f'{esc(gust24["windgustmph"], 1)} mph from {gd} at {gt}'
    temps24 = [r["tempf"] for r in recs if r.get("tempf") is not None]
    hi24 = max(temps24) if temps24 else None
    lo24 = min(temps24) if temps24 else None

    tr = sorted((r for r in recs if r.get("tempf") is not None), key=lambda r: r["dateutc"])
    def hour_label(ts_ms):
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(TZ)
        return dt.strftime("%-I%p").lower() if dt.minute < 5 and dt.hour % 3 == 0 else ""
    t24_labels = json.dumps([hour_label(r["dateutc"]) for r in tr])
    t24_temp = json.dumps([r.get("tempf") for r in tr])
    t24_dew = json.dumps([r.get("dewPoint") for r in tr])
    t24_rh = json.dumps([r.get("humidity") for r in tr])

    wr = sorted((r for r in recs if r.get("windspeedmph") is not None), key=lambda r: r["dateutc"])
    w24_labels = json.dumps([hour_label(r["dateutc"]) for r in wr])
    w24_avg = json.dumps([r.get("windspeedmph") for r in wr])
    w24_gust = json.dumps([r.get("windgustmph") for r in wr])
    peak24 = max((r["windgustmph"] for r in wr if r.get("windgustmph") is not None), default=None)

    # Direction is off the speed chart and into its own aligned strip below it.
    # It was a scatter series on a second 0-360 y-axis over an mph axis, which is
    # two unrelated scales sharing one plot; worse, direction is circular, so a
    # northerly wind alternated between 0 and 360 and drew a band of noise across
    # the top and bottom at once. Arrows do not wrap.
    dir_strip = wind_dir_strip(wr)

    # Hourly rainfall, derived from the daily counter rather than hourlyrainin --
    # that field is a rolling 60-minute total, so plotting it as bars would count
    # the same rain in twelve consecutive buckets.
    rr = sorted((r for r in recs if r.get("dailyrainin") is not None), key=lambda r: r["dateutc"])
    rain_buckets, prev_total = {}, None
    for r in rr:
        v = r["dailyrainin"]
        if prev_total is not None:
            inc = v - prev_total
            if inc < 0:
                # dailyrainin resets at local midnight; after a reset the new
                # reading is itself the rain that fell since.
                inc = v
            if inc > 0:
                hr = (datetime.fromtimestamp(r["dateutc"] / 1000, tz=timezone.utc)
                      .astimezone(TZ).replace(minute=0, second=0, microsecond=0))
                rain_buckets[hr] = rain_buckets.get(hr, 0.0) + inc
        prev_total = v

    r24_hours = []
    if rr:
        last = (datetime.fromtimestamp(rr[-1]["dateutc"] / 1000, tz=timezone.utc)
                .astimezone(TZ).replace(minute=0, second=0, microsecond=0))
        r24_hours = [last - timedelta(hours=n) for n in range(23, -1, -1)]
    r24_labels = json.dumps([h.strftime("%-I%p").lower()[:-1] if h.hour % 3 == 0 else ""
                             for h in r24_hours])
    r24_rain = json.dumps([round(rain_buckets.get(h, 0.0), 3) for h in r24_hours])
    r24_total = sum(rain_buckets.get(h, 0.0) for h in r24_hours)
    r24_wet = sum(1 for h in r24_hours if rain_buckets.get(h, 0.0) > 0)

    br = sorted((r for r in recs if r.get("baromrelin") is not None), key=lambda r: r["dateutc"])
    p24_labels = json.dumps([hour_label(r["dateutc"]) for r in br])
    p24_bar = json.dumps([r.get("baromrelin") for r in br])

    try:
        fc = fetch_forecast(cfg)
    except Exception:
        fc = {}
    f48 = {"labels": [], "temp": {}, "wind": {}, "gust": {}, "precip": []}
    om = fc.get("om")
    idxs = []
    if om:
        now_local = datetime.now(TZ).strftime("%Y-%m-%dT%H:00")
        times = om["time"]
        start = next((i for i, t in enumerate(times) if t >= now_local), 0)
        idxs = list(range(start, min(start + 168, len(times))))
        def flab(t):
            dt = datetime.fromisoformat(t)
            return dt.strftime("%a").upper() if dt.hour == 0 else ""
        f48["labels"] = [flab(times[i]) for i in idxs]
        for key, _, _, _ in MODELS:
            f48["temp"][key] = [om.get(f"temperature_2m_{key}", [None] * len(times))[i] for i in idxs]
            f48["wind"][key] = [om.get(f"wind_speed_10m_{key}", [None] * len(times))[i] for i in idxs]
            f48["gust"][key] = [om.get(f"wind_gusts_10m_{key}", [None] * len(times))[i] for i in idxs]
        precip_model = calib.get("precip_model") or "ecmwf_ifs025"
        pkey = f"precipitation_{precip_model}"
        prec = om.get(pkey, [None] * len(times))
        f48["precip"] = [prec[i] if i < len(prec) and prec[i] is not None else 0 for i in idxs]

    daily_precip = {}
    if om:
        precip_model = calib.get("precip_model") or "ecmwf_ifs025"
        pc = om.get(f"precipitation_{precip_model}", [])
        for i, t in enumerate(om["time"]):
            if i < len(pc) and pc[i] is not None:
                d_ = t[:10]
                daily_precip[d_] = daily_precip.get(d_, 0) + pc[i]
        daily_precip = {k: round(v, 2) for k, v in daily_precip.items()}

    daily_dew, night_dew = {}, {}
    if om:
        ecd = om.get("dew_point_2m_ecmwf_ifs025", [])
        acc_d, acc_n = {}, {}
        for i, t in enumerate(om["time"]):
            if i >= len(ecd) or ecd[i] is None:
                continue
            day_, hr = t[:10], int(t[11:13])
            if 12 <= hr <= 20:
                acc_d.setdefault(day_, []).append(ecd[i])
            elif hr >= 21:
                acc_n.setdefault(day_, []).append(ecd[i])
            elif hr <= 6:
                prev = (date.fromisoformat(day_) - timedelta(days=1)).isoformat()
                acc_n.setdefault(prev, []).append(ecd[i])
        daily_dew = {k: round(sum(v) / len(v)) for k, v in acc_d.items()}
        night_dew = {k: round(sum(v) / len(v)) for k, v in acc_n.items()}

    fcast_cards = ""
    for pi, p in enumerate(fc.get("periods", [])):
        pop = f' &middot; {p["pop"]}% chance' if p.get("pop") else ""
        dew = daily_dew.get(p.get("date")) if p["day"] else night_dew.get(p.get("date"))
        dew_txt = f' &middot; dew {dew}&deg;' if dew is not None else ""
        amt = daily_precip.get(p.get("date"))
        amt_txt = (f' &middot; <b class="sw-blue">~{amt}&Prime;</b>'
                   if amt is not None and amt >= 0.01 and (p["day"] or pi == 0) else "")
        short = p["short"] if len(p["short"]) <= 42 else p["short"][:40] + "&hellip;"
        fcast_cards += (f'<div class="card"><div class="label">{p["name"]}</div>'
                        f'<div class="val">{p["temp"]}&deg;</div>'
                        f'<div class="sub">{short}{pop}{dew_txt}{amt_txt}</div></div>')

    alert_html = ""
    for a in fc.get("alerts", []):
        alert_html += f'<div class="alert">&#9888; {a["event"]}<span> &mdash; {a.get("headline","")}</span></div>'

    afd_html = ""
    if fc.get("afd"):
        try:
            issued = datetime.fromisoformat(fc["afd"]["time"].replace("Z", "+00:00")).astimezone(TZ).strftime("%-I:%M %p, %b %-d")
        except Exception:
            issued = ""
        raw = fc["afd"]["text"]
        first_sec = raw.find("\n.")
        last_close = raw.rfind("$$")
        body = raw[first_sec:last_close if last_close > first_sec else len(raw)].strip()
        paras_html = ""
        for block in body.split("\n\n"):
            block = block.strip()
            if not block or block == "$$" or block == "&&":
                continue
            lines = block.split("\n")
            if lines[0].startswith("."):
                header = lines[0].strip(".").split("...")[0]
                paras_html += f'<p class="afdh">{header}</p>'
                lines = lines[1:]
            text = " ".join(l.strip() for l in lines if l.strip() not in ("&&", "$$"))
            if text:
                text = text.replace("&", "&amp;").replace("<", "&lt;")
                paras_html += f"<p>{text}</p>"
        cwa = fc.get("cwa", "")
        afd_html = (f'<div class="afd"><div class="afdhead">{cwa} Forecast Discussion <span>&middot; issued {issued}</span></div>'
                    f'<div class="afdtext">{paras_html}</div></div>')

    gauge_cap = (f'mph &middot; <span class="sw-temp">&#9644;</span> your gauge, calibrated &middot; '
                 f'<span class="sw-gust">&#9644;</span> gust envelope at your gauge &middot; '
                 f'dashed = raw models')
    f48_labels = json.dumps(f48["labels"])
    f48_temp_ds = model_ds(f48["temp"], 2)
    f48_wind_ds = model_ds(f48["wind"], 0, subdued=True)
    f48_precip = json.dumps(f48["precip"])
    has_forecast = bool(f48["labels"])

    calibrated = bool(calib.get("wind_monthly")) and calib.get("gust_factor") is not None
    if has_forecast and calibrated:
        month_factor = calib["wind_monthly"].get(str(datetime.now(TZ).month), 1.0)
        dir_anom = calib.get("dir_anom", {})
        n_hours = len(f48["labels"])
        gauge_line = []
        for i in range(n_hours):
            vals, u, v_ = [], 0.0, 0.0
            for k, _, _, _ in MODELS:
                spd = f48["wind"][k][i] if i < len(f48["wind"][k]) else None
                if spd is None:
                    continue
                vals.append(spd)
                darr = om.get(f"wind_direction_10m_{k}")
                if darr and i < len(idxs) and idxs[i] < len(darr) and darr[idxs[i]] is not None:
                    u += spd * math.sin(math.radians(darr[idxs[i]]))
                    v_ += spd * math.cos(math.radians(darr[idxs[i]]))
            if not vals:
                gauge_line.append(None)
                continue
            factor = month_factor
            if u or v_:
                deg = math.degrees(math.atan2(u, v_)) % 360
                sector = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((deg / 45) + 0.5) % 8]
                factor = max(0.05, min(0.60, month_factor * dir_anom.get(sector, 1.0)))
            gauge_line.append(round(sum(vals) / len(vals) * factor, 1))
        gauge_gust = []
        gust_factor = calib["gust_factor"]
        for i in range(n_hours):
            gv = [f48["gust"][k][i] for k, _, _, _ in MODELS if i < len(f48["gust"][k]) and f48["gust"][k][i] is not None]
            gauge_gust.append(round(sum(gv) / len(gv) * gust_factor, 1) if gv else None)
        f48_wind_ds += (', { type: "line", label: "Gusts at your gauge", data: ' + json.dumps(gauge_gust)
                        + ', borderColor: S.gust, backgroundColor: S.gustFill,'
                        ' tension: 0.3, pointRadius: 0, borderWidth: 1.5, fill: "+1", spanGaps: true, yAxisID: "y" }'
                        ', { type: "line", label: "At your gauge", data: ' + json.dumps(gauge_line)
                        + ', borderColor: S.temp, backgroundColor: S.temp, tension: 0.3,'
                        ' pointRadius: 0, borderWidth: 2.5, spanGaps: true, yAxisID: "y" }')

    rate = d.get("hourlyrainin") or 0
    if rate:
        storm_line = f"raining now &middot; {rate}&Prime;/hr"
    elif d.get("lastRain"):
        try:
            lr = datetime.fromisoformat(d["lastRain"].replace("Z", "+00:00")).astimezone(TZ)
            storm_line = f"last rain {lr.strftime('%b %-d, %-I:%M %p')}"
        except Exception:
            storm_line = ""
    else:
        storm_line = ""

    monthly = json.loads(MONTHLY.read_text()) if MONTHLY.exists() else {}
    hist_days = {dstr: v for dstr, v in hist30}
    today = date.today()
    prev_ym = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if prev_ym not in monthly:
        prev_days = [v["rain"] for dstr, v in hist_days.items() if dstr.startswith(prev_ym) and v.get("rain") is not None]
        first_prev = date(*map(int, prev_ym.split("-")), 1)
        days_in_prev = ((first_prev.replace(day=28) + timedelta(days=4)).replace(day=1) - first_prev).days
        if len(prev_days) >= days_in_prev:
            monthly[prev_ym] = round(max(prev_days), 2) if prev_days else 0
            MONTHLY.write_text(json.dumps(monthly, indent=1))
    comps = []
    for back in (1, 2):
        m = today.month - back
        ym = f"{today.year - (1 if m < 1 else 0)}-{(m if m > 0 else m + 12):02d}"
        if ym in monthly:
            comps.append(f"{date(2000, int(ym[5:]), 1).strftime('%b')} {monthly[ym]}&Prime;")
    month_sub = ("full months &mdash; " + " &middot; ".join(comps)) if comps else "no history yet"

    rise, sett = sun_times(lat, lon, today)

    # ---- Basic view -------------------------------------------------------
    def _daylight(dt):
        r, st = sun_times(lat, lon, dt.date())
        if not r or not st:
            return 6 <= dt.hour < 18
        return r <= dt <= st

    now_local = datetime.now(TZ)
    hourly = fc.get("hourly") or []
    cond_short = ""
    if hourly:
        cond_short = hourly[0].get("shortForecast", "")
    elif fc.get("periods"):
        cond_short = fc["periods"][0]["short"]

    today_str = today.isoformat()
    t_hi = next((p["temp"] for p in fc.get("periods", [])
                 if p["date"] == today_str and p["day"]), None)
    t_lo = next((p["temp"] for p in fc.get("periods", [])
                 if p["date"] == today_str and not p["day"]), None)
    # After sunset NWS drops today's daytime period, so today's high stops being a
    # forecast at all: it already happened and the station measured it. Falling back
    # to the current temperature (the old behaviour) printed "H:47 L:45" on a day
    # that reached 69, and left the 5-day row's high as an em-dash with no bar.
    obs_today = [r["tempf"] for r in recs
                 if r.get("tempf") is not None
                 and datetime.fromtimestamp(r["dateutc"] / 1000, tz=timezone.utc)
                             .astimezone(TZ).date() == today]
    if d.get("tempf") is not None:
        obs_today.append(d["tempf"])
    if t_hi is None and obs_today:
        t_hi = round(max(obs_today))
    if t_lo is None and obs_today:
        t_lo = round(min(obs_today))

    b_tiles = [
        ("Wind", f'{esc(d.get("windspeedmph"), 1)} <span class="bunit">mph</span>',
         f'{wdir} \u00b7 gust {esc(d.get("windgustmph"), 1)}'),
        ("Humidity", f'{esc(d.get("humidity"), 0)}<span class="bunit">%</span>',
         f'dew {esc(d.get("dewPoint"), 0)}\u00b0'),
        ("Rain today", f'{esc(d.get("dailyrainin"), 2)}<span class="bunit">in</span>',
         f'{esc(d.get("monthlyrainin"), 2)}in this month'),
        ("Pressure", f'{esc(d.get("baromrelin"), 2)}<span class="bunit">in</span>',
         bar_words(d.get("baromrelin"))),
        ("UV index", f'{esc(d.get("uv"), 0)}', f'{esc(d.get("solarradiation"), 0)} W/m\u00b2'),
        ("Sunset", sett.strftime("%-I:%M").lower() if sett else "\u2014",
         f'sunrise {rise.strftime("%-I:%M%p").lower()[:-1]}' if rise else ""),
    ]

    b_days = basicview.daily_strip(fc.get("periods", []), 5,
                                   today=today_str, today_hi=t_hi, today_lo=t_lo)

    basic_html = basicview.build(
        now_temp=round(d.get("tempf") or 0),
        feels=round(d.get("feelsLike") or d.get("tempf") or 0),
        cond_short=cond_short,
        cond_is_day=_daylight(now_local),
        today_hi=t_hi, today_lo=t_lo,
        parts=basicview.day_parts(hourly, now_local, 4, is_daylight=_daylight),
        days=b_days,
        tiles=b_tiles,
        alerts=fc.get("alerts") or [],
        when=ts_date,
        hours=basicview.hourly_strip(hourly, now_local, 12, is_daylight=_daylight))
    radar_html = basicview.radar_tab(
        basicview.day_parts(hourly, now_local, 4, is_daylight=_daylight))

    # ---- Forecast tab: 120h temp + PoP trend -------------------------------
    # Both series come from the NWS hourly periods already fetched for Basic, so
    # the tab costs no extra request. Open-Meteo's hourly would give amounts too,
    # but mixing a model's precipitation with NOAA's probability on one chart
    # invites reading them as the same forecast.
    f120_labels, f120_times, f120_temp, f120_pop, f120_nights = [], [], [], [], []
    night_start = None
    for i, p in enumerate(hourly[:120]):
        try:
            dt = datetime.fromisoformat(p["startTime"])
        except (ValueError, KeyError):
            continue
        # A label every six hours; the rest are blank so the axis stays readable
        # across five days without dropping the points between them.
        if i == 0:
            lab = "Now"
        elif dt.hour == 0:
            lab = dt.strftime("%a")
        elif dt.hour % 6 == 0:
            lab = dt.strftime("%-I%p").lower()[:-1]
        else:
            lab = ""
        f120_labels.append(lab)
        f120_times.append(dt.strftime("%a %-I%p").replace("AM", "am").replace("PM", "pm"))
        f120_temp.append(p.get("temperature"))
        f120_pop.append((p.get("probabilityOfPrecipitation") or {}).get("value") or 0)
        idx = len(f120_labels) - 1
        if not _daylight(dt):
            if night_start is None:
                night_start = idx
        elif night_start is not None:
            f120_nights.append([night_start, idx])
            night_start = None
    if night_start is not None and f120_labels:
        f120_nights.append([night_start, len(f120_labels) - 1])
    # json.dumps, not repr: a missing NWS temperature is None, which is not JS.
    f120_labels_js = json.dumps(f120_labels)
    f120_times_js = json.dumps(f120_times)
    f120_temp_js = json.dumps(f120_temp)
    f120_pop_js = json.dumps(f120_pop)
    f120_nights_js = json.dumps(f120_nights)

    # 120 hourly points squashed into a phone's width turned five days of diurnal
    # swing into a picket fence. The canvas gets a floor of 720px inside a
    # horizontal scroller instead, so each hour keeps about 6px whatever the screen
    # is; on a desktop it still just fills the box.
    fc_chart_html = (
        '<h2>Next 5 Days <span class="accent">/</span> Temp &amp; Chance of Rain</h2>'
        + chart_fig("fc120", 250,
                    '<span class="sw-temp">&#9644;</span> temperature &nbsp;&middot;&nbsp; '
                    '<span class="sw-blue">&#9644;</span> chance of precipitation, % '
                    '(right axis) &nbsp;&middot;&nbsp; shaded = night &nbsp;&middot;&nbsp; '
                    'scrolls sideways &nbsp;&middot;&nbsp; NWS hourly forecast',
                    scroll=True)) if f120_labels else ""
    if rise and sett:
        daylen = sett - rise
        dl_h, dl_m = divmod(int(daylen.total_seconds() // 60), 60)
        sun_val2 = f"{rise.strftime('%-I:%M%p').lower()[:-1]} &rarr; {sett.strftime('%-I:%M%p').lower()[:-1]}"
        sun_sub2 = f"{dl_h}h {dl_m}m of daylight &middot; UV {esc(d.get('uv'), 0)} &middot; {esc(d.get('solarradiation'), 0)} W/m&sup2;"
    else:
        sun_val2, sun_sub2 = "&mdash;", "polar day/night"

    try:
        m_rise, m_set, m_phase, m_illum = moon_info(lat, lon, today)
        icon = moon_icon_svg(m_illum, "waxing" in m_phase or m_phase in ("new moon", "first quarter"))
        moon_val = (f'<span style="display:flex;align-items:center;gap:9px;">{icon}'
                    f'<span style="font-size:13px;line-height:1.55;white-space:nowrap;">'
                    f'<span class="sw-temp" style="font-size:9px;letter-spacing:1px;">RISE</span> {m_rise}<br>'
                    f'<span class="sw-temp" style="font-size:9px;letter-spacing:1px;">SET</span> {m_set}</span></span>')
        moon_sub = f"{m_phase} &middot; {m_illum}% lit"
    except Exception:
        moon_val, moon_sub = "&mdash;", ""

    ytd_sub = "total moisture since Jan 1"
    if YTDREF.exists():
        ref = json.loads(YTDREF.read_text())
        doy = min(today.timetuple().tm_yday, 365) - 1
        comps2, vals = [], []
        for yr in sorted(ref, reverse=True):
            arr = ref[yr]["cum"]
            v = arr[min(doy, len(arr) - 1)]
            vals.append(v)
            tilde = "~" if ref[yr].get("est") else ""
            comps2.append(f"'{yr[2:]} {tilde}{v}&Prime;")
        ytd_now = d.get("yearlyrainin")
        if vals and ytd_now is not None:
            delta = ytd_now - sum(vals) / len(vals)
            verdict = f"{'+' if delta >= 0 else ''}{delta:.1f}&Prime; vs {len(vals)}-yr avg"
            ytd_sub = " &middot; ".join(comps2) + f" &mdash; <b>{verdict}</b>"

    labels = json.dumps([dstr[5:] for dstr, _ in hist30])
    highs = json.dumps([v["hi"] for _, v in hist30])
    lows = json.dumps([v["lo"] for _, v in hist30])
    rain30 = json.dumps([v["rain"] for _, v in hist30])

    wind_now = d.get("windspeedmph")
    gust_now = d.get("windgustmph")
    peak_today = d.get("maxdailygust")
    gauge_svg = wind_gauge_svg(wind_now, gust_now, peak_today, wdir)

    run_sub = ""
    run24_vals = [r["windspeedmph"] for r in wr if r.get("windspeedmph") is not None]
    if WIND_RUN_DIST.exists() and run24_vals:
        # Normalised 24h wind run, matching how calibrate.py builds the distribution
        # (avg mph x 24). The original /4.0 assumed WeatherLink's 15-minute archive
        # records; Ambient logs every 5 minutes, which made every day read 3x high.
        run24 = (sum(run24_vals) / len(run24_vals)) * 24
        pctls = json.loads(WIND_RUN_DIST.read_text())["percentiles"]
        pct = max((int(p) for p, v in pctls.items() if v <= run24), default=1)
        tier = ("dead calm" if pct <= 10 else "quiet" if pct <= 40 else
                "typical" if pct <= 70 else "breezy" if pct <= 90 else
                "big day" if pct <= 98 else "rager")
        suffix = "th" if 10 <= pct % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(pct % 10, "th")
        run_sub = f'<div class="sub2">24h: {run24:.0f} mi &middot; {pct}{suffix} pctile &middot; {tier}</div>'

    station_name = cfg.get("station_name", "Weather Station")
    location = cfg.get("location", "")
    elev = cfg.get("elevation_ft")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    A = sync_vendor(OUT.parent)
    theme_js = THEME_JS.replace("__MDI_CSS__", A["mdi"])

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{station_name}">
<meta name="theme-color" content="#FFFFFF">
<meta name="mobile-web-app-capable" content="yes">
<link rel="manifest" href="manifest.webmanifest">
<!-- Inter and JetBrains Mono (Paper theme), Montserrat and Lato (Minimal), served
     from vendor/. Loaded unconditionally because a font swapped in after a theme
     change reflows the whole page; `font-display: swap` plus a full system
     fallback stack means a missing webfont costs nothing but itself. -->
<link rel="stylesheet" href="{A['fonts']}">
<link rel="icon" href="favicon.ico" sizes="32x32">
<link rel="icon" type="image/png" sizes="32x32" href="icon-32.png{ICON_V}">
<!-- Unversioned on purpose: iOS ignores a query string here and probes this exact
     name at the site root anyway, so the conventional path is what has to exist. -->
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
<title>{station_name}</title>
<!-- Chart.js and Leaflet used to sit here. A synchronous script in the head blocks
     first paint until it arrives, so on a cold cellular start the app showed a
     white screen for as long as two CDN round trips took -- which is what the
     splash was being asked to cover. They now load at the end of the body,
     immediately before the inline scripts that use them, which keeps execution
     order identical (both are still synchronous) while letting the page paint as
     soon as the body starts parsing. Do not move them back, and do not add defer:
     the chart and radar initialisers call `new Chart` and `L.map` inline with no
     ready-guard, so defer would execute them after those calls. -->
<!-- Leaflet's stylesheet stays in the head, where a <link> is actually valid, but
     loads asynchronously: `media="print"` makes it non-render-blocking, and the
     onload handler promotes it to all media once it has arrived. A plain
     stylesheet here would block first paint exactly as the scripts used to, and
     Radar is not the opening view, so it has time to land. -->
<link rel="stylesheet" href="{A['leaflet_css']}"
      media="print" onload="this.media='all'">
{BOOT_JS}
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ -webkit-text-size-adjust: 100%; }}

/* ---- Themes -----------------------------------------------------------------
   Every colour in the page comes from these tokens. Light is the base; dark and
   retro override. Layout, spacing and type scale are shared -- only the palette,
   border weight, corner radius and text shadow change between them. */
/* ---- Cold-start splash ------------------------------------------------------
   Painted from theme tokens, so it is already the right palette on frame one --
   see BOOT_JS. Hidden entirely unless `cold` is set, which costs a warm reload
   nothing but the markup. */
#splash {{ display: none; }}
html.cold #splash {{
  display: flex; position: fixed; inset: 0; z-index: 9999;
  flex-direction: column; align-items: center; justify-content: center; gap: 18px;
  background: var(--bg); background-image: var(--bg-img);
  opacity: 1; transition: opacity 240ms ease-out;
}}
html.cold #splash.gone {{ opacity: 0; pointer-events: none; }}
#splash img {{ width: 96px; height: 96px; }}
#splash .splash-name {{
  font-family: var(--font); font-size: 20px; font-weight: 700;
  letter-spacing: 0.10em; text-transform: uppercase; color: var(--fg);
}}
#splash .splash-sub {{
  font-family: var(--font); font-size: 11px; letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--muted);
}}
@media (prefers-reduced-motion: reduce) {{
  html.cold #splash {{ transition: none; }}
}}

:root {{
  --font: Futura, "Avenir Next", "Century Gothic", sans-serif;
  --font-num: var(--font);
  --bg: #FFFFFF;
  --bg-img: none;
  --panel: #FFFFFF;
  --panel-img: none;
  --fg: #14171C;
  --muted: #6B7280;
  --faint: #8A9099;
  --label: #E1552A;
  --line: #14171C;
  --hair: rgba(20,23,28,0.12);
  --bw: 2px;
  --rad: 0px;
  --accent: #E1552A;
  --accent-fg: #FFFFFF;
  --blue: #3E63A8;
  --alert: #C93A2E;
  --alert-fg: #FFFFFF;
  --head-bg: #FFFFFF;
  --head-fg: #14171C;
  --head-sub: #6B7280;
  /* Overlays are separate from the masthead: the radar chips must stay legible
     over map tiles, and the footer badge is an inverted pill by design -- both
     would vanish if they followed a light header. */
  --overlay-bg: rgba(20,23,28,0.88);
  --overlay-fg: #FFFFFF;
  --rule: var(--accent);
  --rule-h: 4px;
  --tshadow: none;
  --caps: uppercase;
  --icon-stroke: none;
  --icon-shadow: none;
  --icon-moon: #7E8CA8;
  --icon-flake: #93A7BC;
  --icon-fog: #99A5B3;
  --chart-bg: var(--panel);
  --chart-ink: #4A5260;
  --chart-grid: rgba(20,23,28,0.13);
  /* Series colours. Chart.js bakes colour in at construction, so these are read
     as tokens when a chart is built and the whole set is rebuilt on a theme
     change -- which is how a greyscale theme gets greyscale charts. */
  --s-temp: #E1552A;
  --s-temp-fill: rgba(225,85,42,0.18);
  --s-ink: #111111;
  --s-blue: rgba(62,99,168,0.75);
  --s-blue-solid: #3E63A8;
  --s-blue-fill: rgba(62,99,168,0.22);
  --s-bar: rgba(62,99,168,0.60);
  --s-gust: rgba(243,168,59,0.55);
  --s-gust-fill: rgba(245,198,60,0.30);
  --s-peak: #C1121F;
  --s-model-0: #E1552A;
  --s-model-1: #3E63A8;
  --s-model-2: #C98A12;
  --dial-ink: #14171C;
  --dial-track: #DCE0E6;
}}

[data-theme="dark"] {{
  --bg: #0E1116;
  --panel: #171B22;
  --fg: #E9ECF1;
  --muted: #98A0AC;
  --faint: #7B8391;
  --label: #FF7A4D;
  --line: #E9ECF1;
  --hair: rgba(233,236,241,0.16);
  --accent: #FF7A4D;
  --accent-fg: #14171C;
  --blue: #7BA0E8;
  --alert: #E14B3C;
  --head-bg: #05070A;
  --head-fg: #E9ECF1;
  --head-sub: #79828F;
  --overlay-bg: rgba(5,7,10,0.92);
  --overlay-fg: #E9ECF1;
  --chart-bg: #12161C;
  --chart-ink: #B8C0CC;
  --chart-grid: rgba(233,236,241,0.16);
  --icon-moon: #E8DCC0;
  --icon-flake: #DCE7F2;
  --icon-fog: #BFC7D2;
  --dial-ink: #E9ECF1;
  --dial-track: rgba(233,236,241,0.20);
}}

/* Retro: the 1990s cable weather-channel look. Mauve ground, banded blue
   panels, yellow labels, white values, hard black shadow on everything, chunky
   monospace. */
[data-theme="retro"] {{
  /* Palette taken from the ws4kp simulator's own
     shared/_colors.scss rather than eyeballed from a screenshot:

       background gradient  #102080 -> #001040     (dark navy, not mid blue)
       panel / "blue box"   #26235a
       column header        #200057
       titles               yellow
       values               white, with a hard black shadow
       cold / low           #8080FF
       heat index           #e00

     The previous version had the gradient far too light (#8296EE -> #2740B4),
     which is why white text on it was unreadable: the ink was right and the
     ground was wrong. It also banded the panels, so text sat on a moving value.
     Panels are flat now -- every string sits on one known colour. */
  --font: "Helvetica Neue", Helvetica, Arial, sans-serif;
  --font-num: var(--font);
  --bg: #001040;
  --bg-img: linear-gradient(180deg, #102080 0%, #001040 100%);
  --panel: #26235a;
  --panel-img: none;
  --fg: #FFFFFF;
  --muted: #FFFF00;
  --faint: #C6CEEA;
  --label: #FFFF00;
  --line: #FFFFFF;
  --hair: rgba(255,255,255,0.34);
  --bw: 2px;
  --rad: 0px;
  --accent: #FFFF00;
  --accent-fg: #001040;
  --blue: #8080FF;
  --alert: #EE0000;
  --alert-fg: #FFFFFF;
  --head-bg: #200057;
  --head-fg: #FFFF00;
  --head-sub: #C6CEEA;
  --overlay-bg: #200057;
  --overlay-fg: #FFFF00;
  --rule: #FFFF00;
  --rule-h: 3px;
  --tshadow: 2px 2px 0 #000000;
  --caps: uppercase;
  --icon-stroke: #101010;
  --icon-shadow: drop-shadow(2px 2px 0 rgba(0,0,0,0.85));
  --icon-moon: #E8DCC0;
  --icon-flake: #DCE7F2;
  --icon-fog: #BFC7D2;
  /* Charts sit in the palette now. The old near-black #0E1330 was a patch for
     the light gradient and matched nothing else on the page. */
  --chart-bg: #26235a;
  --chart-ink: #FFFFFF;
  --chart-grid: rgba(255,255,255,0.26);
  --dial-ink: #FFFFFF;
  --dial-track: rgba(255,255,255,0.30);
  /* Series in the 4000's own vocabulary: yellow leads, periwinkle is cold. */
  --s-temp: #FFFF00;
  --s-temp-fill: rgba(255,255,0,0.16);
  --s-ink: #FFFFFF;
  --s-blue: #8080FF;
  --s-blue-solid: #8080FF;
  --s-blue-fill: rgba(128,128,255,0.22);
  --s-bar: rgba(128,128,255,0.75);
  --s-gust: rgba(255,255,0,0.45);
  --s-gust-fill: rgba(255,255,0,0.14);
  --s-peak: #EE0000;
  --s-model-0: #FFFF00;
  --s-model-1: #8080FF;
  --s-model-2: #FFFFFF;
}}

/* ---- paper: graph paper and one accent ----------------------------------------
   Paper-white ground with a faint graph-paper grid (two 1px gradients at 46px)
   running the full page at low opacity, which is what makes it read as paper
   rather than as a table.

   Thin throughout: 1px rules, a 10px radius, ink that is grey rather
   than black, and one saturated accent doing all the emphasis. */
[data-theme="paper"] {{
  --font: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-num: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace;
  --bg: #FDFDFE;
  --bg-img: linear-gradient(rgba(227,228,234,0.55) 1px, transparent 1px),
            linear-gradient(90deg, rgba(227,228,234,0.55) 1px, transparent 1px);
  --panel: #FFFFFF;
  --panel-img: none;
  --fg: #17191E;
  --muted: #5C5F6B;
  --faint: #686B78;
  --label: #5C5F6B;
  --line: #C9CBD4;
  --hair: #E3E4EA;
  --bw: 1px;
  --rad: 10px;
  --accent: #4A3AFF;
  --accent-fg: #FFFFFF;
  --blue: #2F6FEB;
  --alert: #C8372D;
  --alert-fg: #FFFFFF;
  --head-bg: #FFFFFF;
  --head-fg: #17191E;
  --head-sub: #686B78;
  --overlay-bg: rgba(23,25,30,0.90);
  --overlay-fg: #FDFDFE;
  --rule: var(--accent);
  --rule-h: 2px;
  --tshadow: none;
  --caps: uppercase;
  --icon-stroke: none;
  --icon-shadow: none;
  --icon-moon: #7E8CA8;
  --icon-flake: #93A7BC;
  --icon-fog: #99A5B3;
  --chart-bg: #FFFFFF;
  --chart-ink: #5C5F6B;
  --chart-grid: #E3E4EA;
  --dial-ink: #17191E;
  --dial-track: #E3E4EA;
}}

/* ---- minimal: an e-ink register -----------------------------------------------
   Styled after e-ink wall dashboards, which is why this theme is genuinely
   greyscale rather than "muted": there is no accent colour anywhere, and
   emphasis is carried by weight and size alone. Ink is #1A1A1A, borders are
   that same ink at low alpha, and the type is Montserrat over Lato.

   Weather glyphs switch to Material Design Icons here, the icon set those
   dashboards use, so the page matches one sitting beside it. */
[data-theme="minimal"] {{
  --font: "Montserrat", system-ui, -apple-system, sans-serif;
  --font-num: "Lato", system-ui, -apple-system, sans-serif;
  --bg: #FFFFFF;
  --bg-img: none;
  --panel: #FFFFFF;
  --panel-img: none;
  --fg: #1A1A1A;
  --muted: #5A5A5A;
  --faint: #8A8A8A;
  --label: #5A5A5A;
  --line: rgba(26,26,26,0.30);
  --hair: rgba(26,26,26,0.16);
  --bw: 1px;
  --rad: 4px;
  --accent: #1A1A1A;
  --accent-fg: #FFFFFF;
  --blue: #5A5A5A;
  --alert: #1A1A1A;
  --alert-fg: #FFFFFF;
  --head-bg: #FFFFFF;
  --head-fg: #1A1A1A;
  --head-sub: #8A8A8A;
  --overlay-bg: rgba(26,26,26,0.90);
  --overlay-fg: #FFFFFF;
  --rule: rgba(26,26,26,0.30);
  --rule-h: 1px;
  --tshadow: none;
  --caps: uppercase;
  --icon-stroke: none;
  --icon-shadow: none;
  --icon-moon: #5A5A5A;
  --icon-flake: #8A8A8A;
  --icon-fog: #8A8A8A;
  --chart-bg: #FFFFFF;
  --chart-ink: #5A5A5A;
  --chart-grid: rgba(26,26,26,0.14);
  --dial-ink: #1A1A1A;
  --dial-track: rgba(26,26,26,0.16);
  /* Greyscale series. Lines that were told apart by hue are told apart by
     value and dash here instead: temp is the darkest, the models step down
     through mid greys, and everything that was blue is a light neutral. */
  --s-temp: #1A1A1A;
  --s-temp-fill: rgba(26,26,26,0.10);
  --s-ink: #6A6A6A;
  --s-blue: rgba(26,26,26,0.42);
  --s-blue-solid: #8A8A8A;
  --s-blue-fill: rgba(26,26,26,0.10);
  --s-bar: rgba(26,26,26,0.55);
  --s-gust: rgba(26,26,26,0.26);
  --s-gust-fill: rgba(26,26,26,0.07);
  --s-peak: #1A1A1A;
  --s-model-0: #1A1A1A;
  --s-model-1: #7A7A7A;
  --s-model-2: #B4B4B4;
}}
/* Greyscale means greyscale. The chart palettes, the temperature gradient on the
   five-day bars and the wind-direction arrows are all colour-coded by value
   elsewhere; here they are re-stated in ink so nothing depends on hue. */
[data-theme="minimal"] .bdbar {{ background: rgba(26,26,26,0.55) !important; }}
[data-theme="minimal"] .bddot {{ background: #1A1A1A; }}
[data-theme="minimal"] .dirstrip svg path, [data-theme="minimal"] .dirstrip svg circle {{
  stroke: #1A1A1A; fill: none; }}
[data-theme="minimal"] .dirstrip svg circle {{ fill: #8A8A8A; stroke: none; }}
[data-theme="minimal"] .bdpop, [data-theme="minimal"] .bppop,
[data-theme="minimal"] .bhrpop {{ color: var(--muted); }}
/* The selected pill is the one solid black object on the page, as on the panel. */
[data-theme="minimal"] .tabbar button, [data-theme="minimal"] .subtabbar button {{
  background: rgba(26,26,26,0.07); color: var(--muted); opacity: 1; }}
[data-theme="minimal"] .tabbar button[aria-selected="true"],
[data-theme="minimal"] .subtabbar button[aria-selected="true"] {{
  background: #1A1A1A; color: #FFFFFF; }}
[data-theme="minimal"] .btemp, [data-theme="minimal"] .bigtemp {{ font-weight: 300; }}

/* ---- the two icon sets ------------------------------------------------------
   Both are baked into the page because the icon is rendered server-side and the
   theme is a browser choice. `display: contents` keeps the wrapper out of the
   layout entirely, so every rule that targets the drawn `svg` still matches. */
.ico {{ display: contents; }}
.ico .mdi {{ display: none; line-height: 1; color: currentColor; }}
[data-theme="minimal"] .ico .wxi {{ display: none; }}
[data-theme="minimal"] .ico .mdi {{ display: block; margin: 0 auto; color: var(--fg); }}
[data-theme="minimal"] .bhero .ico .mdi {{ color: var(--fg); }}
[data-theme="minimal"] .basic .bpart .ico .mdi {{ margin: 5px auto 3px; }}
[data-theme="minimal"] .basic .bhr .ico .mdi {{ margin: 2px auto; }}
/* The wind rose petals are colour-coded by frequency in the other themes, but
   petal *length* already encodes exactly that -- the colour is reinforcement.
   One grey loses nothing here, which is not true of the charts. */
[data-theme="minimal"] .rosebox svg path {{ fill: rgba(26,26,26,0.50); }}
[data-theme="minimal"] .gaugebox svg path,
[data-theme="minimal"] .gaugebox svg rect {{ fill: rgba(26,26,26,0.50); }}
/* 46px squares, matching the site. Panels paint over it, so the grid shows in
   the gutters and behind the page rather than through every card. */
[data-theme="paper"] body {{ background-size: 46px 46px; }}
/* Section labels sit in accent on the site, not in the warm orange the other
   themes use for the same job. */
[data-theme="paper"] .basic .bsec, [data-theme="paper"] h2 {{ color: var(--muted); }}
[data-theme="paper"] h2 .accent {{ color: var(--accent); }}
[data-theme="paper"] .basic .bplabel {{ color: var(--accent); letter-spacing: 0.9px; }}
/* One saturated accent doing the emphasis: the selected pill is the accent
   rather than an ink fill. */
[data-theme="paper"] .tabbar button[aria-selected="true"],
[data-theme="paper"] .subtabbar button[aria-selected="true"] {{
  background: var(--accent); color: var(--accent-fg); }}
[data-theme="paper"] .tabbar button, [data-theme="paper"] .subtabbar button {{
  background: #F4F4F7; color: var(--muted); opacity: 1; }}
/* Numbers in JetBrains Mono, as on the site. */
[data-theme="paper"] .btemp, [data-theme="paper"] .bptemp, [data-theme="paper"] .bval,
[data-theme="paper"] .bdhi, [data-theme="paper"] .bdlo, [data-theme="paper"] .bigtemp,
[data-theme="paper"] .mini .val, [data-theme="paper"] .card .val,
[data-theme="paper"] .bhrtemp {{ font-family: var(--font-num); letter-spacing: -0.5px; }}

body {{ font-family: var(--font); background: var(--bg); background-image: var(--bg-img);
  background-attachment: fixed; color: var(--fg); padding-bottom: 24px; }}

.masthead {{ background: var(--head-bg); color: var(--head-fg); padding: 10px 96px 8px 20px;
  padding-top: calc(10px + env(safe-area-inset-top)); display: flex; justify-content: space-between;
  align-items: center; flex-wrap: wrap; gap: 6px 12px; position: relative; }}
/* Absolutely placed rather than a flex child: the masthead's items wrap at
   different points in each theme (the families have different metrics), and the
   clock has to land in the same corner in all of them. */
.masthead .mastclock {{ position: absolute; right: 20px; top: calc(9px + env(safe-area-inset-top));
  font-size: 15px; font-weight: 800; letter-spacing: 0.5px; font-variant-numeric: tabular-nums;
  text-shadow: var(--tshadow); }}
.masthead h1 {{ font-size: 16px; font-weight: 800; letter-spacing: 2px; text-transform: uppercase;
  text-shadow: var(--tshadow); }}
.masthead .sub {{ font-size: 8px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--head-sub); }}
.masthead .switches {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
.rule {{ height: var(--rule-h); background: var(--rule); }}

main {{ max-width: 720px; margin: 0 auto; padding: 18px 20px; }}

.hero {{ display: flex; gap: 18px; align-items: center; border-bottom: 2px solid var(--hair);
  padding-bottom: 14px; margin-bottom: 14px; flex-wrap: wrap; }}
.bigtemp {{ font-size: 68px; font-weight: 800; line-height: 0.9; flex: 0 0 auto; text-shadow: var(--tshadow); }}
.bigtemp sup {{ font-size: 24px; color: var(--accent); }}
.ministats {{ flex: 1; display: grid; grid-template-columns: repeat(auto-fit, minmax(88px, 1fr)); gap: 8px 14px; min-width: 220px; }}
.mini .label {{ font-size: 9px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: var(--label); }}
.mini .val {{ font-size: 19px; font-weight: 800; line-height: 1.2; }}
.mini .val small {{ font-size: 11px; font-weight: 700; color: var(--faint); }}

/* Section headings match the Basic view's .bsec: a hairline underneath rather
   than a heavy bar above. The 4px near-black rule over every h2 was what made
   Detailed read as a different app to the tab beside it. Retro keeps the bar --
   the retro look is banded panels and hard rules, and losing them loses
   the theme. */
h2 {{ font-size: 11px; font-weight: 700; letter-spacing: 1.6px; text-transform: uppercase;
  color: var(--muted); border-bottom: 2px solid var(--hair);
  padding-bottom: 7px; margin: 22px 0 10px; text-shadow: var(--tshadow); }}
h2 .accent {{ color: var(--accent); }}
[data-theme="retro"] h2 {{ font-size: 13px; letter-spacing: 2px; color: var(--fg);
  border-bottom: 0; border-top: var(--rule-h) solid var(--line); padding: 8px 0 0; margin: 6px 0 10px; }}

.windwrap {{ display: flex; gap: 16px; align-items: center; margin-bottom: 18px; flex-wrap: wrap; }}
.rosebox {{ flex: 0 0 auto; width: 30%; max-width: 220px; }}
.gaugebox {{ flex: 0 0 auto; width: 30%; max-width: 220px; }}
.rosecap {{ font-size: 9px; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); text-align: center; margin-top: 4px; line-height: 1.6; }}
.rosecap b {{ color: var(--fg); }}
.dialhead {{ font-size: 11px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase; text-align: center; margin-bottom: 4px; }}
.dialhead span {{ color: var(--accent); }}
.cap {{ font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted); text-align: center; margin: -12px 0 18px; }}
.cap span {{ font-weight: 800; }}
/* Legend swatches read from the same series tokens as the charts, so they can
   never disagree with the line they describe. */
.sw-temp {{ color: var(--s-temp); }}
.sw-blue {{ color: var(--s-blue-solid); }}
.sw-gust {{ color: var(--s-gust); }}
.sw-m2 {{ color: var(--s-model-2); }}
.sw-peak {{ color: var(--s-peak); }}

.alert {{ background: var(--alert); color: var(--alert-fg); font-size: 12px; font-weight: 800; letter-spacing: 1px;
  text-transform: uppercase; padding: 8px 12px; margin-bottom: 12px; border-radius: var(--rad); }}
.alert span {{ font-weight: 400; text-transform: none; letter-spacing: 0; }}

.radarbox {{ border: var(--bw) solid var(--hair); height: 320px; margin-bottom: 4px; background: var(--panel);
  position: relative; border-radius: max(14px, var(--rad)); overflow: hidden; }}
#radarmap {{ height: 100%; width: 100%; }}
#radartime {{ color: var(--accent); font-weight: 800; }}
.radarstamp {{ position: absolute; top: 8px; right: 8px; z-index: 800; background: var(--overlay-bg); color: var(--overlay-fg);
  padding: 3px 10px 4px; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase;
  border: 1px solid var(--hair); border-radius: calc(var(--rad) / 2); }}
.radarstamp b {{ color: var(--accent); }}
/* The scrubber bar: play/pause plus a draggable time track, as Apple Weather has.
   It is a sibling of the map container, not a child, so dragging the thumb never
   reaches Leaflet's pan handlers. */
.radarbar {{ position: absolute; left: 8px; right: 8px; bottom: 8px; z-index: 800;
  display: flex; align-items: center; gap: 10px; padding: 7px 12px 6px;
  background: var(--overlay-bg); color: var(--overlay-fg); border-radius: max(14px, var(--rad));
  border: var(--bw) solid var(--hair); }}
.radarbar .rbplay {{ flex: 0 0 auto; width: 30px; height: 30px; border-radius: 50%; border: none;
  background: rgba(255,255,255,0.18); color: var(--overlay-fg); font-family: var(--font);
  font-size: 11px; line-height: 1; cursor: pointer; padding: 0; }}
.radarbar .rbplay:hover {{ color: var(--accent); }}
.radarbar .rbtrack {{ flex: 1; min-width: 0; }}
#radarslider {{ -webkit-appearance: none; appearance: none; display: block; width: 100%; height: 4px;
  margin: 0; border-radius: 2px; background: rgba(255,255,255,0.28); outline: none; cursor: pointer; }}
#radarslider::-webkit-slider-thumb {{ -webkit-appearance: none; appearance: none; width: 15px; height: 15px;
  border-radius: 50%; background: var(--overlay-fg); border: none; cursor: grab; }}
#radarslider::-moz-range-thumb {{ width: 15px; height: 15px; border-radius: 50%;
  background: var(--overlay-fg); border: none; cursor: grab; }}
#radarslider:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 4px; }}
.radarbar .rbticks {{ display: flex; justify-content: space-between; margin-top: 5px;
  font-size: 9px; font-weight: 700; letter-spacing: 0.6px; text-transform: uppercase;
  opacity: 0.7; font-variant-numeric: tabular-nums; }}

.radarplay {{ position: absolute; top: 44px; right: 8px; z-index: 800; background: var(--overlay-bg); color: var(--overlay-fg);
  width: 30px; height: 24px; line-height: 24px; text-align: center; font-size: 11px; font-weight: 800;
  border: 1px solid var(--hair); cursor: pointer; user-select: none; border-radius: calc(var(--rad) / 2); }}
.radarplay:hover {{ color: var(--accent); }}

.afd {{ background: var(--panel); background-image: var(--panel-img); border: var(--bw) solid var(--hair);
  margin-bottom: 18px; border-radius: max(14px, var(--rad)); }}
.afdhead {{ padding: 10px 14px 0; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase; }}
.afdhead span {{ color: var(--muted); font-weight: 400; letter-spacing: 0.5px; }}
.afdtext {{ padding: 6px 14px 14px; font-size: 12.5px; line-height: 1.65; color: var(--fg); }}
.afdtext p {{ margin-bottom: 10px; }}
.afdtext .afdh {{ font-weight: 800; font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent); margin: 14px 0 4px; }}

.windstats {{ flex: 1; min-width: 200px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; align-content: center; }}
.wstat .lab {{ color: var(--label); font-weight: 700; font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; }}
.wstat .wval {{ font-size: 15px; font-weight: 800; line-height: 1.3; }}
.wstat .sub2 {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }}

.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 18px; }}
.card {{ background: var(--panel); background-image: var(--panel-img); border: var(--bw) solid var(--hair);
  padding: 10px 12px; border-radius: max(14px, var(--rad)); }}
.card .label {{ font-size: 9px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: var(--label); margin-bottom: 3px; }}
.card .val {{ font-size: 22px; font-weight: 800; text-shadow: var(--tshadow); }}
.card .sub {{ font-size: 10px; color: var(--faint); margin-top: 2px; }}
/* The frame belongs to the figure, not the plot: plot, direction strip and
   caption are one bordered object rather than three stacked ones. */
.chartfig {{ background: var(--chart-bg); border: var(--bw) solid var(--hair);
  border-radius: max(14px, var(--rad)); padding: 12px 12px 9px; margin-bottom: 18px; }}
.chartplot {{ position: relative; height: 240px; }}
.chartfig .cap {{ margin: 8px 0 0; }}
.chartfig .radarbox {{ border: 0; border-radius: 0; margin-bottom: 0; }}
/* Kept for anything still using the old single-element form. */
.chartbox {{ background: var(--chart-bg); border: var(--bw) solid var(--hair); padding: 12px; height: 240px;
  position: relative; margin-bottom: 18px; border-radius: max(14px, var(--rad)); }}
/* A chart with more points than the screen has pixels scrolls rather than
   compresses. The inner box carries the real width; Chart.js sizes to it. */
.chartscroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: thin; }}
.chartscroll .chartwide {{ min-width: 720px; height: 100%; }}
/* Pinned axis gutters. The canvas keeps its gridlines and drops its tick text;
   these carry the numbers and do not scroll, so the scales stay readable at any
   offset. Opaque, so the plot slides underneath rather than through. */
.plotwrap {{ position: relative; }}
.axgut {{ position: absolute; top: 0; bottom: 0; width: 38px; pointer-events: none;
  background: var(--chart-bg); z-index: 2; }}
.axgut-l {{ left: 0; }}
.axgut-r {{ right: 0; }}
.axgut span {{ position: absolute; transform: translateY(-50%); font-size: 9px;
  color: var(--chart-ink); font-family: var(--font); white-space: nowrap; }}
.axgut-l span {{ right: 5px; }}
.axgut-r span {{ left: 5px; }}

/* Detailed's own section strip, built as pills to match the view tabs exactly.
   The colours differ only because this bar sits on the page background rather
   than on the masthead. */
.subtabbar {{ display: flex; gap: 4px; margin: 2px 0 14px; overflow-x: auto;
  -webkit-overflow-scrolling: touch; scrollbar-width: none; }}
.subtabbar::-webkit-scrollbar {{ display: none; }}
.subtabbar button {{ flex: 1 1 auto; white-space: nowrap; font: inherit; font-size: 11px;
  letter-spacing: 1.2px; text-transform: uppercase; font-weight: 700; border: 0;
  background: rgba(127,127,127,0.22); color: var(--fg); opacity: 0.75;
  padding: 8px 10px; border-radius: 999px; cursor: pointer; }}
.subtabbar button[aria-selected="true"] {{ background: var(--fg); color: var(--bg); opacity: 1; }}

/* Wind direction, on its own row under the speed chart rather than as a second
   y-axis on it.

   The left and right padding are set from the chart's own chartArea after it
   renders, so the twelve columns span exactly the plot and each arrow sits under
   the time it belongs to. Guessing the axis gutter in CSS would drift with the
   tick labels. */
.dirstrip {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 2px;
  margin: 6px 0 0; }}
.dirstrip .dcell {{ text-align: center; }}
.dirstrip .dcell svg {{ display: block; margin: 0 auto; }}
.dirstrip .dhr {{ font-size: 8px; letter-spacing: 0.4px; text-transform: uppercase;
  color: var(--faint); margin-top: 1px; }}
/* The first heading in a pane sits right under the strip and does not need its
   own 22px of air on top of it. */
#view-detail > div > h2:first-child {{ margin-top: 10px; }}

.footer {{ text-align: center; font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); }}
.footer .badge {{ display: inline-block; background: var(--overlay-bg); color: var(--overlay-fg); padding: 4px 12px; border-radius: var(--rad); }}
.footer .badge b {{ color: var(--accent); }}

#radar-slot-radar .radarbox {{ height: min(58vh, 520px); min-height: 320px; margin-bottom: 16px; }}
.radartab .bparts {{ margin-bottom: 4px; }}
/* The old cable-channel regional maps were flat grey landmasses, not blue. */
/* Scoped to the basemap layer, NOT .leaflet-tile-pane -- that pane is the parent of
   every tile layer, so a filter there also hit the eleven NEXRAD layers and
   flattened the whole green/yellow/orange/red reflectivity ramp to grey. The
   layers carry their class via Leaflet's GridLayer `className` option. */
[data-theme="retro"] .basetiles {{ filter: grayscale(1) brightness(0.70) contrast(1.08); }}
/* And since the ground under them is now fully desaturated, the echoes can afford
   to run a little hotter -- retro is a punchy-flat-colour theme. */
[data-theme="retro"] .radartiles {{ filter: saturate(1.2); }}
@media (max-width: 480px) {{ #radar-slot-radar .radarbox {{ height: min(52vh, 420px); }} }}

[hidden] {{ display: none !important; }}

/* ---- switches --------------------------------------------------------------- */
.themesel {{ font: inherit; font-size: 10px; letter-spacing: 1.2px; text-transform: uppercase;
  font-weight: 700; color: var(--head-fg); background: rgba(127,127,127,0.22); border: 0;
  border-radius: 999px; padding: 5px 22px 5px 11px; cursor: pointer; -webkit-appearance: none;
  appearance: none; background-image: linear-gradient(45deg, transparent 50%, currentColor 50%),
  linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position: right 11px center, right 7px center; background-size: 4px 4px, 4px 4px;
  background-repeat: no-repeat; }}
.themesel option {{ color: #14171C; background: #FFFFFF; }}

/* Its own full-width row rather than sharing the masthead: four tabs plus three
   theme buttons wrapped at different points in each theme, because the fonts have
   different metrics. A dedicated bar is deterministic and scales. */
.tabbar {{ display: flex; gap: 4px; background: var(--head-bg); padding: 0 12px 9px;
  overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }}
.tabbar::-webkit-scrollbar {{ display: none; }}
.tabbar button {{ flex: 1 1 auto; white-space: nowrap; font: inherit; font-size: 11px;
  letter-spacing: 1.2px; text-transform: uppercase; font-weight: 700; border: 0;
  background: rgba(127,127,127,0.22); color: var(--head-fg); opacity: 0.75;
  padding: 8px 10px; border-radius: 999px; cursor: pointer; }}
.tabbar button[aria-selected="true"] {{ background: var(--head-fg); color: var(--head-bg); opacity: 1; }}

/* ---- Basic view -------------------------------------------------------------- */
.basic .bsection {{ margin-bottom: 22px; }}
.basic .bsec {{ font-size: 10px; font-weight: 700; letter-spacing: 1.6px; text-transform: uppercase;
  color: var(--muted); margin: 0 0 9px; padding-bottom: 7px; border-bottom: 2px solid var(--hair); }}
.basic .bhero {{ display: flex; align-items: center; gap: 8px; padding: 6px 0 20px; }}
.basic .bicon {{ flex: 0 0 auto; }}
.basic .bwhen {{ font-size: 11px; font-weight: 700; letter-spacing: 1.6px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 5px; }}
.basic .btemp {{ font-size: 76px; font-weight: 300; line-height: 0.95; letter-spacing: -3px; text-shadow: var(--tshadow); }}
.basic .btemp sup {{ font-size: 26px; font-weight: 400; letter-spacing: 0; top: -0.45em; }}
.basic .bcond {{ font-size: 15px; margin-top: 4px; color: var(--fg); }}
.basic .bmeta {{ font-size: 12px; color: var(--muted); margin-top: 3px; letter-spacing: 0.3px; }}

.basic .balerts {{ margin-bottom: 14px; }}
.basic .balert {{ background: var(--alert); color: var(--alert-fg); font-size: 11px; font-weight: 700; letter-spacing: 1.2px;
  text-transform: uppercase; padding: 8px 12px; border-radius: max(10px, var(--rad)); margin-bottom: 6px; }}

.basic .bhours {{ display: flex; gap: 6px; overflow-x: auto; padding-bottom: 6px;
  scroll-snap-type: x proximity; -webkit-overflow-scrolling: touch; }}
.basic .bhours::-webkit-scrollbar {{ height: 4px; }}
.basic .bhours::-webkit-scrollbar-thumb {{ background: var(--hair); border-radius: 2px; }}
.basic .bhr {{ flex: 0 0 auto; width: 58px; text-align: center; padding: 10px 4px 8px;
  background: var(--panel); background-image: var(--panel-img); border: var(--bw) solid var(--hair);
  border-radius: max(12px, var(--rad)); scroll-snap-align: start; }}
.basic .bhrlab {{ font-size: 10px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 2px; }}
.basic .bhrpop {{ font-size: 10px; font-weight: 700; color: var(--blue); min-height: 13px; }}
.basic .bhrtemp {{ font-size: 17px; font-weight: 800; margin-top: 1px; }}

/* The day-part row stays four across at every width. Collapsing to 2x2 on a phone
   was what made this section tall: four bordered cards stacked two deep, each
   reserving a line for condition text. It is now a bare row -- no panel, no
   border -- reading label / icon / temperature / chance, sized between the hero
   temperature and its feels line. */
.basic .bparts {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 16px; }}
.basic .bpart {{ background: none; border: 0; padding: 2px 0; text-align: center; }}
.basic .bplabel {{ font-size: 9px; letter-spacing: 0.9px; text-transform: uppercase; color: var(--label); font-weight: 700; text-shadow: var(--tshadow); }}
.basic .bpart svg {{ display: block; margin: 5px auto 3px; }}
.basic .bptemp {{ font-size: 22px; font-weight: 400; letter-spacing: -1px; text-shadow: var(--tshadow); }}
.basic .bppop {{ font-size: 11px; color: var(--blue); font-weight: 700; margin-top: 2px; }}

.basic .btiles {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 16px; }}
.basic .btile {{ background: var(--panel); background-image: var(--panel-img); border: var(--bw) solid var(--hair);
  border-radius: max(14px, var(--rad)); padding: 11px 13px; }}
.basic .blab {{ font-size: 9px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--label); font-weight: 700; }}
.basic .bval {{ font-size: 21px; font-weight: 400; margin-top: 3px; letter-spacing: -0.5px; text-shadow: var(--tshadow); }}
.basic .bunit {{ font-size: 11px; color: var(--muted); margin-left: 1px; letter-spacing: 0; }}
.basic .bsub {{ font-size: 10px; color: var(--muted); margin-top: 2px; }}

.basic .bradar {{ border: var(--bw) solid var(--hair); border-radius: max(14px, var(--rad)); overflow: hidden;
  height: 260px; margin-bottom: 16px; position: relative; background: var(--panel); }}

.basic .bdays {{ background: var(--panel); background-image: var(--panel-img); border: var(--bw) solid var(--hair);
  border-radius: max(14px, var(--rad)); padding: 4px 14px; }}
.basic .bday {{ padding: 11px 0 12px; border-bottom: 1px solid var(--hair); }}
.basic .bdmain {{ display: grid; grid-template-columns: 76px 34px 34px 34px 1fr 34px;
  align-items: center; gap: 6px; }}
.basic .bdsum {{ font-size: 11.5px; line-height: 1.4; color: var(--muted); margin-top: 6px; }}
.basic .bday:last-child {{ border-bottom: 0; }}
.basic .bdname {{ font-size: 13px; font-weight: 500; }}
.basic .bdpop {{ font-size: 10px; color: var(--blue); font-weight: 700; }}
.basic .bdlo {{ font-size: 14px; color: var(--muted); text-align: right; }}
.basic .bdhi {{ font-size: 14px; text-align: right; }}
.basic .bdtrack {{ position: relative; height: 5px; border-radius: 3px; background: var(--hair); }}
.basic .bdbar {{ position: absolute; top: 0; height: 100%; border-radius: 3px; }}
.basic .bddot {{ position: absolute; top: 50%; width: 7px; height: 7px; margin: -3.5px 0 0 -3.5px;
  border-radius: 50%; background: var(--fg); box-shadow: 0 0 0 2px var(--panel); }}

/* Night icons take their fill from the theme. The literal fill attribute in the
   SVG is the fallback; any CSS rule outranks a presentation attribute. */
.wxi .wxmoon {{ fill: var(--icon-moon, #E8DCC0); }}
.wxi .wxflake {{ fill: var(--icon-flake, #DCE7F2); }}
.wxi .wxfog {{ stroke: var(--icon-fog, #BFC7D2); }}

/* ---- retro flourishes -------------------------------------------------------- */
[data-theme="retro"] .wxi {{ filter: var(--icon-shadow); }}
[data-theme="retro"] .wxi circle, [data-theme="retro"] .wxi path {{
  stroke: var(--icon-stroke); stroke-width: 2.2; paint-order: stroke fill; }}
/* Retro legibility. Eleven size overrides used to live here compensating for
   Courier at 9-12px; the 4000 was never monospace, so dropping the monospace
   dropped the need for them. What remains is the rule that matters: running
   text comes off the yellow and onto white, because yellow is a label colour
   in this palette and a paragraph of it is unreadable. */
[data-theme="retro"] .basic .blab, [data-theme="retro"] .card .label,
[data-theme="retro"] .mini .label, [data-theme="retro"] .wstat .lab {{ font-size: 11.5px; letter-spacing: 0.4px; }}
[data-theme="retro"] .basic .bsub, [data-theme="retro"] .card .sub,
[data-theme="retro"] .wstat .sub2, [data-theme="retro"] .basic .bunit {{ font-size: 12px; color: var(--faint); letter-spacing: 0.2px; }}
[data-theme="retro"] .basic .bppop, [data-theme="retro"] .basic .bdpop {{ color: var(--blue); font-weight: 700; }}
[data-theme="retro"] .basic .bdsum {{ font-size: 12px; color: var(--faint); }}
[data-theme="retro"] .basic .bsec {{ color: var(--head-fg); letter-spacing: 1.2px; }}
[data-theme="retro"] .cap, [data-theme="retro"] .rosecap {{ font-size: 11.5px; letter-spacing: 0.2px;
  color: var(--faint); text-transform: none; }}
[data-theme="retro"] .basic .bdname, [data-theme="retro"] .basic .bplabel {{ text-transform: uppercase; }}
[data-theme="retro"] .basic .bdlo, [data-theme="retro"] .basic .bdhi,
[data-theme="retro"] .basic .bptemp, [data-theme="retro"] .basic .bval {{ font-weight: 700; }}
[data-theme="retro"] .basic .bdays .bday {{ border-bottom-color: rgba(255,255,255,0.28); }}
[data-theme="retro"] .radarbox, [data-theme="retro"] .basic .bradar {{ border-color: var(--line); }}
/* The view tabs fill with --head-fg (yellow) when selected; the sub-pills were
   filling with --fg (white), which is the same colour in light and dark and a
   different one here. Only retro separates those two tokens, so only retro
   showed the mismatch. */
[data-theme="retro"] .subtabbar button {{ background: rgba(255,255,255,0.16); color: var(--fg); }}
[data-theme="retro"] .subtabbar button[aria-selected="true"] {{
  background: var(--head-fg); color: var(--head-bg); }}

/* Radar was the one surface not derived from the palette -- desaturated to grey
   and tinted blue, which matched nothing. Hue-rotated onto the navy instead, and
   the echoes keep their own colours by being excluded from the basemap filter. */
[data-theme="retro"] .basetiles {{
  filter: grayscale(1) brightness(0.42) contrast(1.15) sepia(1) hue-rotate(185deg) saturate(3.2); }}

/* Scanlines. The 4000 was a CRT and the simulator ships this; at this opacity it
   reads as texture rather than as damage, and it is the cheapest thing on the
   page that says "television". */
[data-theme="retro"] body::after {{
  content: ""; position: fixed; inset: 0; z-index: 9999; pointer-events: none;
  background: repeating-linear-gradient(to bottom,
    transparent 0 1px, rgba(0,0,0,0.16) 1px 2px); }}
/* Light and dark unified on hairline borders; retro keeps its hard white frames,
   which together with the banded panels are most of what makes it read as retro. */
[data-theme="retro"] .card, [data-theme="retro"] .afd,
[data-theme="retro"] .chartbox {{ border-color: var(--line); }}
[data-theme="retro"] .hero {{ border-bottom: var(--rule-h) solid var(--line); }}

@media (max-width: 480px) {{
  .masthead h1 {{ font-size: 18px; letter-spacing: 1.5px; }}
  .masthead .sub {{ font-size: 8px; letter-spacing: 1px; }}
  main {{ padding: 14px 14px calc(14px + env(safe-area-inset-bottom)); }}
  .bigtemp {{ font-size: 54px; }}
  .bigtemp sup {{ font-size: 19px; }}
  .ministats {{ grid-template-columns: repeat(3, 1fr); gap: 6px 10px; min-width: 0; }}
  .mini .val {{ font-size: 16px; }}
  .windwrap {{ gap: 10px; }}
  .rosebox, .gaugebox {{ width: 47%; }}
  .windstats {{ flex-basis: 100%; gap: 7px 10px; }}
  .wstat .wval {{ font-size: 13.5px; }}
  .grid {{ grid-template-columns: 1fr 1fr; gap: 8px; }}
  .card {{ padding: 8px 10px; }}
  .card .val {{ font-size: 19px; }}
  .chartbox {{ height: 200px; padding: 8px; }}
  .basic .btemp {{ font-size: 62px; }}
  .basic .btiles {{ grid-template-columns: repeat(2, 1fr); }}
  .basic .bdmain {{ grid-template-columns: 58px 28px 30px 28px 1fr 30px; gap: 4px; }}
  .basic .bdsum {{ font-size: 11px; }}
  .basic .bradar {{ height: 220px; }}
  .tabbar button {{ font-size: 10px; letter-spacing: 0.8px; padding: 8px 8px; }}
}}
</style></head><body>
<div id="splash" aria-hidden="true">
  <img src="icon-192.png{ICON_V}" alt="" width="96" height="96">
  <div class="splash-name">{station_name}</div>
  <div class="splash-sub">Current Conditions</div>
</div>
<div class="masthead"><h1>{station_name}</h1>
<div class="sub">{location} &mdash; Elev. {elev} ft</div>
<div class="mastclock">{ts_time}</div>
<select id="themesel" class="themesel" aria-label="Theme">
  <option value="light">Light</option>
  <option value="dark">Dark</option>
  <option value="retro">Retro</option>
  <option value="paper">Paper</option>
  <option value="minimal">Minimal</option>
</select></div>
<nav class="tabbar" role="tablist" aria-label="View">
  <button id="mode-basic" role="tab" aria-selected="true">Current</button>
  <button id="mode-radar" role="tab" aria-selected="false">Radar</button>
  <button id="mode-detail" role="tab" aria-selected="false">Detailed</button>
  <button id="mode-afd" role="tab" aria-selected="false">Discussion</button>
</nav>
<div class="rule"></div>
<main>
{alert_html}

<div id="view-basic">{basic_html}</div>

<div id="view-radar" hidden>{radar_html}</div>

<div id="view-afd" hidden>{afd_html}</div>

<div id="view-detail" hidden>
<nav class="subtabbar" role="tablist" aria-label="Detailed section">
  <button id="sub-now" role="tab" aria-selected="true">Now</button>
  <button id="sub-24h" role="tab" aria-selected="false">24 Hours</button>
  <button id="sub-fc" role="tab" aria-selected="false">Forecast</button>
  <button id="sub-alm" role="tab" aria-selected="false">Almanac</button>
</nav>

<div id="pane-now">
<div class="hero">
  <div class="bigtemp">{round(d.get("tempf") or 0)}<sup>&deg;F</sup></div>
  <div class="ministats">
    <div class="mini"><div class="label">Feels</div><div class="val">{round(feels or 0)}&deg;</div></div>
    <div class="mini"><div class="label">Dew Point</div><div class="val">{round(d.get("dewPoint") or 0)}&deg;</div></div>
    <div class="mini"><div class="label">Humidity</div><div class="val">{round(d.get("humidity") or 0)}%</div></div>
    <div class="mini"><div class="label">24h Range</div><div class="val">{round(lo24) if lo24 is not None else "?"}&ndash;{round(hi24) if hi24 is not None else "?"}&deg;</div></div>
    <div class="mini"><div class="label">Inside</div><div class="val">{round(d.get("tempinf") or 0)}&deg;</div></div>
    <div class="mini"><div class="label">Inside RH</div><div class="val">{round(d.get("humidityin") or 0)}%</div></div>
  </div>
</div>

<h2>Wind <span class="accent">/</span> Now</h2>
<div class="windwrap">
  <div class="gaugebox"><div class="dialhead">Speed <span>/ Now</span></div>{gauge_svg}<div class="rosecap">band = current&mdash;&gt;gust &middot; <span class="sw-peak">tick</span> = today's peak</div></div>
  <div class="rosebox"><div class="dialhead">From <span>/ 24h</span></div>{rose_svg}<div class="rosecap">petals = wind origin &middot; calm {calm_pct}% of day</div></div>
  <div class="windstats">
    <div class="wstat"><div class="lab">Now</div><div class="wval">{esc(wind_now, 1)} mph {wdir}</div><div class="sub2">{beaufort(wind_now or 0)}</div></div>
    <div class="wstat"><div class="lab">Current / gust</div><div class="wval">{esc(wind_now, 1)} / {esc(gust_now, 1)} mph</div></div>
    <div class="wstat"><div class="lab">Today's peak gust</div><div class="wval">{esc(peak_today, 1)} mph</div>{run_sub}</div>
    <div class="wstat"><div class="lab">Biggest gust, 24h</div><div class="wval">{gust_line or "&mdash;"}</div></div>
  </div>
</div>
</div>

<div id="pane-24h" hidden>
<h2>Last 24 Hours <span class="accent">/</span> Temp &middot; Dew Point &middot; Humidity</h2>
{chart_fig("chart24", 190, '<span class="sw-temp">&#9644;</span> temp &nbsp;&middot;&nbsp; <span style="letter-spacing:-1px;">- - -</span> dew point &nbsp;&middot;&nbsp; <span class="sw-blue">&#9644;</span> RH % (right axis)')}

<h2>Wind <span class="accent">/</span> Last 24 Hours</h2>
{chart_fig("windchart", 190, '<span class="sw-temp">&#9644;</span> speed &nbsp;&middot;&nbsp; <span class="sw-gust">&#9644;</span> gust envelope &nbsp;&middot;&nbsp; arrows fly <b>with</b> the wind, coloured by speed', under=dir_strip)}

<h2>Rain <span class="accent">/</span> Last 24 Hours</h2>
{chart_fig("rainchart", 160, (f'{r24_total:.2f}&Prime; over {r24_wet} wet hour{"" if r24_wet == 1 else "s"}' if r24_total > 0 else 'no rain in the last 24 hours') + ' &middot; hourly totals, inches')}

<h2>Last 24 Hours <span class="accent">/</span> Pressure</h2>
{chart_fig("presschart", 160, 'relative pressure, inHg &middot; falling = weather coming, rising = clearing')}

</div>

<div id="pane-fc" hidden>
{fc_chart_html}
{('<h2>Forecast <span class="accent">/</span> 7 Days &middot; 3 Models</h2>'
  + chart_fig("fctemp", 210, '<span class="sw-temp">&#9644;</span> GFS &nbsp;&middot;&nbsp; <span class="sw-blue">&#9644;</span> ECMWF &nbsp;&middot;&nbsp; <span class="sw-m2">&#9644;</span> HRRR (48h) &nbsp;&middot;&nbsp; <span class="sw-blue">&#9646;&#9646;</span> precip (right axis)')
  + '<h2>Forecast <span class="accent">/</span> Wind</h2>'
  + chart_fig("fcwind", 180, gauge_cap if calibrated else 'mph &middot; dashed = raw models &middot; calibration pending &mdash; run calibrate.py once you have station history')) if has_forecast else ''}
{'<h2>Forecast <span class="accent">/</span> 7 Days</h2><div class="grid">' + fcast_cards + '</div>' if fcast_cards else ''}
</div>

<div id="pane-alm" hidden>
<h2>Rain <span class="accent">/</span> Sky</h2>
<div class="grid">
  <div class="card"><div class="label">Rain Today</div><div class="val">{esc(d.get("dailyrainin"), 2)}&Prime;</div><div class="sub">{storm_line}</div></div>
  <div class="card"><div class="label">Month to Date</div><div class="val">{esc(d.get("monthlyrainin"), 2)}&Prime;</div><div class="sub">{month_sub}</div></div>
  <div class="card"><div class="label">Year to Date</div><div class="val">{esc(d.get("yearlyrainin"), 2)}&Prime;</div><div class="sub">{ytd_sub}</div></div>
  <div class="card"><div class="label">Barometer</div><div class="val">{esc(d.get("baromrelin"), 2)}</div><div class="sub">{bar_words(None)}</div></div>
  <div class="card"><div class="label">Sun</div><div class="val" style="font-size:17px;">{sun_val2}</div><div class="sub">{sun_sub2}</div></div>
  <div class="card"><div class="label">Moon</div><div class="val">{moon_val}</div><div class="sub">{moon_sub}</div></div>
</div>

<h2>Last 30 Days <span class="accent">/</span> Temp &amp; Rain</h2>
{chart_fig("chart", 240, '<span class="sw-temp">&#9644;</span> daily high &nbsp;&middot;&nbsp; <span>&#9644;</span> daily low &nbsp;&middot;&nbsp; <span class="sw-blue">&#9646;&#9646;</span> rain')}
</div>
</div>

<div class="footer"><span class="badge">{station_name.upper()} <b>&#9733;</b> STATION BRIEF</span></div>
</main>
<script src="{A['chart_js']}"></script>
<script src="{A['leaflet_js']}"></script>
<script>
/* The Forecast tab's one chart. Separate from initCharts() so each tab builds
   its own on first show -- Chart.js measures the container at construction and a
   hidden one measures zero. */
// Mirrors a scrolling chart's y scales into the two pinned gutters beside it.
// Runs on every draw, so it survives resize, theme rebuilds and data changes.
var stickyAxes = {{
  id: "stickyaxes",
  afterDraw: function (chart) {{
    var wrap = chart.canvas.closest(".plotwrap");
    var ca = chart.chartArea;
    if (!wrap || !ca) return;
    var pairs = [[wrap.querySelector(".axgut-l"), chart.scales.y,
                  function (v) {{ return v + "\u00B0"; }}],
                 [wrap.querySelector(".axgut-r"), chart.scales.ypop,
                  function (v) {{ return v + "%"; }}]];
    pairs.forEach(function (pr) {{
      var el = pr[0], sc = pr[1], fmt = pr[2];
      if (!el || !sc) return;
      var html = "";
      sc.ticks.forEach(function (tk, i) {{
        var y = sc.getPixelForTick(i);
        if (y < ca.top - 6 || y > ca.bottom + 6) return;
        html += '<span style="top:' + y.toFixed(1) + 'px">' + fmt(tk.value) + '</span>';
      }});
      el.innerHTML = html;
    }});
  }}
}};

function initForecastChart() {{
  var el = document.getElementById("fc120");
  if (!el) return;
  // Must run before the dataset literals below are evaluated: it is what
  // defines window.S, which every series colour reads from.
  __chartDefaults();

  var NIGHTS = {f120_nights_js};
  var TIMES = {f120_times_js};
  /* Night is shaded rather than labelled: over five days the bands are what make
     the daily temperature rhythm legible at a glance. */
  var nightBands = {{
    id: "nightbands",
    beforeDatasetsDraw: function (chart) {{
      var ca = chart.chartArea, x = chart.scales.x, ctx = chart.ctx;
      if (!ca || !x) return;
      ctx.save();
      ctx.fillStyle = S.grid || "rgba(0,0,0,0.07)";
      ctx.globalAlpha = 0.5;
      NIGHTS.forEach(function (sp) {{
        var a = x.getPixelForValue(sp[0]), b = x.getPixelForValue(sp[1]);
        ctx.fillRect(a, ca.top, Math.max(1, b - a), ca.bottom - ca.top);
      }});
      ctx.restore();
    }}
  }};

  window.__charts.push(new Chart(el, {{
    data: {{
      labels: {f120_labels_js},
      datasets: [
        {{ type: "line", label: "Chance of precip %", data: {f120_pop_js},
           borderColor: S.blue, backgroundColor: S.blueFill,
           fill: "origin", tension: 0.25, pointRadius: 0, borderWidth: 1.5, yAxisID: "ypop" }},
        {{ type: "line", label: "Temp °F", data: {f120_temp_js},
           borderColor: S.temp, backgroundColor: S.temp,
           tension: 0.35, pointRadius: 0, borderWidth: 2.5, yAxisID: "y" }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      // Keeps the plot clear of the pinned gutters at scroll offset 0.
      layout: {{ padding: {{ left: 42, right: 42 }} }},
      interaction: {{ mode: "index", intersect: false }},
      scales: {{
        // Tick text off: the pinned gutters draw it. Gridlines stay, and the
        // scales are zero-width so the plot uses the full scrolling canvas.
        y: {{ position: "left", grid: {{ color: S.grid }}, ticks: {{ display: false }},
             afterFit: function (sc) {{ sc.width = 0; }} }},
        ypop: {{ position: "right", min: 0, max: 100, ticks: {{ display: false, stepSize: 25 }},
                grid: {{ drawOnChartArea: false }}, afterFit: function (sc) {{ sc.width = 0; }} }},
        x: {{ ticks: {{ autoSkip: false, maxRotation: 0,
             callback: function (v) {{ var l = this.getLabelForValue(v); return l || null; }},
             font: __dayFont }}, grid: {{ display: false }} }}
      }},
      plugins: {{ legend: {{ display: false }},
                 tooltip: {{ callbacks: {{ title: function (items) {{
                   // The axis labels are mostly blank by design, so the tooltip
                   // carries the full timestamp instead.
                   return items.length ? (TIMES[items[0].dataIndex] || "") : ""; }} }} }} }}
    }},
    plugins: [nightBands, stickyAxes]
  }}));
}}
/* Chart.js bakes colours in at construction, so a theme change rebuilds rather
   than restyles; every instance is kept so it can be destroyed first.

   Split one function per Detailed sub-pane. A chart constructed inside a hidden
   pane measures its container as zero, so each pane builds its own the first
   time it is shown. */
function __chartDefaults() {{
  window.__charts = window.__charts || [];
  const css = getComputedStyle(document.documentElement);
  Chart.defaults.color = css.getPropertyValue('--chart-ink').trim();
  Chart.defaults.borderColor = css.getPropertyValue('--chart-grid').trim();
  Chart.defaults.font.family = css.getPropertyValue('--font').trim();
  const t = function (n) {{ return css.getPropertyValue(n).trim(); }};
  // Every series colour comes from a token, so a theme change repaints the
  // charts along with everything else rather than leaving them orange.
  window.S = {{
    temp: t('--s-temp'), tempFill: t('--s-temp-fill'), ink: t('--s-ink'),
    blue: t('--s-blue'), blueSolid: t('--s-blue-solid'), blueFill: t('--s-blue-fill'),
    bar: t('--s-bar'), gust: t('--s-gust'), gustFill: t('--s-gust-fill'),
    grid: t('--chart-grid'),
    m: [t('--s-model-0'), t('--s-model-1'), t('--s-model-2')]
  }};
}}
function __mkChart(el, cfg) {{ const c = new Chart(el, cfg); window.__charts.push(c); return c; }}
// Day names bold, clock times light, so an axis reads as days first.
//
// Reads c.tick.label, NOT c.chart.data.labels[c.index]. Chart.js drops any tick
// whose callback returned null, so on the 120-hour axis 120 labels become ~20
// ticks and c.index indexes the survivors -- data.labels[6] is "12p" where
// tick 6 is actually "6p". Indexing the data was silently testing the wrong
// string for every tick.
function __dayFont(c) {{
  var l = (c.tick && c.tick.label) || "";
  return {{ size: 10, weight: /^[A-Za-z]+$/.test(l) ? 700 : 400 }};
}}
// Model lines are drawn solid, dimmed and ghosted from the same token, so a
// theme only has to state three colours rather than nine.
function __RGBA(i, a) {{
  var c = (window.S && S.m[i]) || "#888888";
  if (c.charAt(0) !== "#") return c;
  return "rgba(" + parseInt(c.substr(1,2),16) + "," + parseInt(c.substr(3,2),16)
       + "," + parseInt(c.substr(5,2),16) + "," + a + ")";
}}

function initChartsFc() {{
  __chartDefaults();
if (document.getElementById("fctemp")) {{
__mkChart(document.getElementById("fctemp"), {{
  data: {{
    labels: {f48_labels},
    datasets: [{f48_temp_ds},
      {{ type: "bar", label: "Precip", data: {f48_precip}, backgroundColor: S.bar, yAxisID: "y1" }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      y: {{ position: "left", grid: {{ color: S.grid }} }},
      y1: {{ position: "right", beginAtZero: true, suggestedMax: 0.5, grid: {{ drawOnChartArea: false }}, ticks: {{ font: {{ size: 9 }} }} }},
      x: {{ ticks: {{ autoSkip: false, maxRotation: 0, callback: function(v) {{ var l = this.getLabelForValue(v); return l || null; }}, font: __dayFont }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});
__mkChart(document.getElementById("fcwind"), {{
  data: {{
    labels: {f48_labels},
    datasets: [{f48_wind_ds}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      y: {{ beginAtZero: true, grid: {{ color: S.grid }} }},
      x: {{ ticks: {{ autoSkip: false, maxRotation: 0, callback: function(v) {{ var l = this.getLabelForValue(v); return l || null; }}, font: __dayFont }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});
}}
}}

function initCharts24() {{
  __chartDefaults();
/* One axis, mph. Direction used to ride a second 0-360 axis on this same plot;
   it is an arrow strip under the canvas now, padded to the plot area so each
   arrow lines up with the hour above it. */
var alignDirStrip = {{
  id: "aligndir",
  afterDraw: function (chart) {{
    var strip = document.querySelector(".dirstrip");
    var ca = chart.chartArea;
    if (!strip || !ca) return;
    strip.style.paddingLeft = ca.left + "px";
    strip.style.paddingRight = (chart.width - ca.right) + "px";
  }}
}};
__mkChart(document.getElementById("windchart"), {{
  data: {{
    labels: {w24_labels},
    datasets: [
      {{ type: "line", label: "Gust", data: {w24_gust}, borderColor: S.gust, backgroundColor: S.gustFill, tension: 0.3, pointRadius: 0, borderWidth: 1, fill: "origin" }},
      {{ type: "line", label: "Speed", data: {w24_avg}, borderColor: S.temp, backgroundColor: S.tempFill, tension: 0.3, pointRadius: 0, borderWidth: 2.5, fill: "origin" }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: "index", intersect: false }},
    scales: {{
      y: {{ beginAtZero: true, grid: {{ color: S.grid }}, title: {{ display: true, text: "mph", font: {{ size: 9 }} }} }},
      x: {{ ticks: {{ autoSkip: false, maxRotation: 0, callback: function(v, i) {{ var l = this.getLabelForValue(v); return l || null; }} }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }},
  plugins: [alignDirStrip]
}});
__mkChart(document.getElementById("rainchart"), {{
  type: "bar",
  data: {{
    labels: {r24_labels},
    datasets: [
      {{ label: "Rain (in)", data: {r24_rain}, backgroundColor: S.bar, borderRadius: 4, borderSkipped: false, barPercentage: 0.82, categoryPercentage: 0.94 }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: "index", intersect: false }},
    scales: {{
      y: {{ beginAtZero: true, suggestedMax: 0.1, grid: {{ color: S.grid }},
           ticks: {{ callback: function(v) {{ return v.toFixed(2); }}, font: {{ size: 9 }} }} }},
      x: {{ ticks: {{ autoSkip: false, maxRotation: 0, callback: function(v) {{ var l = this.getLabelForValue(v); return l || null; }}, font: __dayFont }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ display: false }},
               tooltip: {{ callbacks: {{ label: function (c) {{ return c.parsed.y.toFixed(2) + '"'; }} }} }} }}
  }}
}});
__mkChart(document.getElementById("presschart"), {{
  type: "line",
  data: {{
    labels: {p24_labels},
    datasets: [
      {{ label: "inHg", data: {p24_bar}, borderColor: S.ink, backgroundColor: S.ink, tension: 0.35, pointRadius: 0, borderWidth: 2.5 }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      y: {{ grid: {{ color: S.grid }}, ticks: {{ callback: function(v) {{ return v.toFixed(2); }} }} }},
      x: {{ ticks: {{ autoSkip: false, maxRotation: 0, callback: function(v, i) {{ var l = this.getLabelForValue(v); return l || null; }} }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});
__mkChart(document.getElementById("chart24"), {{
  type: "line",
  data: {{
    labels: {t24_labels},
    datasets: [
      {{ label: "Temp °F", data: {t24_temp}, borderColor: S.temp, backgroundColor: S.temp, tension: 0.35, pointRadius: 0, borderWidth: 3, yAxisID: "y" }},
      {{ label: "Dew point °F", data: {t24_dew}, borderColor: S.ink, backgroundColor: S.ink, borderDash: [6, 4], tension: 0.35, pointRadius: 0, borderWidth: 2, yAxisID: "y" }},
      {{ label: "RH %", data: {t24_rh}, borderColor: S.blue, backgroundColor: S.blue, tension: 0.35, pointRadius: 0, borderWidth: 1.5, yAxisID: "yrh" }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      y: {{ position: "left", grid: {{ color: S.grid }} }},
      yrh: {{ position: "right", min: 0, max: 100, ticks: {{ stepSize: 25, callback: function(v) {{ return v + "%"; }}, font: {{ size: 9 }} }}, grid: {{ drawOnChartArea: false }} }},
      x: {{ ticks: {{ autoSkip: false, maxRotation: 0, callback: function(v, i) {{ var l = this.getLabelForValue(v); return l || null; }} }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});
}}

function initChartsAlm() {{
  __chartDefaults();
__mkChart(document.getElementById("chart"), {{
  data: {{
    labels: {labels},
    datasets: [
      {{ type: "line", label: "High °F", data: {highs}, borderColor: S.temp, backgroundColor: S.temp, tension: 0.3, pointRadius: 0, borderWidth: 3, yAxisID: "y" }},
      {{ type: "line", label: "Low °F", data: {lows}, borderColor: S.blueSolid, backgroundColor: S.blueSolid, tension: 0.3, pointRadius: 0, borderWidth: 3, yAxisID: "y" }},
      {{ type: "bar", label: "Rain (in)", data: {rain30}, backgroundColor: S.bar, yAxisID: "y1" }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      y: {{ position: "left", grid: {{ color: S.grid }} }},
      y1: {{ position: "right", beginAtZero: true, suggestedMax: 1.5, grid: {{ drawOnChartArea: false }} }},
      x: {{ ticks: {{ maxTicksLimit: 10 }}, grid: {{ display: false }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});
}}
</script>
<script>
function initRadar() {{
(async () => {{
  const map = L.map("radarmap", {{ zoomControl: false, attributionControl: false }}).setView([{lat}, {lon}], 7);
  const tok = function (n) {{ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }};
  // Basemap follows the theme. Retro reuses the dark tiles and tints them blue in
  // CSS -- CARTO has no retro basemap and a filter is closer than any of them.
  const BASE = {{ light: "light_all", dark: "dark_all", retro: "light_all" }};
  function baseUrl() {{
    const t = document.documentElement.getAttribute("data-theme") || "light";
    return "https://{{s}}.basemaps.cartocdn.com/" + (BASE[t] || "light_all") + "/{{z}}/{{x}}/{{y}}{{r}}.png";
  }}
  const baseLayer = L.tileLayer(baseUrl(), {{ maxZoom: 10, className: "basetiles" }}).addTo(map);
  const mk = L.circleMarker([{lat}, {lon}], {{ radius: 6, color: tok("--panel"), weight: 2, fillColor: tok("--accent"), fillOpacity: 1 }})
    .bindTooltip("{station_name}").addTo(map);
  window.__radar = {{ map: map, base: baseLayer, baseUrl: baseUrl, marker: mk, tok: tok }};
  const locBtn = document.getElementById("radarlocate");
  if (locBtn) locBtn.addEventListener("click", () => {{
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(pos => {{
      const {{ latitude: yla, longitude: ylo }} = pos.coords;
      L.circleMarker([yla, ylo], {{ radius: 5, color: tok("--panel"), weight: 2, fillColor: tok("--blue"), fillOpacity: 1 }})
        .bindTooltip("You").addTo(map);
      map.panTo([yla, ylo]);
      locBtn.style.color = tok("--blue");
    }}, () => {{}}, {{ timeout: 8000 }});
  }});
  fetch("https://api.weather.gov/alerts/active?point={lat},{lon}&status=actual")
    .then(r => r.json())
    .then(aj => {{
      const feats = (aj.features || []).filter(f => f.geometry);
      if (feats.length) L.geoJSON({{ type: "FeatureCollection", features: feats }}, {{
        style: f => ({{ color: /Tornado|Severe/.test(f.properties.event) ? "#C93A2E" : "#F3A83B",
                       weight: 2, fillOpacity: 0.08 }})
      }}).addTo(map);
    }}).catch(() => {{}});
  fetch("https://mesonet.agron.iastate.edu/geojson/nexrad_attr.geojson")
    .then(r => r.json())
    .then(aj => {{
      const bb = map.getBounds().pad(0.25);
      (aj.features || []).forEach(f => {{
        const [lon, lat] = f.geometry.coordinates;
        if (!bb.contains([lat, lon])) return;
        const p = f.properties;
        const severe = p.tvs !== "NONE" || p.posh >= 50 || p.max_dbz >= 60;
        const notable = p.meso !== "NONE" || p.max_dbz >= 50;
        const col = severe ? "#C93A2E" : (notable ? "#EE8434" : "#F5C63C");
        L.circleMarker([lat, lon], {{ radius: 4.5, color: "#111", weight: 1.5, fillColor: col, fillOpacity: 1, zIndex: 900 }})
          .bindTooltip(p.nexrad + " " + p.storm_id + " &middot; " + p.max_dbz + " dBZ &middot; " + Math.round(p.sknt * 1.15) + " mph"
            + (p.tvs !== "NONE" ? " &middot; TVS" : "") + (p.meso !== "NONE" ? " &middot; MESO" : "")).addTo(map);
        if (p.sknt > 2) {{
          const brg = ((p.drct + 180) % 360) * Math.PI / 180;
          const pts = [[lat, lon]];
          for (let mins = 15; mins <= 60; mins += 15) {{
            const km = p.sknt * 1.852 * mins / 60;
            const la = lat + km / 111 * Math.cos(brg);
            const lo = lon + km / (111 * Math.cos(lat * Math.PI / 180)) * Math.sin(brg);
            pts.push([la, lo]);
            L.circleMarker([la, lo], {{ radius: 1.6, color: col, weight: 1, fillColor: col, fillOpacity: 1 }}).addTo(map);
          }}
          L.polyline(pts, {{ color: col, weight: 1.5, opacity: 0.85, dashArray: "4,3" }}).addTo(map);
        }}
      }});
    }}).catch(() => {{}});
  try {{
    const offs = [50, 45, 40, 35, 30, 25, 20, 15, 10, 5, 0];
    const layers = offs.map(m => L.tileLayer(
      "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913" + (m ? "-m" + String(m).padStart(2, "0") + "m" : "") + "/{{z}}/{{x}}/{{y}}.png",
      {{ opacity: 0, zIndex: 5, maxZoom: 10, className: "radartiles" }}).addTo(map));
    let cur = 0, paused = false;
    const btn = document.getElementById("radarplay");
    const sl = document.getElementById("radarslider");
    const ticks = document.getElementById("radarticks");
    const stamp = document.getElementById("radarstamp");
    const lab = document.getElementById("radartime");
    if (sl) sl.max = String(layers.length - 1);

    // Offsets are minutes behind the wall clock, so the clock is read per frame
    // rather than anchored once at load -- this page can sit open a long while.
    const frameTime = i => new Date(Date.now() - offs[i] * 60000);
    const hhmm = t => t.toLocaleTimeString("en-US", {{ hour: "numeric", minute: "2-digit" }});
    const stampOf = i => hhmm(frameTime(i)) + (offs[i] === 0 ? " (now)" : "");

    function drawTicks() {{
      if (!ticks) return;
      ticks.innerHTML = "";
      [0, (layers.length - 1) >> 1, layers.length - 1].forEach(i => {{
        const sp = document.createElement("span");
        sp.textContent = offs[i] === 0 ? "Now" : hhmm(frameTime(i));
        ticks.appendChild(sp);
      }});
    }}

    function paint() {{
      const ts = stampOf(cur);
      if (lab) lab.textContent = ts;
      if (stamp) stamp.innerHTML = "RADAR &middot; <b>" + ts + "</b>";
      if (!sl) return;
      sl.value = String(cur);
      // The filled portion of the track is painted in, since a range input gives
      // no way to style the two sides of the thumb differently.
      const pct = layers.length > 1 ? (cur / (layers.length - 1)) * 100 : 100;
      sl.style.background = "linear-gradient(90deg, var(--overlay-fg) " + pct
        + "%, rgba(255,255,255,0.28) " + pct + "%)";
    }}

    function show(i) {{
      layers[cur].setOpacity(0);
      cur = ((i % layers.length) + layers.length) % layers.length;
      layers[cur].setOpacity(0.78);
      // Wrapping is the cheapest moment to re-label the ticks, which have drifted
      // by one frame's worth of wall clock since the last pass.
      if (cur === 0) drawTicks();
      paint();
    }}

    function setPaused(p) {{
      paused = p;
      btn.innerHTML = paused ? "&#9654;" : "&#10074;&#10074;";
      btn.setAttribute("aria-label", paused ? "Play the radar loop" : "Pause the radar loop");
    }}

    btn.addEventListener("click", () => setPaused(!paused));
    // Scrubbing takes over the loop: dragging pauses, and playback resumes only on
    // the play button. Arrow keys reach this too, since it is a real range input.
    if (sl) sl.addEventListener("input", () => {{ setPaused(true); show(parseInt(sl.value, 10)); }});

    layers[0].setOpacity(0.78);
    drawTicks();
    paint();
    setPaused(false);
    setInterval(() => {{ if (!paused) show(cur + 1); }}, 650);
  }} catch (e) {{
    document.getElementById("radartime").textContent = "radar feed unavailable";
  }}
}})();
}}
</script>
{theme_js}
{MODE_JS}
{REFRESH_JS}
{SPLASH_JS}</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # PWA shell, written beside the page so Add-to-Home-Screen yields a real icon
    # and a standalone window rather than a browser screenshot.
    (OUT.parent / "manifest.webmanifest").write_text(json.dumps({
        "name": f"{station_name} Live",
        "short_name": station_name,
        "start_url": ".",
        "scope": ".",
        "display": "standalone",
        # Matches the default (light) chrome; the running page updates theme-color
        # live when the theme changes, but a manifest can only declare one.
        "background_color": "#FFFFFF",
        "theme_color": "#FFFFFF",
        "icons": [
            {"src": f"icon-192.png{ICON_V}", "sizes": "192x192", "type": "image/png"},
            {"src": f"icon-512.png{ICON_V}", "sizes": "512x512", "type": "image/png"},
            {"src": f"icon-512.png{ICON_V}", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }, indent=2))
    icons.write_icons(OUT.parent)

    OUT.write_text(html)
    write_weather_json(d, fc)


if __name__ == "__main__":
    main()
