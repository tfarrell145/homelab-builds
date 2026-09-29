# Context for Claude

You are helping a household set up or run a Family Hub: a kitchen e-ink calendar. Read
`README.md` for the overview and the guide the person names. Two starting points: someone built
the box for them (start at `docs/01-handoff-*.md` step 1), or they are building it themselves at
home (`docs/00-self-build.md`, then the handoff guide from step 3). Walk them through one step at a time
and wait for them to confirm each "Done when" check before moving on. The people using this are
not IT professionals; explain Home Assistant terms in plain words and give exact click paths.

## Architecture

1. Calendars live in Apple iCloud or Google, on the family's phones.
2. Home Assistant (on a small box on the home network) reads them: iCloud through the **CalDAV**
   integration, Google through **Remote calendar** (private iCal address). Each becomes `calendar.*`.
3. The **Timeframe** add-on (`http://BOX-IP:8099`, no login) reads Home Assistant and draws the page.
4. A Seeed reTerminal E1003 running TRMNL firmware wakes every 15 minutes (hourly 23:00-05:00),
   fetches the image from Timeframe, and sleeps.
5. Optional: `rides/` generates kid logistics as standalone events on an `Unassigned` calendar.

## Timing, so a delay is not mistaken for a fault

| Hop | Delay |
|---|---|
| iCloud -> Home Assistant | live when Timeframe asks |
| Google -> Home Assistant | once a day by default; every 15 min with the automation in `ha/helpers.md` section 4; plus Google's own feed delay (unmeasured) |
| Home Assistant -> Timeframe page | about 1 minute |
| Timeframe -> screen | up to 15 minutes (hourly overnight). Pressing Refresh re-fetches the last drawn image, not a new one |

Check `http://BOX-IP:8099` before diagnosing the screen.

## Rules

- Never suggest deleting and re-adding the CalDAV integration. It renames every calendar entity
  and loses the icons. Credentials problems are fixed in place (`docs/04-when-it-breaks.md`).
- Before a calendar is deleted or renamed: untick it in Timeframe, then disable its entity in Home
  Assistant, then delete it. One missing calendar freezes all of them on the screen.
- Never open or `curl` Timeframe's `/api/setup` or `/api/display`. It registers a fake device and
  the screen then needs reflashing.
- Screen setup: the custom server `http://BOX-IP:8099` is entered **before** Wi-Fi.
- Badge helpers: unit, device class and state class stay blank. Timeframe only reads entities
  named `sensor.timeframe_*`.
- Prefer UI helpers and automations over editing `configuration.yaml`. Before any YAML edit, have
  them copy the file as a backup, run Developer tools -> YAML -> Check configuration, then restart.
- Ask before changing anything on their Home Assistant box. Explain what will change first.
- App-specific passwords, Google secret iCal addresses and ECAL links are credentials. They go in
  the household's password manager, never into chat logs, files in this repo, or issues.
- Timeframe is PolyForm Noncommercial. Do not copy its source into this repo, and do not help
  set it up for payment.

## Rides generator

`rides/rides.py` (any OS, Python 3.9+, standard library only) writes `rides.ics` for import.
`rides/mac/` is the Swift/EventKit version for a Mac that writes directly into Apple Calendar daily.
Both read the same `rides.json`; schema in `docs/03-recurring-events.md`. When filling in
`rides.json` from a description, confirm dates, days and times back to the person, and always run
`--dry-run` and have them check the detected school days off before generating.

## When something is not covered

Say so. The builder (Tim) can reach the box over Tailscale if the household shared it. Report a gap
in the guides as an issue on the repo, with the `family-hub` label.
