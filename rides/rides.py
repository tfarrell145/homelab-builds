#!/usr/bin/env python3
"""Turn recurring kid logistics (school runs, daycare, practices) into a .ics
file of standalone events, one per ride, for importing into an "Unassigned"
calendar.

Standalone, not repeating, because Apple Calendar moves a whole repeating
series when its calendar changes. A standalone ride is assigned to a parent by
moving that one event to the parent's calendar.

    python3 rides.py --config rides.json --dry-run      show detected school days off and the ride count
    python3 rides.py --config rides.json                write rides.ics
    python3 rides.py --config rides.json --from 2027-01-04 --only "Swim"
                                                        just one new series, from a date

Standard library only, Python 3.9 or newer. Same rides.json format as the Mac
tool in mac/, which creates the events directly instead of writing a file.
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.request
from zoneinfo import ZoneInfo

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fail(msg):
    sys.exit(f"error: {msg}")


def day(s, what):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        fail(f"{what}: bad date {s!r}, use YYYY-MM-DD")


def hhmm(s, what):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s or "")
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        fail(f"{what}: bad time {s!r}, use HH:MM 24-hour")
    return dt.time(int(m[1]), int(m[2]))


def norm(s):
    return s.replace("’", "'").lower()


# ---------- school calendar ----------

def read_ics(src):
    if re.match(r"(https?|webcal)://", src):
        url = re.sub(r"^webcal://", "https://", src)
        req = urllib.request.Request(url, headers={"User-Agent": "family-hub-rides"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    with open(src, encoding="utf-8") as f:
        return f.read()


def ics_date(line, value, tz):
    """DTSTART/DTEND -> (local date, is_all_day)."""
    if "VALUE=DATE" in line.split(":", 1)[0] or len(value) == 8:
        return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    t = dt.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        t = t.replace(tzinfo=dt.timezone.utc).astimezone(tz)
    else:
        m = re.search(r"TZID=([^;:]+)", line)
        if m:
            try:
                t = t.replace(tzinfo=ZoneInfo(m[1])).astimezone(tz)
            except Exception:
                pass  # unknown TZID: treat as local wall time
    return t.date(), False


def school_days_off(school, tz):
    """{date: set of 'no_school' / 'early_release'} from the school's calendar feed."""
    flags = {}
    for d in school.get("no_school_dates", []):
        flags.setdefault(day(d, "no_school_dates"), set()).add("no_school")
    for d in school.get("early_release_dates", []):
        flags.setdefault(day(d, "early_release_dates"), set()).add("early_release")

    sources = school.get("ics", [])
    if isinstance(sources, str):
        sources = [sources]
    kinds = {
        "no_school": [norm(k) for k in school.get("no_school_keywords", ["No School"])],
        "early_release": [norm(k) for k in school.get("early_release_keywords", ["Early Release"])],
    }
    skipped_repeating = 0
    for src in sources:
        try:
            text = read_ics(src)
        except Exception as e:
            fail(f"cannot read school calendar {src}: {e}")
        text = re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n")
        for block in re.findall(r"BEGIN:VEVENT\n(.*?)END:VEVENT", text, re.S):
            props = {}
            for line in block.splitlines():
                name, _, value = line.partition(":")
                props.setdefault(name.split(";")[0], (line, value))
            title = norm(props.get("SUMMARY", ("", ""))[1].replace("\\,", ","))
            hits = [k for k, words in kinds.items() if any(w in title for w in words)]
            if not hits or "DTSTART" not in props:
                continue
            if "RRULE" in props:
                skipped_repeating += 1
                continue
            start, all_day = ics_date(*props["DTSTART"], tz)
            end = start
            if "DTEND" in props:
                end, _ = ics_date(*props["DTEND"], tz)
                if all_day:
                    end -= dt.timedelta(days=1)  # all-day DTEND is exclusive
            d = start
            while d <= max(start, end):
                flags.setdefault(d, set()).update(hits)
                d += dt.timedelta(days=1)
    if skipped_repeating:
        print(f"warning: {skipped_repeating} repeating school event(s) matched a keyword and were "
              "ignored; list those dates in no_school_dates / early_release_dates", file=sys.stderr)
    return flags


# ---------- rides ----------

def rides(config, first, last, only, tz):
    holidays = {day(h, "holidays") for h in config.get("holidays", [])}
    flags = school_days_off(config.get("school", {}), tz)
    out = []
    d = first
    while d <= last:
        weekday = WEEKDAYS[d.weekday()]
        f = flags.get(d, set())
        if d not in holidays:
            for s in config["series"]:
                title = s["title"]
                if only and title not in only:
                    continue
                if weekday not in s["days"]:
                    continue
                if "from" in s and d < day(s["from"], title):
                    continue
                if "until" in s and d > day(s["until"], title):
                    continue
                if s.get("school_days_only") and "no_school" in f:
                    continue
                early = "early_release" in f and s.get("early_release")
                times = s["early_release"] if early else s
                out.append({
                    "title": title,
                    "date": d,
                    "start": hhmm(times["start"], title),
                    "end": hhmm(times["end"], title),
                    "early": bool(early),
                })
        d += dt.timedelta(days=1)
    return out, flags, holidays


def fold(line):
    out, b = [], line.encode("utf-8")
    while len(b) > 75:
        cut = 75 if not out else 74
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n ".join(out)


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")


def to_ics(items, tzname):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//family-hub//rides//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-TIMEZONE:{tzname}"]
    for r in items:
        key = f"{r['title']}|{r['date'].isoformat()}"
        uid = hashlib.sha1(key.encode()).hexdigest()[:20] + "@family-hub"
        start = dt.datetime.combine(r["date"], r["start"])
        end = dt.datetime.combine(r["date"], r["end"])
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID={tzname}:{start:%Y%m%dT%H%M%S}",
            f"DTEND;TZID={tzname}:{end:%Y%m%dT%H%M%S}",
            f"SUMMARY:{esc(r['title'])}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, help="rides.json")
    ap.add_argument("--out", default="rides.ics")
    ap.add_argument("--from", dest="first", help="first date, YYYY-MM-DD (default today)")
    ap.add_argument("--through", help="last date (default: 'through' in the config)")
    ap.add_argument("--only", action="append", help="one series title; repeat for more")
    ap.add_argument("--dry-run", action="store_true", help="list rides and days off, write nothing")
    a = ap.parse_args()

    try:
        with open(a.config, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read {a.config}: {e}")

    tzname = config.get("timezone") or fail('config needs "timezone", e.g. "America/New_York"')
    try:
        tz = ZoneInfo(tzname)
    except Exception:
        fail(f"unknown timezone {tzname!r}")

    first = day(a.first, "--from") if a.first else dt.datetime.now(tz).date()
    last_s = a.through or config.get("through") or fail('set "through" in the config or pass --through')
    last = day(last_s, "through")
    known = {s["title"] for s in config["series"]}
    for t in a.only or []:
        if t not in known:
            fail(f"--only {t!r}: no series with that title")

    items, flags, holidays = rides(config, first, last, a.only, tz)

    if a.dry_run:
        for d in sorted(set(flags) | holidays):
            if first <= d <= last and d.weekday() < 5:
                what = "holiday, no rides" if d in holidays else \
                    "NO SCHOOL" if "no_school" in flags[d] else "early release"
                print(f"{WEEKDAYS[d.weekday()]} {d}  {what}")
        for r in items:
            note = "  (early release)" if r["early"] else ""
            print(f"{WEEKDAYS[r['date'].weekday()]} {r['date']}  "
                  f"{r['start']:%H:%M}-{r['end']:%H:%M}  {r['title']}{note}")
        print(f"{len(items)} rides, {first} to {last}")
        return

    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(to_ics(items, tzname))
    print(f"{len(items)} rides, {first} to {last} -> {a.out}")


if __name__ == "__main__":
    main()
