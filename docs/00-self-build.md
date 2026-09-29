# 00 · Build it yourself, at home

About 2 hours, on a laptop, at home. **Result:** the Home Assistant box running on your network,
the display software installed, and the screen ready to connect. After this you continue with the
handoff guide for your calendars ([Apple](01-handoff-apple.md) or [Google](01-handoff-google.md)),
starting at its **step 3**.

This is the version for a household building everything themselves. If someone built the box for
you, skip this and start at step 1 of the handoff guide.

Do the steps in order; each one ends with a "Done when" check. If one fails, stop and ask Claude
with the step number and exactly what you see.

## Collect first

| Item | Notes |
|---|---|
| [Home Assistant Green](https://www.home-assistant.io/green/) | Home Assistant comes preinstalled |
| Seeed reTerminal E1003 and a USB-C **data** cable | a charge-only cable will not work for step 6 |
| Ethernet cable | the box plugs into your router |
| A laptop with **Chrome or Edge** | step 6 cannot be done from Safari, a phone or an iPad |
| Your router's app or admin login | usually on a sticker on the router |
| A password-manager entry called "Family Hub" | every password below goes in it the moment it is created; several are shown only once |

## 1. Plug in the box

1. Plug the Green into a spare port on your router with the Ethernet cable, then plug in its power.
2. Wait 10 minutes. The first start takes a while.
3. On the laptop, on your home Wi-Fi, open `http://homeassistant.local:8123`. If it does not load,
   wait another 10 minutes and try again.

**Done when:** a Home Assistant welcome page asks you to create an account.

## 2. First-run setup

1. **Create my smart home.** Name, username, password. Save them in "Family Hub".
2. **Home location:** your address, or a nearby cross-street. This drives the weather on the screen.
3. **Units:** °F, mph, inches in the US.
4. Skip the discovered devices for now; they can be added later.
5. Settings -> System -> **Updates**: install anything listed, and restart if asked.

**Done when:** the Overview page shows a weather card for your town.

## 3. Give it a fixed address

1. Settings -> System -> **Network**: note the **IPv4 address** (like `192.168.1.50`). This is
   **BOX-IP** for the rest of the guides.
2. In your router's app, find the device named `homeassistant` and turn on **Reserve IP**, **Fixed
   IP** or **DHCP reservation** (the name varies by router). Without this the address can change
   one day and silently disconnect the screen.
3. Save BOX-IP in "Family Hub".

**Done when:** `http://BOX-IP:8123` opens Home Assistant.

## 4. Install the display software (Timeframe)

1. Settings -> **Add-ons** -> **Add-on Store** -> ⋮ (top right) -> **Repositories**. Add
   `https://github.com/timeframe/ha-addon`, then close the box.
2. Scroll to or search for **Timeframe**. **Install**. Turn on **Start on boot** and **Watchdog**,
   then **Start**.
3. Open `http://BOX-IP:8099` in a new tab and **bookmark it**. This is where you set up the screen.
   Do not use the Timeframe link in Home Assistant's sidebar; it breaks on Timeframe's inner pages.

Anyone on your home Wi-Fi can open this page and see the family calendar. It has no login.

**Done when:** `http://BOX-IP:8099` loads and shows the weather.

## 5. Two helpers and backups

Helpers are small pieces of Home Assistant that the screen reads. From
[../ha/helpers.md](../ha/helpers.md), create:

| Section | What it does |
|---|---|
| 1. The big temperature (two helpers) | the temperature beside the date |
| 2. Calendar offline badge | a warning on the screen if a calendar stops updating |

Leave sections 3 and 4 for later; they need your phone app and calendars, and the handoff guide
comes back to them.

Then backups: Settings -> System -> **Backups** -> **Set up backups**. Daily, stored **somewhere
other than the box** (Home Assistant Cloud, or Google Drive with the Google Drive backup
integration). Save the **encryption key** in "Family Hub"; without it a backup cannot be restored.

**Done when:** both helpers exist under Settings -> Devices & services -> Helpers, and a first
backup is listed.

## 6. Install the screen's software

The screen comes with Seeed's own software. It needs the free TRMNL software instead, version
**1.8.7 or newer**, which lets it talk to your box with no cloud account. This is done once, over
a USB cable.

1. Charge the screen on USB-C for a while, then slide its power switch on. Press **Refresh** (the
   top button) to wake it.
2. **Mac only, first:** install a USB driver, or the Mac cannot see the screen at all.
   1. Download `CH34xVCPDriver.pkg` from https://github.com/WCHSoftGroup/ch34xser_macos (the green
      **Code** button -> Download ZIP, or the file in the list) and open it.
   2. System Settings -> General -> **Login Items & Extensions** -> **Driver Extensions** -> turn
      the WCH driver on. Restart the Mac if asked.
   3. Windows usually needs nothing; if the flasher finds no port, install the CH340 driver from the
      same maker.
3. In **Chrome or Edge**, open `https://usetrmnl.com/flash`. Plug the screen **directly** into the
   laptop, not through a hub or dock.
4. Device **reTerminal E1003**, firmware **1.8.7 or newer** -> **Connect** -> pick the port that
   appears (on a Mac, it contains `wchusbserial`) -> **Flash**. Leave it plugged in until it says
   done.
   If reTerminal E1003 is not in the list, use Seeed's page instead:
   `https://seeed-projects.github.io/OSHW-reTerminal-Series-E-D/` (TRMNL option).
5. Unplug it. Slide the power switch off, then on.

If the flasher shows no port at all on a Mac, the driver in step 2 is not switched on yet.

**Done when:** the screen shows TRMNL's Wi-Fi setup instructions.

## Next

Open the handoff guide for your calendars and start at **step 3**. Steps 1 and 2 there are already
done:

- Apple (iCloud): [01-handoff-apple.md](01-handoff-apple.md)
- Google: [01-handoff-google.md](01-handoff-google.md)

Read [02-calendar-playbook.md](02-calendar-playbook.md) first; setting up the calendars before
connecting them saves redoing the icons.
