# Roadmap

Where Family Hub could go beyond a hand-built kit. Nothing here is built. The first two outside
households (one Apple, one Google, autumn 2026) are the test: every place they get stuck becomes an
issue on this repo (label `family-hub`), and those issues decide what comes first.

## Is Home Assistant needed?

For the display as it works today, yes. Timeframe reads every calendar, the weather and every
badge through Home Assistant. Home Assistant is also what makes Apple and Google look the same:
CalDAV and Remote calendar both become ordinary `calendar.*` entities, so nothing downstream cares
which one a family uses.

A calendar-only household does not need Home Assistant in principle. A product could build the
calendar connections in and treat Home Assistant as an optional extra for energy, weather-station
or other badges.

## Where the kit is rough today

| Area | Today | Direction |
|---|---|---|
| Unboxing | two boxes; the builder flashes the screen with a desktop browser and a driver | one box that is the server; the screen arrives already flashed |
| Setup | Home Assistant UI, template helpers, a router reservation, typing an IP into the screen | a first-run web page: sign in with Apple or Google, tick calendars, pick icons. The screen finds the box on the network by itself |
| Calendars | CalDAV and Remote calendar, a 15-minute reload automation for Google | built-in Apple (CalDAV), Google (OAuth, real-time) and plain iCal connections |
| Customising | four fixed badge slots, each a hand-written template | a block editor: drag a block onto the page, choose what it shows ("this Home Assistant sensor", "weather", "this calendar"), see it live |
| Monitoring | a Home Assistant badge and push alert for dead calendars; battery alert | one health page: last calendar sync per calendar, last screen check-in, battery, Wi-Fi signal |
| Recurring events | a script and a JSON file; import by hand or a Mac job | a "rides" block in the setup page, writing to the family's calendar directly |

## Licensing constraint

Timeframe is licensed PolyForm Noncommercial. A device or service that is sold cannot include it
without a commercial license from Timeframe LLC. Two ways forward:

1. **Own renderer.** Draw the page with our own code. [Tesserae](https://github.com/dmellok/tesserae)
   (AGPL-3.0, drag-and-drop cells, 40+ widgets, already speaks the TRMNL screen protocol) is the
   working reference for the block model; AGPL allows commercial use as long as the source of the
   modified server stays public.
2. **Ask Timeframe LLC** about a commercial license before any design work that depends on
   Timeframe.

Either way, the calendar organisation in `docs/02-calendar-playbook.md` and the rides generator
are ours and carry over unchanged.
