# 05 · Optional extras

## Clothing forecast

Timeframe -> the device -> Settings -> **Clothing forecast** (Landscape template). Adds a shirt and a
shorts/pants icon beside each day, from that day's hourly forecast:

| Garment | When |
|---|---|
| Shorts | 8am at least 55°F, and noon and the day's high at least 65°F |
| T-shirt | shorts weather, or noon above 50°F |
| Otherwise | pants, long sleeves |

No Home Assistant setup.

## Home utility badges

Electricity, water or heating-oil totals across the top-left, if the house already has that
monitoring in Home Assistant. [../ha/helpers.md](../ha/helpers.md) section 5.

## Screen battery on the display and on the phone

[../ha/eink_battery.yaml](../ha/eink_battery.yaml): a battery badge top-right, and a push at 25% and
10%. Needs `configuration.yaml` edits and a full restart, so the builder usually does it.

## F1 races

30 minutes, needs file access to the box, so usually the builder. **Result:** the screen shows only
Grand Prix and Sprint races, titled like `Azerbaijan Grand Prix R15` and `Singapore Sprint R17`,
while phones keep the full F1 calendar with practice and qualifying.

Every night at 04:10 Home Assistant runs a small script. It downloads the official F1 calendar feed,
keeps only the races, looks up each race's round number (from Jolpica, the free public F1 results
database), and writes a new calendar file on the box. A Remote calendar in Home Assistant reads that
file. The file never leaves the box.

### 1. The house's own F1 calendar link

1. On f1.com, open the racing schedule and choose **Sync calendar** (run by a service called ECAL).
   Sign up with the F1 fan's email and add it to their phone.
2. Copy the subscription link, which looks like `webcal://ics.ecal.com/ecal-sub/…/Formula%201.ics`.
   Save it in "Family Hub". If ECAL's page does not show it, it is in the confirmation email, or on
   the phone under Settings -> Calendar -> Accounts -> the subscribed calendar.

### 2. Put the script on the box

1. Settings -> Add-ons -> Add-on Store -> **Advanced SSH & Web Terminal** (or File editor), start it.
2. Create `/config/family-hub` and `/config/www`. **`/config/www` has to exist before the restart in
   step 3**, or Home Assistant will not serve the file.
3. Copy [../ha/f1_timeframe.py](../ha/f1_timeframe.py) into `/config/family-hub/`.
4. Test it. The last line should read like `43 events -> /config/www/f1_timeframe.ics`:

```bash
sudo python3 /config/family-hub/f1_timeframe.py --feed "PASTE_THE_LINK"
```

### 3. Let Home Assistant run it

1. Add the `shell_command:` block from [../ha/f1_timeframe.yaml](../ha/f1_timeframe.yaml) to the end
   of `/config/configuration.yaml`, with the link.
2. Developer tools -> YAML -> **Check configuration**, then **Restart**.

### 4. The races calendar

1. Settings -> Devices & services -> Add integration -> **Remote calendar**. Name
   `Formula 1 Races`, URL `http://127.0.0.1:8123/local/f1_timeframe.ics`.
2. Settings -> Entities -> `calendar.formula_1_races` -> gear -> Icon `mdi:flag-checkered`.
3. Settings -> Automations -> Create -> ⋮ -> Edit in YAML: paste the automation from
   `f1_timeframe.yaml`, Save. Open it, ⋮ -> **Run actions**; every step in Traces should be green.
4. Timeframe -> device settings: tick **Formula 1 Races**.

Do not also add the full F1 feed to Home Assistant. If it is already there, untick it in Timeframe
first, then delete it (the playbook's deletion order).

### Checking it

- The next race weekend shows one line per race, at local start time.
- `ls -l --full-time /config/www/f1_timeframe.ics` shows 04:10 today. An older date means last
  night's run failed: open the automation's Traces.
- Until Jolpica publishes a new season (usually a few months ahead), that season's races show the
  long sponsor name with no round number, and switch to `R1`, `R2` … on their own once it does.
