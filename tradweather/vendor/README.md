# vendor/

Third-party files the page used to load from CDNs, pinned and served locally so a page load makes
no requests to Google Fonts or jsDelivr. `render.py` copies this folder into `public/vendor/`
whenever the copy is missing or out of date.

| Folder | What | Version | Licence | Source |
|---|---|---|---|---|
| `chartjs/` | Chart.js UMD build | 4.5.0 | MIT (`LICENSE.md`) | `cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js` |
| `leaflet/` | Leaflet JS, CSS, control images | 1.9.4 | BSD-2-Clause (`LICENSE`) | `cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/` |
| `mdi/` | Material Design Icons webfont + CSS (woff2, woff) | 7.4.47 | Apache 2.0 code, OFL font (`LICENSE`) | `cdn.jsdelivr.net/npm/@mdi/font@7.4.47/` |
| `fonts/` | Inter, JetBrains Mono, Montserrat, Lato, Latin subset, woff2 | @fontsource 5.3.0 | SIL OFL 1.1 (`LICENSE-*.txt`) | `cdn.jsdelivr.net/npm/@fontsource/<family>@5.3.0/files/` |

Updating one: replace the files, bump the version here, and bump `VENDOR_V` in `render.py` so
browsers and the `public/` copy pick up the change.
