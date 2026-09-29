# Family Hub

A kitchen e-ink screen that shows the family's week: who is doing what, school days off, dinner,
birthdays, weather. It updates itself from the calendars already on everyone's phones, Apple or
Google.

This repo is the setup kit, built from one house where it has run daily since September 2026.
It contains no software to install beyond two small scripts; the display software is the
source-available [Timeframe](https://github.com/timeframe/timeframe) Home Assistant add-on.

## How it fits together

```
phones (Apple or Google calendars)
        │
        ▼
Home Assistant box ── turns every calendar into the same kind of entity, adds weather
        │
        ▼
Timeframe add-on ── draws the page as an image, on the same box
        │
        ▼
e-ink screen ── wakes every 15 minutes, fetches the image, sleeps
```

Nothing goes through a cloud service except the calendars themselves.

## Who does what

| Person | Does | Guide |
|---|---|---|
| Builder | Buys the parts, sets up the box and the screen at their place | [docs/00-builder-prebuild.md](docs/00-builder-prebuild.md) |
| Household, Apple calendars | Plugs it in, connects iCloud, pairs the screen (~45 min) | [docs/01-handoff-apple.md](docs/01-handoff-apple.md) |
| Household, Google calendars | Same, with Google | [docs/01-handoff-google.md](docs/01-handoff-google.md) |
| Household | Organises the calendars so the screen reads well | [docs/02-calendar-playbook.md](docs/02-calendar-playbook.md) |
| Household with kids | Generates school runs, daycare, practices as assignable events | [docs/03-recurring-events.md](docs/03-recurring-events.md) |
| Anyone | Something looks wrong | [docs/04-when-it-breaks.md](docs/04-when-it-breaks.md) |
| Anyone | F1 races, utility badges, clothing icons | [docs/05-optional-extras.md](docs/05-optional-extras.md) |

## Using Claude with this

Every guide is written so a Claude session can walk you through it. Point Claude at this repo
(`https://github.com/tfarrell145/family-hub`) and say which guide you are on. [CLAUDE.md](CLAUDE.md)
gives it the background and the handful of mistakes that cost real time in the reference house.

## Parts

| Part | Price (2026) | Notes |
|---|---|---|
| [Home Assistant Green](https://www.home-assistant.io/green/) | ~$99 | Home Assistant comes preinstalled. Any small PC running Home Assistant OS works |
| [Seeed reTerminal E1003](https://www.seeedstudio.com/) | ~$180 | 10.3" e-paper, 1872×1404, battery, desk stand |
| Ethernet cable | | the box plugs into the router |

## Repo map

| Path | What |
|---|---|
| `docs/` | the guides |
| `ha/helpers.md` | every Home Assistant helper and automation, ready to paste |
| `ha/eink_battery.yaml` | screen battery sensor and low-battery alert |
| `ha/f1_timeframe.*` | optional F1 races calendar |
| `rides/rides.py` | recurring kid logistics -> `.ics` file, any computer |
| `rides/mac/` | the same thing as a daily Mac job writing straight into Apple Calendar |
| `ROADMAP.md` | where this could go next |

## Credits and licensing

The display is drawn by **Timeframe**, © Timeframe LLC, licensed under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).
This repo contains none of Timeframe's code; each house installs it from
[timeframe/ha-addon](https://github.com/timeframe/ha-addon). Timeframe is free for personal use.
Setting it up for someone for pay, or selling hardware with it, needs Timeframe LLC's permission.

Everything in this repo (guides and scripts) is MIT licensed; see [LICENSE](LICENSE).
