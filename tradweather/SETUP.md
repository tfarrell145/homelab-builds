# Setup

Three ways to run it. Pick one. All of them assume you have filled in `config.json` first.

## 0. Config first, always

```bash
cp config.example.json config.json
$EDITOR config.json
```

You need, at minimum: both Ambient keys, the device MAC, real coordinates, your timezone, and a contact address.

**Coordinates**: from the Ambient app → station settings, or drop a pin on the actual building. Four decimals minimum. Everything downstream — the forecast gridpoint, the radar centre, the sun and moon times, every calibration constant — keys off this one pair of numbers. Getting it wrong costs you the entire calibration record, not just the map.

**Contact address**: NWS returns 403 for requests without a `User-Agent` identifying who is calling. It stays in your local `config.json`, which is gitignored.

---

## 1. Docker Compose (recommended)

```bash
docker compose up -d
docker compose logs -f
```

Open `http://localhost:8788`.

The compose file bind-mounts the project directory to `/config` inside the container. Config, caches, your history and the generated `public/` all live in the project directory on the host, so nothing is lost when the container is replaced.

To change the port, edit both the `PORT` environment variable and the `ports:` mapping.

## 2. Docker, without compose

```bash
docker build -t tradweather .
docker run -d --name tradweather --restart unless-stopped \
  -p 8788:8788 -e PORT=8788 \
  -v "$PWD":/config \
  tradweather
```

## 3. No Docker

The renderer is standard library only, so it needs nothing installed beyond Python 3.11+. Point `TRADWEATHER_DIR` at the project directory:

```bash
export TRADWEATHER_DIR="$HOME/tradweather"
python3 render.py                       # one render, fails loudly if misconfigured
cd public && python3 -m http.server 8788
```

Then run the render on a timer.

**systemd**, `/etc/systemd/system/tradweather.service` and `.timer`:

```ini
# tradweather.service
[Service]
Type=oneshot
Environment=TRADWEATHER_DIR=/home/you/tradweather
ExecStart=/usr/bin/python3 /home/you/tradweather/render.py
```

```ini
# tradweather.timer
[Timer]
OnCalendar=*:*:00
[Install]
WantedBy=timers.target
```

**cron**: `* * * * * TRADWEATHER_DIR=/home/you/tradweather /usr/bin/python3 /home/you/tradweather/render.py`

### macOS and launchd — one trap

**launchd cannot read `~/Documents`, `~/Desktop` or `~/Downloads`.** A job that works perfectly in Terminal and dies under launchd with `Operation not permitted` is always this. Put the project in a plain home directory, e.g. `~/tradweather`.

Check the port is free first — `lsof -i :8788`. Two copies bound to different interfaces on one port produce genuinely maddening split-brain symptoms.

---

## Building the station record

The first render creates `history.csv` and starts appending to it, so the record grows on its own from day one at no extra API cost. That is enough if you are patient.

To backfill as far as Ambient will give you:

```bash
docker compose exec tradweather python3 /config/history_builder.py
# or, without Docker:  TRADWEATHER_DIR=$PWD python3 history_builder.py
```

Ambient rate-limits to **one request per second** and returns a maximum of 288 records per call, so a long backfill takes a while. The builder sleeps between pages. If your station has had an outage, the builder walks up to the gap and stops; those days are simply not in the archive and will not be recoverable.

## Calibrating

```bash
docker compose exec tradweather python3 /config/calibrate.py
```

Reads `history.csv`, writes `calibration.json` and `wind_run_dist.json`. It fetches archived model forecasts for your point from Open-Meteo, which is free and needs no key, in roughly one-year chunks.

Until it has run, the page shows raw model output and prints `calibration pending` under the forecast wind chart. Nothing breaks; the numbers are just uncorrected.

Re-run it every month or two. Each run is strictly better than the last as the record lengthens. Sectors with fewer than 20 days default to a factor of 1.0 rather than inventing a correction from three data points.

## Exposing it beyond your LAN

Your call, with two things worth saying plainly.

**The page pins your house on a map.** That is the point of it, and it is also a reason to think before putting it on the public internet.

**Verify your auth is actually enforced, the day you add it.** I put mine behind Basic Auth and confirmed the auth was working sixteen days later. It had been open the whole time. Curl it from off-network and look at the status code; do not assume the config took.

Tailscale is the low-drama answer: `tailscale serve` for private access, `tailscale funnel` if you genuinely want it public. Funnel is per-port, so other services on other ports stay private. Note that `ts.net` certificates appear in Certificate Transparency logs, so a funnelled hostname is discoverable.

## What each file does

| File | Role |
|---|---|
| `render.py` | The whole renderer — fetch, calibrate, bake HTML. Runs every 60s. |
| `basicview.py` | The Current and Radar views: folds NWS hourly into named parts of the day. |
| `wxicons.py` | Inline SVG weather icons, the NWS-phrase → icon mapping, and the Home Assistant condition mapping. |
| `icons.py` | Draws the PWA app icons as PNGs using only `zlib` and `struct`. No Pillow. |
| `history_builder.py` | **Manual.** Backfills `history.csv` from the Ambient API. |
| `calibrate.py` | **Manual.** `history.csv` → `calibration.json` + `wind_run_dist.json`. |

Generated at runtime, all gitignored: `history.csv`, `history30.json`, `calibration.json`, `wind_run_dist.json`, the three dot-prefixed caches, and `public/`.

## Consuming the data

`public/weather.json` is the machine-readable contract — current observations, a Home Assistant condition token, and the folded forecast. It is versioned with `schema_version`. Read that instead of scraping the HTML.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `403` from api.weather.gov | No `contact_email` in config, so no usable User-Agent. |
| NWS returns an HTML error page | Coordinates with more than four decimals. The renderer rounds, but check yours. |
| Everything renders, NWS sections empty | You are outside the United States. Expected. |
| `Operation not permitted` under launchd | Project is in `~/Documents`, `~/Desktop` or `~/Downloads`. Move it. |
| Charts blank on a tab you just opened | Report it. Charts are built on a pane's first show precisely because a chart constructed in a hidden container sizes itself to zero. |
| Wind reads far too low | Working as designed, if you have calibrated. The correction is real; a treed site genuinely sees a fraction of the model's wind. |
