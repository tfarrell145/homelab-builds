# 00 · Builder: prebuild at your place

About 2 hours per house. **Result:** a box and a screen the household only has to plug in, connect
their calendars to, and point the screen at.

The household's own accounts (Apple ID, Google, Tailscale) are **not** entered here. They add those
themselves at handoff, so no one else ever holds their calendar passwords.

## Collect first

| Item | Notes |
|---|---|
| Home Assistant Green (or a mini PC already running Home Assistant OS) | |
| reTerminal E1003 + USB-C **data** cable | |
| The household's street address | for weather; a nearby cross-street is enough |
| A password-manager entry named "Family Hub", shared with the household | every password below goes in it the moment it is created |
| A Mac or PC with Chrome or Edge | the screen can only be flashed from Chrome/Edge (Web Serial); Safari cannot |

## 1. Home Assistant

1. Plug the Green into your router and power. Wait 10 to 20 minutes, then open
   `http://homeassistant.local:8123`.
2. Create the owner account. Username and password into "Family Hub"; the household takes over
   this account.
3. Home location: the household's address. This drives the built-in weather (Met.no).
4. Units: set to the household's (°F, mph, in for the US).
5. Skip discovered devices; they are from your network, not theirs.
6. Settings -> System -> Updates: install everything, restart.

**Done when:** the Overview page shows a weather card for their town.

## 2. Timeframe add-on

1. Settings -> Add-ons -> Add-on Store -> ⋮ -> Repositories, add
   `https://github.com/timeframe/ha-addon`.
2. Install **Timeframe**, turn on **Start on boot** and **Watchdog**, Start.
3. Open it at `http://<box IP>:8099` directly. The Home Assistant sidebar link breaks on
   Timeframe's internal pages, so the household will use the IP address too.

**Done when:** the Timeframe page loads and shows the weather.

## 3. Helpers and automations

From [../ha/helpers.md](../ha/helpers.md):

| Section | Every house | Google house |
|---|---|---|
| 1. Big temperature | yes | yes |
| 2. Calendar offline badge | yes | yes |
| 3. Calendar offline push | after handoff (needs the household's phone) | same |
| 4. Refresh Google calendars every 15 min | | after handoff (needs the calendar entities) |
| 5. Utility badges | only with energy/water monitoring | |

Sections 3 and 4 depend on things that only exist after handoff. Leave a note in "Family Hub" so
they get done on the handoff call.

## 4. Backups

Settings -> System -> Backups -> Set up backups. Daily, and stored **off the box**: Home Assistant
Cloud, or the Google Drive backup integration once the household has an account on it. Encryption
key into "Family Hub"; without it the backups cannot be restored.

## 5. Tailscale (install only)

Settings -> Add-ons -> Add-on Store -> **Tailscale** -> Install, Start on boot, Watchdog. Do **not**
log in. The household logs in with their own account at handoff and shares the machine back to you
for support.

## 6. Flash the screen

The E1003 ships with Seeed's own firmware. It needs TRMNL firmware **1.8.7 or newer**, which is what
lets it talk to Timeframe with no cloud account.

1. Charge it on USB-C for a while, slide the power switch on. Press **Refresh** (top) to wake it.
2. **Mac only:** install the WCH CH34x driver first. The E1003's USB chip (WCH CH340K, PID 0x7522) is
   not covered by macOS's built-in driver, so without it the flasher finds no serial port.
   `CH34xVCPDriver.pkg` from https://github.com/WCHSoftGroup/ch34xser_macos, then System Settings ->
   General -> Login Items & Extensions -> Driver Extensions -> on. Check: `ls /dev/cu.*` shows
   `cu.wchusbserial…`.
3. Chrome -> `https://usetrmnl.com/flash`. Plug the E1003 **directly** into the computer, not
   through a dock.
4. Device **reTerminal E1003**, firmware 1.8.7 or newer, Connect, pick the USB serial port, Flash.
   If the E1003 build is not listed, Seeed's hub has it:
   `https://seeed-projects.github.io/OSHW-reTerminal-Series-E-D/` (TRMNL channel).
5. Unplug, power switch off then on. The screen shows TRMNL Wi-Fi setup instructions.

Stop there. The server address and Wi-Fi are entered at the household's house, because the box's
address changes when it moves to their network.

**Done when:** the screen shows the Wi-Fi setup instructions.

## 7. Before it leaves

- [ ] Home Assistant and all add-ons updated
- [ ] First backup exists, key saved
- [ ] "Family Hub" entry has: owner login, backup key, a note of sections 3 and 4 still to do
- [ ] Screen charged
- [ ] Printed or linked: the household's handoff guide (Apple or Google)

## Appendix: a used mini PC instead of the Green

Any x86-64 PC with 4 GB+ RAM, an SSD and wired Ethernet works. A used Datto 1000 (AMD GX-415GA,
8 GB, ~8 W, needs a **19 V 3.42 A** adapter) is proven. Install Home Assistant OS by booting an
Ubuntu live USB, downloading "Home Assistant OS, Generic x86-64", and writing it to the internal
SSD with the Disks app's **Restore Disk Image**. If it will not boot: BIOS -> UEFI mode, Secure Boot
off. Then continue from step 1 above.
