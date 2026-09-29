# 01 · Handoff: Apple (iCloud) calendars

About 45 minutes, at home, on a laptop. **Result:** the kitchen screen shows your family's
calendars and weather, and updates itself.

Do the steps in order; each one ends with a "Done when" check. If one fails, stop and ask Claude
with the step number and exactly what you see.

Before starting, read [02-calendar-playbook.md](02-calendar-playbook.md) and set up the calendars
in Apple Calendar. Connecting first and reorganising later means redoing step 3.

You need: the Home Assistant box, the screen, the "Family Hub" password-manager entry, your router's
app or admin login, and the Apple ID that owns the family calendars.

## 1. Plug in the box and give it a fixed address

1. Plug the box into a spare port on your router with the Ethernet cable, then plug in power. Wait
   5 minutes.
2. On a laptop on your home Wi-Fi, open `http://homeassistant.local:8123` and log in with the owner
   account from "Family Hub".
3. Settings -> System -> Network: note the **IPv4 address** (like `192.168.1.50`). This is
   **BOX-IP** for the rest of this guide.
4. In your router's app, find the device named `homeassistant` and turn on **Reserve IP**, **Fixed
   IP** or **DHCP reservation** (the name varies by router). This stops the address changing,
   which would silently disconnect the screen.
5. Save BOX-IP in "Family Hub".

**Done when:** `http://BOX-IP:8123` opens Home Assistant.

## 2. Change the owner password

Settings -> your name (bottom left) -> Security -> Change password. Save it in "Family Hub".

## 3. Connect iCloud calendars

1. At `account.apple.com`: Sign-In and Security -> **App-Specific Passwords** -> +, name it
   `Home Assistant`. Apple shows the password once; save it in "Family Hub" now.
2. Home Assistant: Settings -> Devices & services -> **Add integration** -> **CalDAV**.
3. URL: `https://caldav.icloud.com`. Username: the Apple ID **email address**. Password: the
   app-specific password (not your Apple ID password). Submit.
4. Each iCloud calendar appears as `calendar.<name>`. Reminders lists come along too, as `todo.*`.

**Done when:** Settings -> Entities, search `calendar.`, lists every family calendar.

> If you ever change your Apple ID email address, this connection breaks without warning and the
> screen freezes on old events. See [04-when-it-breaks.md](04-when-it-breaks.md). Never delete and
> re-add the CalDAV integration to fix it.

## 4. Give each calendar its icon

The screen shows each event with its calendar's icon, so this is how you tell whose event it is.

1. Settings -> Entities, search `calendar.`
2. Open each one -> gear -> **Icon**, type the name from the playbook's icon table (e.g.
   `mdi:alpha-n`), Update.

**Done when:** every calendar in the list shows its icon.

## 5. Point the screen at the box

1. Power the screen on. It shows Wi-Fi setup instructions.
2. On your phone, join the Wi-Fi network **TRMNL**. A setup page opens (if not, browse to
   `http://4.3.2.1`).
3. **Custom server first.** Open the custom server option and enter exactly
   `http://BOX-IP:8099`: `http` not `https`, no trailing slash.
4. **Then** pick your home Wi-Fi and enter its password. It must be a **2.4 GHz** network. Saving
   Wi-Fi connects immediately, so a server left for afterwards never gets saved.
5. The screen shows a **6-digit code**. Ignore the "trmnl.com/start" text under it.

If the screen instead says `MAC ... not registered - purchase a BYOD license`, it is talking to
TRMNL's cloud: the server was blank or wrong. No license is needed. Hold **Page Up + Page Down**
for 2 seconds to reopen the setup page and redo 3 and 4.

## 6. Pair it

1. Laptop: `http://BOX-IP:8099` -> **Add Device**. Bookmark this page.
2. Name `Kitchen`. Device **reTerminal E1003 10.3"**. The 6-digit code. Add Device.
3. Within about 30 seconds the screen shows a confirmation, then the calendar. Press **Refresh**
   (top button) to skip the wait.

Never type Timeframe's `/api/...` addresses into a browser to test it. That creates a fake
device of the wrong size and the screen then needs reflashing.

**Done when:** the calendar is on the screen and Timeframe's device list says `reTerminal E1003 10.3"`.

## 7. Screen settings

Timeframe (`http://BOX-IP:8099`) -> the device -> Settings:

| Setting | Set to | Why |
|---|---|---|
| Template | Portrait or Landscape, matching how it stands | |
| Current date & temperature | on (Portrait) | the big date and temperature at the top |
| Hourly conditions | 2 to 3 hours only (e.g. 7am, 4pm) | each hour adds a row to every day and pushes later days off |
| Hide current day if no events after | 6:00 PM | frees space for tomorrow in the evening |
| Calendars | untick anything that is not for the family | every calendar is included by default |
| Clothing forecast (Landscape) | your call | a shirt and shorts/pants icon per day from the forecast |

Saving settings re-draws the screen within about a minute; press Refresh to fetch it.

## 8. Remote access and support: Tailscale

Lets the Home Assistant app work away from home, and lets the builder help without visiting.
Nothing on your network is opened to the internet.

1. Home Assistant: Settings -> Add-ons -> **Tailscale** -> Open Web UI -> **Log in**, with the
   Apple or Google account you want to own this. Save which one in "Family Hub".
2. At `login.tailscale.com/admin/machines`, `homeassistant` -> ⋯ -> **Disable key expiry**. If you
   skip this, remote access stops without warning after 180 days.
3. Same page, `homeassistant` -> ⋯ -> **Share** -> send the invite to the builder.
4. Each adult's phone: install **Tailscale**, sign in with the same account (or accept a share),
   leave it on. Install the **Home Assistant** app and log in.
5. In the Home Assistant app: Settings -> Companion app -> the server -> **External URL**:
   `http://100.x.y.z:8123`, using the `100.` address from the Tailscale machines page.

**Done when:** with Wi-Fi off, the Home Assistant app opens on cellular.

## 9. Finish the alerts

With the phone app now installed, create [../ha/helpers.md](../ha/helpers.md) section 3 (calendar
offline push), and the battery alert in [../ha/eink_battery.yaml](../ha/eink_battery.yaml) if you
want it. Both need your phone's notify service name.

## 10. Final check

1. Add a test event for today on your phone, on one of the family calendars.
2. Reload `http://BOX-IP:8099`: the event is in the preview within about 2 minutes.
3. The screen shows it within about 16 minutes (it wakes every 15; overnight, hourly).
4. Delete the test event.

**Done when:** the test event appeared, then disappeared.
