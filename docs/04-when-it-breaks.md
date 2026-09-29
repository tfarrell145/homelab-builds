# 04 · When it breaks

Every row cost real troubleshooting time in the reference house. Start with the first column; the
most common one is first.

Before anything else: open `http://BOX-IP:8099`. It shows what the screen will show next. If the
web page is right and only the screen is behind, it is a timing question, not a fault.

## Calendar

| Symptom | Cause | Fix |
|---|---|---|
| Screen looks normal but new events never appear, for hours or days | A calendar connection failed. Timeframe keeps showing the last events it saved | Home Assistant -> Settings -> Devices & services: look for an orange "needs attention" card on CalDAV or Remote calendar. The "Calendar offline" badge and push alert ([../ha/helpers.md](../ha/helpers.md)) exist to catch this |
| Everything froze right after a calendar was deleted | Timeframe was still reading it; one missing calendar stops all of them | Home Assistant -> Settings -> Entities -> the deleted calendar -> gear -> **Enabled off**. Recovers within a minute. Next time, use the order in the playbook |
| CalDAV says "Credentials error" after an Apple ID email change | The saved username is still the old email; the re-authenticate dialog only asks for the password | Do **not** delete the integration (that renames every calendar and drops the icons). Ask the builder: the fix is editing `username` for the CalDAV entry in `/config/.storage/core.config_entries` over SSH, then restarting Home Assistant |
| CalDAV "Credentials error", email unchanged | The app-specific password was revoked, or the Apple ID password was changed (which revokes them all) | Make a new app-specific password; the orange card's **Reconfigure** asks for it |
| Google: new events take hours to appear | The 15-minute refresh automation is missing, or a calendar is not in its list | [../ha/helpers.md](../ha/helpers.md) section 4 |
| An event shows the wrong icon | It is on a different calendar than you think, or that calendar has no icon | Check the event's calendar; set the icon under Settings -> Entities |
| A calendar has no icon after it was re-added | Re-adding creates a new entity | Set it again from your saved table |
| All calendars blank for a minute after a Home Assistant restart | CalDAV is reconnecting | Wait |

## Screen

| Symptom | Cause | Fix |
|---|---|---|
| Says `MAC ... not registered - purchase a BYOD license` | It is talking to TRMNL's cloud: the custom server was blank or wrong | Hold **Page Up + Page Down** 2 s, enter `http://BOX-IP:8099` first, then Wi-Fi. No license needed |
| Stuck on the 6-digit code after Add Device | Wrong code, or the screen slept for over an hour before the code was typed | Press **Refresh** for a fresh code |
| Was fine, now shows a new 6-digit code | The screen lost its pairing (reset, or new firmware) | Timeframe -> the device -> **Reconnect** with the new code. Keeps the settings. Do not delete and re-add |
| Small rotated image in one corner over grey static | Someone opened Timeframe's `/api/setup` address in a browser, which registered a fake device of the wrong size | Reflash the screen with **Erase** ([00-builder-prebuild.md](00-builder-prebuild.md) step 6), redo the handoff steps 5 and 6 |
| Web page updated, screen still old after pressing Refresh | Refresh fetches the last drawn image. A new one is drawn about a minute before each 15-minute wake-up | Wait for the next wake-up. To force it: change and save any device setting in Timeframe, wait 30 s, press Refresh |
| Changes take up to an hour at night | The screen wakes hourly 23:00-05:00 to save battery | Expected. Not configurable |
| Won't join Wi-Fi | 5 GHz-only or WPA3-only network | Use a 2.4 GHz network with WPA2 |
| Went blank or unreachable after a router change | The box's address changed | Reserve its address (handoff step 1), then redo handoff step 5 with the new BOX-IP |
| Full-screen "recharge" message | Battery under 10% | Charge it. The battery alert in [../ha/eink_battery.yaml](../ha/eink_battery.yaml) warns at 25% |

## Layout

| Symptom | Cause | Fix |
|---|---|---|
| No temperature beside the date | No feels-like helper, or its name does not start with `sensor.timeframe_` | [../ha/helpers.md](../ha/helpers.md) section 1 |
| Later days cut off at the bottom | Too many hourly-condition rows | Pick 2 or 3 hours |
| Top-left badges vanished | A long top-right label | Shorten it to one or two words |
| Several badges run together as one | Line breaks lost when pasting the template | Re-paste; Developer tools -> Template should show separate lines |
| A badge shows a number but no icon, or nothing | The helper has a unit of measurement set | Remove the unit (helper -> gear -> Template options) |

## Home Assistant

| Symptom | Cause | Fix |
|---|---|---|
| App stopped working away from home after about 6 months | Tailscale key expiry | Log the Tailscale add-on back in; disable key expiry |
| A sensor cannot be edited ("does not have a unique ID") | It was written in YAML, not made as a helper | Edit it in `configuration.yaml`, or ask the builder |
| A value changed back by itself after using Developer tools -> States | **Set state** there only overwrites a sensor until its next update | Use that page to read values only |
| Dashboard edit went wrong | Dashboards have no undo | Before big edits, copy the Raw configuration into a note; that copy is the undo |
