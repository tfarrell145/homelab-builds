# 03 · Recurring events: school runs, daycare, practices

**Result:** every drive for the school year sits on the `Unassigned` calendar as its own event,
skipping school days off and switching to early-release times on their own. Parents claim them by
moving them to their calendar (see [02-calendar-playbook.md](02-calendar-playbook.md)).

## Why not just a repeating event

A repeating event is one object. Apple Calendar cannot move one Tuesday of it to another calendar;
changing the calendar moves the whole series. And a repeating event does not know the school is
closed on Columbus Day. So a small script writes one event per ride, per day, reading the school
calendar to skip days off.

In the reference house this is five series (two school runs, two daycare runs, one practice) and
about 650 events for a school year.

## 1. Describe your rides: `rides.json`

Copy [../rides/rides.example.json](../rides/rides.example.json) to `rides.json` in the repo folder
(`cp rides/rides.example.json rides.json`) and edit that. Ask Claude to fill it in from
a plain description ("Sam has soccer Monday and Wednesday 4:30 to 5:30 until mid-November...").

```json
{
  "title": "School PM",
  "from": "2026-09-08",
  "until": "2027-06-11",
  "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
  "start": "15:00",
  "end": "15:30",
  "school_days_only": true,
  "early_release": { "start": "12:00", "end": "12:30" }
}
```

| Series field | Required | Meaning |
|---|---|---|
| `title` | yes | Event title. Name the child or a place only one child uses |
| `days` | yes | any of `Sun` `Mon` `Tue` `Wed` `Thu` `Fri` `Sat` |
| `start`, `end` | yes | 24-hour `HH:MM` |
| `from`, `until` | no | first and last date, `YYYY-MM-DD`, inclusive |
| `school_days_only` | no | `true` skips days the school calendar says "No School" |
| `early_release` | no | times used instead on days the school calendar says "Early Release" |

| Top-level field | Meaning |
|---|---|
| `timezone` | e.g. `America/New_York`, `America/Chicago`, `America/Los_Angeles` |
| `through` | generate up to this date (end of the school year) |
| `holidays` | dates with no rides for **any** series (daycare closures, Thanksgiving) |
| `school.ics` | the school calendar's iCal link (same one as in the playbook), or a downloaded `.ics` file |
| `school.no_school_keywords` | words that mark a day off, matched anywhere in an event title, any case. Default `["No School"]` |
| `school.early_release_keywords` | same, for early release. Default `["Early Release"]` |
| `school.no_school_dates`, `school.early_release_dates` | dates to add by hand, if the school calendar misses some |
| `target_calendar`, `assigned_calendars`, `horizon_days`, `school.calendars` | used by the Mac job only (path B) |

Check the keywords against the real school calendar: some schools write "No Classes" or "Half Day".
Add every phrase they use.

## 2. Generate and import

Two ways. Path A works for everyone; path B is for an Apple house with a Mac that is usually on.

### Path A: a file you import (any computer, Apple or Google)

Needs Python 3.9 or newer (on a Mac it is already there as `python3`). Or ask Claude to run it
and hand you the file.

```bash
python3 rides/rides.py --config rides.json --dry-run
python3 rides/rides.py --config rides.json
```

The dry run lists every school day off, early release and holiday it found, then every ride. Check
the days off against the school's own list before generating. Then it writes `rides.ics`.

Import it into the **Unassigned** calendar:

| Calendar | Import |
|---|---|
| Mac Calendar | File -> Import -> `rides.ics` -> choose **Unassigned** |
| iPhone | AirDrop or email the file to yourself, tap it -> **Add All** -> choose **Unassigned** |
| Google Calendar (computer only) | Settings (gear) -> **Import & export** -> Import -> select file -> "Add to calendar": **Unassigned** -> Import |

Import once per school year, or once per term. To add a series midway, generate just that series
from a date so nothing already imported comes in twice:

```bash
python3 rides/rides.py --config rides.json --only "Riley Swim" --from 2027-01-04
```

To change the times of a series already imported: delete its remaining events on Unassigned, then
generate it again with `--only` and `--from` today. Rides already moved to a parent are yours to fix
by hand.

Each event has a fixed ID built from title and date. What Apple and Google do when the same file
is imported twice (update in place or duplicate) has not been tested; do not rely on it.

### Path B: a daily Mac job (Apple calendars only)

This is how the reference house runs it. A small Mac program writes the rides straight into Apple
Calendar every morning at 05:00, filling in anything missing up to `through` (or at least
`horizon_days` ahead). It also keeps a
ledger, so a ride deleted by hand never comes back, and it will not duplicate a ride that a parent
already claimed.

Needs a Mac that is on (or wakes) most mornings, Xcode Command Line Tools
(`xcode-select --install`), and the Mac's Calendar app signed in to the family's iCloud.

```bash
cd family-hub/rides/mac
./build.sh
family-rides --config ../rides.json --list-calendars   # grants Calendar access on first run
family-rides --config ../rides.json --dry-run
family-rides --config ../rides.json
```

`--list-calendars` triggers the macOS permission prompt; allow full access. Then install the daily
job: edit `com.family-hub.rides.plist`, replacing `YOUR_USER` and the config path with yours, then

```bash
cp com.family-hub.rides.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.family-hub.rides.plist
```

| Goal | Command |
|---|---|
| Preview | `family-rides --config rides.json --dry-run` |
| Stop a series, keep the rides already made | set `until`, or remove it from `rides.json` |
| Remove a series' unclaimed future rides | `family-rides --config rides.json --purge "Sam Soccer" --dry-run`, then without `--dry-run` |
| Change a series' times | edit it, then `--purge` it; it regenerates next morning. Claimed rides are left alone |
| Log | `tail -20 ~/Library/Logs/family-rides.log` |

Path B reads the school calendar from Apple Calendar by name (`school.calendars`), so the school
calendar must also be subscribed on that Mac. It stops with `no calendar named ...` if a calendar
it uses is renamed or deleted.

## Each August

1. Update `through`, each series' `from` and `until`, and `holidays`.
2. Point `school.ics` (and `school.calendars` for path B) at the new school year's calendar.
3. Dry run, check the days off, generate.

## Other recurring things

The same tool handles anything that repeats on set days and needs a person: bin day, piano
lessons, a standing Friday pickup. For things that need no one to claim them (a weekly family
dinner), an ordinary repeating event on `Family Events` is simpler.
