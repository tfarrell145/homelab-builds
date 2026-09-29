#!/usr/bin/env python3
"""The "Basic" view -- an at-a-glance screen in the register of a phone weather app.

Everything here is derived from the NWS hourly forecast (real NOAA wording, not a
model re-description) folded into four named parts of the day, plus current
observations from the station itself.

The instrument-panel view lives in render.py and is unchanged; this is the other
half of the toggle.
"""
from datetime import datetime, timedelta
from html import escape

import wxicons

# Local hour ranges. Overnight wraps past midnight and is handled as a special case.
PARTS = [
    ("Morning",   6, 12, True),
    ("Afternoon", 12, 18, True),
    ("Evening",   18, 22, False),
    ("Overnight", 22, 6, False),
]

# Used only to break ties when one block contains several conditions equally often.
SEVERITY = {"thunder": 6, "snow": 5, "sleet": 5, "rain": 4, "sun_rain": 3,
            "moon_rain": 3, "fog": 3, "cloud": 2, "sun_cloud": 1,
            "moon_cloud": 1, "sun": 0, "moon": 0}


def _part_of(dt):
    h = dt.hour
    for name, a, b, is_day in PARTS:
        if name == "Overnight":
            continue
        if a <= h < b:
            return name, is_day
    return "Overnight", False


def _block_key(dt):
    """(date, part) identifying the block an hour belongs to.

    Hours after midnight belong to the previous day's Overnight, so that "Overnight"
    reads as one continuous night rather than splitting at 00:00.
    """
    name, _ = _part_of(dt)
    d = dt.date()
    if name == "Overnight" and dt.hour < 6:
        d = (dt - timedelta(days=1)).date()
    return d, name


def _label(d, part, today):
    delta = (d - today).days
    if delta == 0:
        return {"Morning": "This Morning", "Afternoon": "This Afternoon",
                "Evening": "This Evening", "Overnight": "Tonight"}[part]
    if delta == 1:
        return "Tomorrow " + part if part != "Overnight" else "Tomorrow Night"
    return d.strftime("%a ") + part


# Four blocks across a phone gives each cell about 88px. "Tomorrow Morning" wraps to
# two lines there and hands back the height the compact row just saved, so the tiles
# carry an abbreviation and the full wording moves to the title attribute.
_SHORT_PART = {"Morning": "AM", "Afternoon": "PM", "Evening": "Eve", "Overnight": "Night"}


def _short_label(d, part, today):
    delta = (d - today).days
    if delta == 0:
        return {"Morning": "Morning", "Afternoon": "Afternoon",
                "Evening": "Evening", "Overnight": "Tonight"}[part]
    prefix = "Tmrw" if delta == 1 else d.strftime("%a")
    return prefix + " " + _SHORT_PART[part]


def day_parts(hourly, now, limit=4, is_daylight=None):
    """Fold NWS hourly periods into upcoming named blocks.

    is_daylight: optional callable(datetime) -> bool, used to pick sun vs moon
    icons from real sunrise/sunset rather than a fixed clock split.
    """
    buckets = {}
    for p in hourly:
        try:
            dt = datetime.fromisoformat(p["startTime"])
        except (ValueError, KeyError):
            continue
        if dt < now - timedelta(minutes=59):
            continue
        key = _block_key(dt)
        buckets.setdefault(key, []).append((dt, p))

    out = []
    today = now.date()
    for (d, part) in sorted(buckets, key=lambda k: (k[0], [x[0] for x in PARTS].index(k[1]))):
        hrs = buckets[(d, part)]
        if len(hrs) < 2:            # a block we have only the tail end of
            continue
        temps = [p["temperature"] for _, p in hrs if p.get("temperature") is not None]
        pops = [(p.get("probabilityOfPrecipitation") or {}).get("value") or 0 for _, p in hrs]
        # Daylight from real solar times, not a clock convention. NWS's own isDaytime
        # flag splits at 06:00/18:00 regardless of season, which would hang a moon on
        # "This Evening" while it is still broad daylight in August.
        mid_dt = hrs[len(hrs) // 2][0]
        is_day = is_daylight(mid_dt) if is_daylight else _part_of(mid_dt)[1]

        counts = {}
        for _, p in hrs:
            counts[p["shortForecast"]] = counts.get(p["shortForecast"], 0) + 1
        # Most frequent wording wins; ties go to the more significant weather.
        short = max(counts, key=lambda s: (counts[s], SEVERITY.get(wxicons.classify(s, is_day), 0)))

        winds = []
        for _, p in hrs:
            try:
                winds.append(int(str(p.get("windSpeed", "0")).split()[0]))
            except (ValueError, IndexError):
                pass
        dirs = [p.get("windDirection") for _, p in hrs if p.get("windDirection")]

        out.append({
            "label": _label(d, part, today),
            "short_label": _short_label(d, part, today),
            "part": part,
            "icon": wxicons.classify(short, is_day),
            "short": short,
            "hi": max(temps) if temps else None,
            "lo": min(temps) if temps else None,
            "pop": max(pops) if pops else 0,
            # Daytime blocks are described by their high, night blocks by their low.
            "headline": (max(temps) if is_day else min(temps)) if temps else None,
            "wind": round(sum(winds) / len(winds)) if winds else None,
            "dir": max(set(dirs), key=dirs.count) if dirs else "",
        })
        if len(out) >= limit:
            break
    return out


def hourly_strip(hourly, now, limit=12, is_daylight=None):
    """The next N hours, one card each, straight from the NWS hourly periods.

    The day-part blocks answer "what is this evening like"; this answers "what is
    happening at 9pm", which is exactly the resolution the blocks throw away.
    """
    out = []
    for p in hourly:
        try:
            dt = datetime.fromisoformat(p["startTime"])
        except (ValueError, KeyError):
            continue
        if dt < now - timedelta(minutes=59):
            continue
        short = p.get("shortForecast", "")
        is_day = is_daylight(dt) if is_daylight else _part_of(dt)[1]
        out.append({
            # The hour already underway is "Now" rather than a time that has passed.
            "hour": "Now" if not out and dt <= now else dt.strftime("%-I%p").lower(),
            "temp": p.get("temperature"),
            "icon": wxicons.classify(short, is_day),
            "short": short,
            "pop": (p.get("probabilityOfPrecipitation") or {}).get("value") or 0,
        })
        if len(out) >= limit:
            break
    return out


def hours_fragment(hours):
    """The hourly cards -- a horizontal scroller, so the count can grow freely."""
    return "".join(
        f'<div class="bhr" title="{escape(h["short"])}">'
        f'<div class="bhrlab">{escape(h["hour"])}</div>'
        f'{wxicons.svg(h["icon"], 28)}'
        f'<div class="bhrpop">{str(h["pop"]) + "%" if h["pop"] >= 15 else "&nbsp;"}</div>'
        f'<div class="bhrtemp">{h["temp"] if h["temp"] is not None else "&mdash;"}&deg;</div>'
        f'</div>'
        for h in hours)


def daily_strip(periods, limit=5, today=None, today_hi=None, today_lo=None):
    """Pair the NWS day/night periods into per-day rows.

    today_hi/today_lo backfill the current day once NWS has dropped its daytime
    period, which otherwise leaves the first row with an em-dash and no bar for the
    last hours of every day.
    """
    days = {}
    for p in periods:
        row = days.setdefault(p["date"], {"date": p["date"]})
        if p["day"]:
            row["hi"] = p["temp"]
            row["short"] = p["short"]
            row["pop"] = p.get("pop") or 0
            row["summary"] = summarize(p.get("detailed", ""))
        else:
            row["lo"] = p["temp"]
            row.setdefault("short", p["short"])
            row["pop"] = max(row.get("pop") or 0, p.get("pop") or 0)
            # Late in the day the daytime period is gone, so fall back to tonight's.
            row.setdefault("summary", summarize(p.get("detailed", "")))
    if today is not None and today in days:
        r = days[today]
        if r.get("hi") is None and today_hi is not None:
            r["hi"] = today_hi
        if r.get("lo") is None and today_lo is not None:
            r["lo"] = today_lo

    out = []
    for k in sorted(days):
        r = days[k]
        if r.get("hi") is None and r.get("lo") is None:
            continue
        r["icon"] = wxicons.classify(r.get("short", ""), True)
        out.append(r)
    return out[:limit]


def parts_fragment(parts):
    """The day-part strip on its own -- Basic and the Radar tab both use it.

    A bare four-across row of label / icon / temperature / chance, sized to sit
    between the hero temperature and the feels line. The NWS wording ("Mostly
    Cloudy") used to have its own line here; the icon already carries it, and the
    line reserved 26px of height whether or not there was anything to say. It
    survives as the tile's tooltip together with the unabbreviated label.
    """
    return "".join(
        f'<div class="bpart" title="{escape(p["label"])} &mdash; {escape(p["short"])}">'
        f'<div class="bplabel">{escape(p.get("short_label") or p["label"])}</div>'
        f'{wxicons.svg(p["icon"], 34)}'
        f'<div class="bptemp">{p["headline"] if p["headline"] is not None else "&mdash;"}&deg;</div>'
        f'<div class="bppop">{str(p["pop"]) + "%" if p["pop"] >= 15 else "&nbsp;"}</div>'
        f'</div>'
        for p in parts)


# The one radar map. It used to be built inside Detailed and re-parented into
# whichever view was showing; Detailed no longer carries a radar section, so the
# block simply lives here. The wrapping slot div stays because the mode script
# still hands Leaflet an invalidateSize() after a theme change.
RADAR_BLOCK = (
    '<div id="radar-slot-radar"><div class="radarbox" id="radarblock">'
    '<div id="radarmap"></div>'
    '<div class="radarstamp" id="radarstamp">RADAR &middot; <b>&hellip;</b></div>'
    '<div class="radarplay" id="radarlocate">&#8982;</div>'
    '<div class="radarbar" id="radarbar">'
    '<button class="rbplay" id="radarplay" aria-label="Pause the radar loop">'
    '&#10074;&#10074;</button>'
    '<div class="rbtrack">'
    '<input type="range" id="radarslider" min="0" max="10" step="1" value="0" '
    'aria-label="Radar frame time">'
    '<div class="rbticks" id="radarticks"></div>'
    '</div></div></div></div>')

RADAR_CAP = (
    '<div class="cap" style="margin: 8px 0 14px;">NEXRAD composite &middot; last hour, '
    'scrub or pause with the slider &middot; <span style="color:#F3A83B;">boxes</span> '
    '= NWS warnings &middot; <span style="color:#F3A83B;">&#9679;&mdash;</span> storm '
    'cells with 1-hr track (ticks = 15 min) &middot; <span id="radartime">&hellip;</span> '
    '&middot; map &copy; OSM/CARTO, radar NOAA/IEM</div>')


def radar_tab(parts):
    """Radar tab: the map at full height, the same forecast blocks beneath it."""
    return (f'<div class="basic radartab">'
            f'<div class="chartfig">{RADAR_BLOCK}{RADAR_CAP}</div>'
            f'<div class="bparts">{parts_fragment(parts)}</div>'
            f'</div>')


# Temperature -> colour, for the forecast range bars. Cool blues through teal and
# green into yellow, orange and red, so a bar's colour says roughly how warm it is
# without reading the numbers. Interpolated between these stops.
TEMP_STOPS = [(20, (124, 156, 232)), (32, (87, 182, 224)), (42, (70, 195, 184)),
              (52, (127, 207, 114)), (62, (227, 209, 79)), (72, (240, 163, 60)),
              (82, (232, 112, 58)), (95, (217, 65, 65))]


# Sentences in NWS detailedForecast that only restate what the row already shows.
_DROP_SENTENCE = ("chance of precipitation is", "new rainfall amounts",
                  "new snowfall amounts", "new ice accumulation",
                  "new precipitation amounts")


def summarize(detailed, limit=125):
    """Trim an NWS detailedForecast down to a one-line row summary.

    Drops the sentences that duplicate the numbers already on the row (PoP,
    accumulation), then clips to whole sentences where it can and a word boundary
    where it cannot.
    """
    if not detailed:
        return ""
    parts, buf = [], ""
    for ch in detailed:
        buf += ch
        if ch == "." and len(buf) > 1:
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())

    keep = [x for x in parts if not any(x.lower().startswith(d) for d in _DROP_SENTENCE)]
    if not keep:
        keep = parts

    out = ""
    for sent in keep:
        cand = (out + " " + sent).strip()
        if len(cand) > limit:
            break
        out = cand
    if not out:                       # a single sentence longer than the limit
        out = keep[0]
        if len(out) > limit:
            out = out[:limit].rsplit(" ", 1)[0].rstrip(",;") + "\u2026"
    return out


def temp_color(f):
    if f is None:
        return "#9AA3AE"
    if f <= TEMP_STOPS[0][0]:
        return "#%02X%02X%02X" % TEMP_STOPS[0][1]
    if f >= TEMP_STOPS[-1][0]:
        return "#%02X%02X%02X" % TEMP_STOPS[-1][1]
    for (a, ca), (b, cb) in zip(TEMP_STOPS, TEMP_STOPS[1:]):
        if a <= f <= b:
            t = (f - a) / (b - a)
            return "#%02X%02X%02X" % tuple(
                round(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))
    return "#9AA3AE"


def _tile(label, value, sub=""):
    sub_html = f'<div class="bsub">{escape(sub)}</div>' if sub else ""
    return (f'<div class="btile"><div class="blab">{escape(label)}</div>'
            f'<div class="bval">{value}</div>{sub_html}</div>')


def build(now_temp, feels, cond_short, cond_is_day, today_hi, today_lo, parts,
          days, tiles, alerts, when="", hours=None):
    """Assemble the Basic view fragment."""
    icon = wxicons.classify(cond_short, cond_is_day)

    alert_html = ""
    if alerts:
        items = "".join(f'<div class="balert">{escape(a["event"])}</div>' for a in alerts[:3])
        alert_html = f'<div class="balerts">{items}</div>'

    part_html = parts_fragment(parts)
    hours_html = hours_fragment(hours or [])

    day_html = days_fragment(days, now_temp)

    tile_html = "".join(_tile(*t) for t in tiles)

    hours_section = (f'<section class="bsection">'
                     f'<h3 class="bsec">Hourly</h3>'
                     f'<div class="bhours">{hours_html}</div>'
                     f'</section>') if hours_html else ""

    # Order is what gets used most, soonest, with the least scrolling. The compact
    # day-part row rides directly under the hero as an extension of it: four blocks
    # of where today is going, at a size between the hero temperature and its feels
    # line. Then the five-day strip, the hourly detail, and the station's own
    # instruments last, since those are the numbers you go looking for rather than
    # glance at. The five-day strip is also the head of the Forecast tab -- same
    # fragment, two places, deliberately.
    return f'''<div class="basic">
{alert_html}
  <div class="bhero">
    <div class="bicon">{wxicons.svg(icon, 92)}</div>
    <div class="bnow">
      <div class="bwhen">{escape(when)}</div>
      <div class="btemp">{now_temp}<sup>&deg;</sup></div>
      <div class="bcond">{escape(cond_short)}</div>
      <div class="bmeta">Feels {feels}&deg; &middot; H:{today_hi}&deg; L:{today_lo}&deg;</div>
    </div>
  </div>
  <section class="bsection">
    <h3 class="bsec">Next 24 Hours</h3>
    <div class="bparts">{part_html}</div>
  </section>
  <section class="bsection">
    <h3 class="bsec">5-Day Forecast</h3>
    <div class="bdays">{day_html}</div>
  </section>
  {hours_section}
  <section class="bsection">
    <h3 class="bsec">Current Conditions</h3>
    <div class="btiles">{tile_html}</div>
  </section>
</div>'''


def days_fragment(days, now_temp=None):
    """The five-day rows on their own -- Basic and the Forecast tab both use it."""
    # One temperature scale shared by every row, so bar position and length are
    # comparable down the column -- a short bar high on the track really is a warm,
    # steady day. Bars all spanning the full width (the previous behaviour) encode
    # nothing at all.
    lows = [r["lo"] for r in days if r.get("lo") is not None]
    highs = [r["hi"] for r in days if r.get("hi") is not None]
    # The station often reads below the NWS low on a clear, calm morning (frost
    # nights especially). Widen the scale to take it, or the dot has nowhere to go.
    if now_temp is not None:
        lows.append(float(now_temp))
        highs.append(float(now_temp))
    gmin = min(lows) if lows else 0
    gmax = max(highs) if highs else 1
    span = max(1.0, float(gmax - gmin))
    today = datetime.now().date().isoformat()

    rows = []
    for r in days:
        lo, hi = r.get("lo"), r.get("hi")
        if lo is None or hi is None:
            track = '<div class="bdtrack"></div>'
        else:
            is_now = r["date"] == today and now_temp is not None
            # Apple marks where the current temperature falls on today's row, and
            # stretches today's bar to reach it when it is outside the forecast.
            blo = min(lo, float(now_temp)) if is_now else lo
            bhi = max(hi, float(now_temp)) if is_now else hi
            left = (blo - gmin) / span * 100.0
            width = max(4.0, (bhi - blo) / span * 100.0)
            width = min(width, 100.0 - left)
            dot = ""
            if is_now:
                pos = (float(now_temp) - gmin) / span * 100.0
                dot = (f'<div class="bddot" style="left:{max(left, min(pos, left + width)):.1f}%;">'
                       f'</div>')
            track = (f'<div class="bdtrack">'
                     f'<div class="bdbar" style="left:{left:.1f}%;width:{width:.1f}%;'
                     f'background:linear-gradient(90deg,{temp_color(blo)},{temp_color(bhi)});">'
                     f'</div>{dot}</div>')
        summary = r.get("summary") or r.get("short") or ""
        rows.append(
            f'<div class="bday">'
            f'<div class="bdmain">'
            f'<div class="bdname">{escape(_dayname(r["date"]))}</div>'
            f'{wxicons.svg(r["icon"], 30)}'
            f'<div class="bdpop">{str(r["pop"]) + "%" if (r.get("pop") or 0) >= 15 else ""}</div>'
            f'<div class="bdlo">{lo if lo is not None else "&mdash;"}&deg;</div>'
            f'{track}'
            f'<div class="bdhi">{hi if hi is not None else "&mdash;"}&deg;</div>'
            f'</div>'
            f'<div class="bdsum">{escape(summary)}</div>'
            f'</div>')
    return "".join(rows)


def _dayname(datestr):
    """Three letters, because the name column is 58px wide.

    The full weekday overflowed it -- "Wednesday" ran under the icon in every
    theme. Widening the column would take it from the temperature track, which
    is the part of the row carrying information, so the name gets shortened
    instead. "Today" fits and is worth keeping.
    """
    try:
        d = datetime.strptime(datestr, "%Y-%m-%d").date()
    except ValueError:
        return datestr
    if d == datetime.now().date():
        return "Today"
    return d.strftime("%a")
