# 02 · Calendar playbook

How the reference house organises its calendars so the kitchen screen can be read from across
the room. Copy the idea, not the names. Settle this in Apple or Google Calendar **before**
connecting Home Assistant; renaming or deleting a calendar later takes care (rules at the bottom).

## The one idea: the calendar is the label

The screen draws every event with the **icon of the calendar it is on**. There is no per-event tag
that survives a repeating event. So each calendar answers one question at a glance, and the
question that matters in a busy house is **who has to act**, not who the event is about.

The reference house started with a calendar per child and retired them. "Soccer" is about a child,
but a parent drives, and the screen is more useful saying who drives. Kids' events live on the
calendar of whoever has to act, and the title names the child.

## The layout

| Calendar | Holds | Icon | On the screen |
|---|---|---|---|
| One per adult (e.g. `Alex`, `Jordan`) | anything that person has to do or attend | `mdi:alpha-a`, `mdi:alpha-j` | their initial |
| `Family Events` | everyone goes | `mdi:home-heart` | house |
| `Unassigned` | kid logistics nobody has taken yet | `mdi:account-question` | question mark: someone needs to claim it |
| `Meals` | dinner, as all-day events titled with the meal | `mdi:silverware-fork-knife` | left column, under the date |
| `Birthdays` | birthdays | `mdi:cake-variant` | cake |
| School | the school's published calendar (days off, early release) | `mdi:school` | left column, since they are all-day |

Optional: an F1 races calendar ([05-optional-extras.md](05-optional-extras.md)).

Icons are [Material Design Icons](https://pictogrammers.com/library/mdi/) names. `mdi:alpha-a`
through `mdi:alpha-z` are the letters; there are circled and boxed versions too
(`mdi:alpha-a-circle`).

### Where things land on the screen

| Event | Column |
|---|---|
| All-day (meals, school days off, birthdays) | left, under the day's date |
| Timed | right, in time order |

To move something to the left column, make it all-day.

### Titles

- Name the child or a place only one child uses: `Sam Soccer`, `Riley Swim`, `Daycare AM`.
- Keep them short; long titles wrap and push later days off the screen.
- No initials in the title (`A - Dentist`). The icon already says whose it is; the reference house
  used prefixes before switching to icons and dropped them.

## The Unassigned calendar: how kid logistics get claimed

Every school run, daycare drop-off and practice goes onto `Unassigned` first (automatically; see
[03-recurring-events.md](03-recurring-events.md)). Whoever takes one moves it to their own
calendar. The question-mark icon on the screen is the to-do list: anything still showing it has no
driver.

| On | Move one event to a parent |
|---|---|
| Mac Calendar | right-click the event -> **Calendar** -> the parent |
| iPhone | open the event -> Edit -> **Calendar** -> the parent -> Done |
| Google Calendar (web) | open the event -> edit (pencil) -> calendar dropdown under the title -> Save |
| Google Calendar (phone) | open the event -> edit -> tap the calendar name -> pick -> Save |

This only works because each ride is its own event. Apple Calendar moves a **whole repeating series**
when you change one occurrence's calendar, which is why the rides are generated as separate
events rather than as one repeating event.

## School calendar

Most schools publish an iCal link (look for "subscribe" or "iCal" on the school calendar page).
Add that link to Home Assistant directly as a **Remote calendar** (Settings -> Devices & services ->
Add integration -> Remote calendar), for both Apple and Google houses. It does not need to be on
anyone's phone for the screen to show it, and the rides generator reads the same link to skip days
off.

Name the Home Assistant entry after the school year (`School 26-27`). Next August, add the new
year's link as a new entry, tick it in Timeframe, then retire the old one using the rules below.

## Meals

A `Meals` calendar with one all-day event per dinner (`Tacos`, `Leftovers`) puts dinner under each
date on the screen. Plan the week on Sunday on a phone; nothing else is needed.

## Reminders and to-do lists (Apple houses)

iCloud Reminders lists come into Home Assistant with the calendars, as `todo.*` entities
(`todo.groceries`). They are not on the e-ink screen, but they can go on a Home Assistant
dashboard, and anyone can tick items off from the Reminders app as usual.

## Rules for changing calendars later

Deleting a calendar and changing the Apple ID email each froze the reference house's screen for
a day or more.

| Change | Do it in this order |
|---|---|
| Delete or rename a calendar | 1. Timeframe -> device settings -> **untick** it. 2. Home Assistant -> Settings -> Entities -> the calendar -> gear -> **Enabled off**. 3. Then delete or rename it in Apple/Google. Deleting a calendar Timeframe still reads freezes **every** calendar on the screen |
| Add a calendar | Apple: Settings -> Devices & services -> CalDAV -> ⋮ -> **Reload** so Home Assistant picks it up, set its icon, tick it in Timeframe. Google: add its secret address as a new Remote calendar, and add it to the 15-minute refresh automation |
| Change the Apple ID email | The CalDAV connection breaks silently. See [04-when-it-breaks.md](04-when-it-breaks.md). Never delete and re-add the CalDAV integration: that renames every calendar and loses the icons |
| Something looks stuck | Settings -> Devices & services: an orange "needs attention" card names the broken connection |

Keep a copy of your calendar/icon table in "Family Hub". If a calendar is ever re-added it comes
back with no icon, and this table is the record to restore from.
