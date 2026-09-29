# Home Assistant helpers and automations

Everything here is created in the Home Assistant UI, not in YAML files, so it can be edited later
from the same screens. Only the F1 extra and the screen battery sensor need `configuration.yaml`.

| Kind | Create at |
|---|---|
| Template sensor | Settings -> Devices & services -> Helpers -> Create helper -> Template -> Template a sensor |
| Automation | Settings -> Automations & scenes -> Create automation -> Create new -> ⋮ -> Edit in YAML |

For every template sensor: leave **unit, device class and state class blank**. A unit makes Home
Assistant treat the value as a number and the `icon,label` text stops working. Try a template in
Developer tools -> Template first; nothing typed there is saved.

## How Timeframe reads these

Timeframe has no badge editor. It watches Home Assistant for entities with reserved names and
draws their state. Only entities whose IDs start with `sensor.timeframe_` (plus `weather.` and
`media_player.`) are read at all, so a helper named anything else is invisible to it.

| Helper name starts with | Appears on the display |
|---|---|
| `timeframe_top_left_` | top-left row |
| `timeframe_top_right_` | top-right corner, directly above the temperature |
| `timeframe_weather_status_` | beside each day's high/low |
| `timeframe_daily_event_` | an all-day line in the day column |

The state is `icon,label`. Icons are Material Design Icons names without the `mdi-` prefix
(browse at pictogrammers.com/library/mdi). A blank state draws nothing. One helper can hold several
badges, one per line, and they stay in that order.

## 1. The big temperature beside the date (every house)

The built-in Met.no weather has no "feels like" value, so the temperature stays blank until
Timeframe is pointed at a sensor. Two helpers:

`timeframe_current_temp`

```jinja
{{ state_attr('weather.forecast_home', 'temperature') }}
```

`timeframe_weather_feels_like_entity_id` (the state is just this text, the name of the first helper)

```jinja
sensor.timeframe_current_temp
```

## 2. Calendar offline badge (every house)

The failure that matters most is invisible: when a calendar connection breaks, the display keeps
showing the last events it saved and looks normal for days. This badge appears only while any
calendar is unavailable.

`timeframe_top_right_alerts`

```jinja
{%- set dead = states.calendar | selectattr('state', 'eq', 'unavailable') | list | count -%}
{%- if dead > 0 -%}calendar-alert,Calendar offline{%- endif -%}
```

Keep top-right labels to one or two words. That slot never shrinks, so a long label pushes every
top-left badge off the screen.

## 3. Calendar offline push notification (every house)

Same check, sent to a phone after 30 minutes. Replace `notify.mobile_app_REPLACE` with the phone's
service (Developer tools -> Actions, type `notify.mobile_app` and pick from the list).

```yaml
alias: Family Hub - calendar offline
mode: single
triggers:
  - trigger: template
    value_template: >
      {{ states.calendar | selectattr('state', 'eq', 'unavailable') | list | count > 0 }}
    for: "00:30:00"
actions:
  - action: notify.mobile_app_REPLACE
    data:
      title: Kitchen calendar is not updating
      message: >
        {{ states.calendar | selectattr('state', 'eq', 'unavailable')
           | map(attribute='name') | join(', ') }} stopped responding. Open Home Assistant ->
        Settings -> Devices & services and look for an orange card.
```

## 4. Google houses: refresh calendars every 15 minutes

Home Assistant's Remote calendar integration re-downloads each Google calendar **once a day**
(`SCAN_INTERVAL = timedelta(days=1)` in its source). Without this automation, an event added on a
phone can take up to a day to reach the display. List every Remote calendar entity:

```yaml
alias: Family Hub - refresh Google calendars
mode: single
triggers:
  - trigger: time_pattern
    minutes: /15
actions:
  - action: homeassistant.reload_config_entry
    target:
      entity_id:
        - calendar.REPLACE_parent_a
        - calendar.REPLACE_parent_b
        - calendar.REPLACE_family
```

Google also caches its own "secret address" feed, so some delay remains even with this. Not yet
measured on a real Google calendar.

Apple (CalDAV) calendars need nothing here: the CalDAV integration asks iCloud live each time
Timeframe requests events.

## 5. Home utility badges (optional)

Only if the house has energy or water monitoring in Home Assistant. Each source is a variable on
the first lines; a missing source shows `--`, so it can be created now and wired later.

`timeframe_top_left_utilities`

```jinja
{%- set electricity = 'sensor.REPLACE_electricity_today' -%}
{%- set water       = 'sensor.REPLACE_water_today' -%}

{%- set e = states(electricity) -%}
{%- set w = states(water) -%}
flash,{{ (e | float) | round(1) ~ ' kWh' if is_number(e) else '-- kWh' }}
water,{{ (w | float) | round(0) | int ~ ' gal' if is_number(w) else '-- gal' }}
```

To connect a meter later: Helpers -> the helper -> gear -> Template options, replace the
`sensor.REPLACE_...` name, Update.

## 6. Screen battery

See `eink_battery.yaml`. It needs `configuration.yaml` because Timeframe does not publish the
screen's battery to Home Assistant; the sensor reads it from Timeframe's device settings page.
