#!/usr/bin/env python3
"""Race-only copy of the F1 calendar for the kitchen display.

Reads an ecal Formula 1 feed (the same one the family's phones subscribe to,
which this never touches), keeps only Race and Sprint Race sessions, renames
them "<Grand Prix> R<round>" and writes a new .ics that HA's Remote Calendar
integration reads back as calendar.formula_1_races.

Round numbers come from Jolpica (the Ergast successor). Its last good answer
per season is cached beside this script, so a Jolpica outage keeps the numbers.
If the ecal fetch fails the previous .ics is left in place.

    f1_timeframe.py --feed webcal://...ics   write /config/www/f1_timeframe.ics
    f1_timeframe.py --src f1.ics --out x.ics  test against a local copy

Get the house's own ecal link from f1.com (Sync calendar) and pass it with --feed; a
webcal:// link is accepted as is. /config/www must exist when HA starts for /local/ to be served.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request

JOLPICA = "https://api.jolpi.ca/ergast/f1/{year}/races/?limit=40"
SESSION = re.compile(r" - (Sprint Race|Race)( \(TBC\))?$")
YEAR = re.compile(r"\b(20\d\d)\b")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "family-hub-f1-timeframe"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n")


def fold(line):
    out, b = [], line.encode("utf-8")
    while len(b) > 75:
        cut = 75 if not out else 74
        while (b[cut] & 0xC0) == 0x80:  # never split a UTF-8 sequence
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n ".join(out)


def events(text):
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)END:VEVENT", text, re.S):
        block = re.sub(r"BEGIN:VALARM\n.*?END:VALARM\n", "", block, flags=re.S)
        props = {}
        for line in block.splitlines():
            name, _, value = line.partition(":")
            props[name.split(";")[0]] = (line, value)
        yield props


def start_date(props):
    value = props["DTSTART"][1]
    return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def rounds(year, cache_dir):
    path = os.path.join(cache_dir, f"f1_rounds_{year}.json")
    try:
        races = json.loads(fetch(JOLPICA.format(year=year)))["MRData"]["RaceTable"]["Races"]
        data = [{"round": int(r["round"]), "date": r["date"], "name": r["raceName"]} for r in races]
        if data:
            with open(path, "w") as f:
                json.dump(data, f)
            return data
    except Exception as e:
        print(f"jolpica {year}: {e}", file=sys.stderr)
    try:
        with open(path) as f:
            return json.load(f)
    except OSError:
        return []


def match(day, sprint, season):
    # A race falls on its Jolpica date (+-1 for UTC vs local); a sprint 0-2 days before it.
    for r in season:
        gap = (dt.date.fromisoformat(r["date"]) - day).days
        if (0 <= gap <= 2) if sprint else (abs(gap) <= 1):
            return r
    return None


def build(src, cache_dir):
    seasons, out = {}, []
    for p in events(unfold(src)):
        summary = p.get("SUMMARY", ("", ""))[1]
        m = SESSION.search(summary)
        if not m or summary.startswith("CALLED OFF") or "DTSTART" not in p:
            continue
        year = int(YEAR.search(summary).group(1))
        if year not in seasons:
            seasons[year] = rounds(year, cache_dir)
        season = seasons[year]
        sprint = m.group(1) == "Sprint Race"
        r = match(start_date(p), sprint, season)
        if r:
            name = r["name"].replace(" Grand Prix", " Sprint") if sprint else r["name"]
            title = f"{name} R{r['round']}"
        else:
            # Season not on Jolpica yet: the ecal name, sponsor and all, no round.
            name = summary.split("FORMULA 1 ", 1)[-1].split(f" {year}")[0]
            name = " ".join(name.split()).title()
            title = f"{name} Sprint" if sprint else name
        lines = ["BEGIN:VEVENT", p["UID"][0], p["DTSTAMP"][0], p["DTSTART"][0]]
        lines += [p[k][0] for k in ("DTEND", "LOCATION") if k in p]
        lines += ["SUMMARY:" + title, "TRANSP:TRANSPARENT", "END:VEVENT"]
        out.extend(lines)
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//family-hub//f1_timeframe//EN",
            "CALSCALE:GREGORIAN", "X-WR-CALNAME:Formula 1 (races)"]
    return "\r\n".join(fold(l) for l in head + out + ["END:VCALENDAR"]) + "\r\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", help="the house's own ecal .ics or webcal:// link")
    ap.add_argument("--src", help="local .ics instead of the ecal feed")
    ap.add_argument("--out", default="/config/www/f1_timeframe.ics")
    a = ap.parse_args()
    if not a.src and not a.feed:
        sys.exit("pass --feed with your ecal link (f1.com -> Sync calendar)")
    try:
        src = open(a.src, encoding="utf-8").read() if a.src else fetch(a.feed.replace("webcal://", "https://", 1))
    except Exception as e:
        sys.exit(f"ecal fetch failed, keeping previous file: {e}")
    cache_dir = os.path.dirname(os.path.abspath(__file__))
    ics = build(src, cache_dir)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    os.replace(tmp, a.out)
    print(f"{ics.count('BEGIN:VEVENT')} events -> {a.out}")


if __name__ == "__main__":
    main()
