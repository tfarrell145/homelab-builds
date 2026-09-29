#!/usr/bin/env python3
"""Weather icons, and the NWS-phrase -> icon mapping.

NWS `shortForecast` is a small controlled vocabulary ("Mostly Sunny", "Scattered
Rain Showers", "Showers And Thunderstorms Likely"), so classification is keyword
matching over a known set rather than anything clever. Ordering matters: the most
specific condition has to win, since "Chance Showers And Thunderstorms" contains
both "showers" and "thunderstorms".

Icons are inline SVG with flat fills. Flat rather than gradient fills on purpose --
gradients need unique element ids, and these get stamped many times per page.
"""

# Warm, muted palette -- deliberately softer than the instrument-panel view.
SUN = "#F0A840"
SUN_PALE = "#F7C86B"
MOON = "#E8DCC0"
CLOUD = "#D6DBE2"
CLOUD_DK = "#A9B4C2"
RAIN = "#6D9BD1"
SNOW = "#DCE7F2"
BOLT = "#F0B93F"
FOG = "#BFC7D2"


def classify(short, is_day=True):
    """NWS shortForecast -> icon key. Most specific condition wins."""
    s = (short or "").lower()
    night = not is_day
    if "thunder" in s:
        return "thunder"
    if "snow" in s or "flurr" in s or "wintry" in s or "sleet" in s or "ice" in s:
        return "snow"
    if "freezing" in s:
        return "sleet"
    if "rain" in s or "shower" in s or "drizzle" in s:
        # "Slight Chance", "Isolated" and "Scattered" still have sun/moon behind them.
        light = any(w in s for w in ("slight chance", "isolated", "scattered", "chance"))
        if light:
            return "moon_rain" if night else "sun_rain"
        return "rain"
    if "fog" in s or "haze" in s or "smoke" in s:
        return "fog"
    if "partly sunny" in s or "partly cloudy" in s or "partly clear" in s:
        return "moon_cloud" if night else "sun_cloud"
    # Mostly cloudy gets the plain cloud, so it stays visually distinct from partly
    # cloudy -- NWS is drawing a real distinction there and the icon should keep it.
    if "mostly cloudy" in s or "broken" in s:
        return "cloud"
    if "cloud" in s or "overcast" in s:
        return "cloud"
    if "clear" in s or "sunny" in s or "fair" in s:
        return "moon" if night else "sun"
    return "moon_cloud" if night else "sun_cloud"


# Home Assistant condition tokens, keyed by the icon vocabulary above. HA's set
# is fixed (the `weather.*` state machine), so this is a narrowing: "slight
# chance of showers" has no token of its own and reads as partly cloudy, with
# the live rain rate at the station promoting it to rainy when it is actually
# raining. See station_condition() in render.py.
HA_CONDITIONS = {
    "sun": "sunny",
    "moon": "clear-night",
    "sun_cloud": "partlycloudy",
    "moon_cloud": "partlycloudy",   # HA has no partly-cloudy-night token
    "cloud": "cloudy",
    "sun_rain": "partlycloudy",
    "moon_rain": "partlycloudy",
    "rain": "rainy",
    "snow": "snowy",
    "sleet": "snowy-rainy",
    "thunder": "lightning-rainy",
    "fog": "fog",
}


def ha_condition(short, is_day=True):
    """NWS shortForecast -> Home Assistant condition token.

    Same keyword ordering as classify(), so the HA condition and the icon on
    the wall display can never disagree about what the forecast said.
    """
    return HA_CONDITIONS.get(classify(short, is_day))


def _sun(cx, cy, r, rays=True, color=SUN):
    out = []
    if rays:
        import math
        for i in range(8):
            a = i * math.pi / 4
            x1, y1 = cx + math.cos(a) * (r + 3.2), cy + math.sin(a) * (r + 3.2)
            x2, y2 = cx + math.cos(a) * (r + 7.0), cy + math.sin(a) * (r + 7.0)
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="{color}" stroke-width="3.2" stroke-linecap="round"/>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>')
    return "".join(out)


def _moon(cx, cy, r):
    """Crescent as two arcs meeting at cusps, opening to the right.

    Not a difference of two circles: an `a` command whose radius is smaller than
    half the chord has that radius silently scaled up to fit (SVG 1.1 F.6.6), so
    the obvious "big arc out, small arc back" crescent collapses into two
    identical semicircles that retrace each other and fill nothing at all.
    Every radius here is checked against its own chord.
    """
    import math
    th = math.radians(58)                     # cusp half-angle on the outer circle
    ax, ay = cx + r * math.cos(th), cy - r * math.sin(th)
    bx, by = cx + r * math.cos(th), cy + r * math.sin(th)
    inner = r * math.sin(th) * 1.32           # > half the cusp-to-cusp chord
    return (f'<path class="wxmoon" fill="{MOON}" '
            f'd="M {ax:.2f} {ay:.2f} A {r:.2f} {r:.2f} 0 1 0 {bx:.2f} {by:.2f} '
            f'A {inner:.2f} {inner:.2f} 0 0 1 {ax:.2f} {ay:.2f} Z"/>')


def _cloud(x, y, s, color=CLOUD):
    """Puffy cloud whose bounding box starts at (x, y), scaled by s."""
    return (f'<path transform="translate({x},{y}) scale({s})" fill="{color}" '
            'd="M9.5,26 a8.2,8.2 0 0,1 0.6,-16.3 a11,11 0 0,1 20.6,-2.6 '
            'a8.6,8.6 0 0,1 8.1,8.6 a8.4,8.4 0 0,1 -8.4,10.3 z"/>')


def _drops(pts, color=RAIN):
    return "".join(
        f'<line x1="{x}" y1="{y}" x2="{x-2.4}" y2="{y+7.5}" stroke="{color}" '
        f'stroke-width="3.1" stroke-linecap="round"/>' for x, y in pts)


def _flakes(pts, color=SNOW):
    # Classed like the moon: the pale fill sits on a white panel in the light theme.
    return "".join(
        f'<circle class="wxflake" cx="{x}" cy="{y+3}" r="2.4" fill="{color}"/>' for x, y in pts)


# Material Design Icons equivalents, for the `minimal` theme. E-ink wall
# dashboards draw their weather with MDI glyphs, so matching one means matching
# the icon set, not just the palette. Keyed by our own icon vocabulary rather than by HA condition, since
# we have finer distinctions than HA does (a partly-cloudy night, for one).
MDI = {
    "sun": "weather-sunny",
    "moon": "weather-night",
    "cloud": "weather-cloudy",
    "sun_cloud": "weather-partly-cloudy",
    "moon_cloud": "weather-night-partly-cloudy",
    "sun_rain": "weather-partly-rainy",
    "moon_rain": "weather-partly-rainy",   # MDI has no partly-rainy night glyph
    "rain": "weather-pouring",
    "snow": "weather-snowy",
    "sleet": "weather-snowy-rainy",
    "thunder": "weather-lightning",
    "fog": "weather-fog",
}


def svg(key, size=64, cls="wxi"):
    """An icon in both sets: our inline SVG, plus the MDI glyph beside it.

    Both are emitted and CSS shows one, because the icon is baked server-side and
    the theme is chosen in the browser. The wrapper is `display: contents`, so
    every existing rule that targets the `svg` directly still matches and the
    layout is unchanged in the three themes that use the drawn set.
    """
    mdi = MDI.get(key, "weather-cloudy")
    return (f'<span class="ico">{_svg_only(key, size, cls)}'
            f'<i class="mdi mdi-{mdi}" style="font-size:{size}px" aria-hidden="true"></i>'
            f'</span>')


def _svg_only(key, size=64, cls="wxi"):
    """Inline SVG for an icon key, drawn in a 64x64 viewBox."""
    b = []
    if key == "sun":
        b.append(_sun(32, 32, 13))
    elif key == "moon":
        b.append(_moon(34, 32, 14))
    elif key == "cloud":
        b.append(_cloud(11, 18, 1.05, CLOUD))
    elif key == "sun_cloud":
        b.append(_sun(23, 22, 9.5, color=SUN_PALE))
        b.append(_cloud(15, 23, 0.95, CLOUD))
    elif key == "moon_cloud":
        b.append(_moon(26, 22, 10))
        b.append(_cloud(15, 23, 0.95, CLOUD))
    elif key == "sun_rain":
        b.append(_sun(23, 19, 8.5, color=SUN_PALE))
        b.append(_cloud(13, 20, 0.92, CLOUD))
        b.append(_drops([(24, 48), (34, 48)]))
    elif key == "moon_rain":
        b.append(_moon(26, 19, 9))
        b.append(_cloud(13, 20, 0.92, CLOUD))
        b.append(_drops([(24, 48), (34, 48)]))
    elif key == "rain":
        b.append(_cloud(11, 14, 1.05, CLOUD_DK))
        b.append(_drops([(20, 46), (30, 46), (40, 46)]))
    elif key == "thunder":
        b.append(_cloud(11, 12, 1.05, CLOUD_DK))
        b.append(f'<path d="M34,42 L26,54 L32,54 L28,63 L40,49 L33,49 Z" fill="{BOLT}"/>')
        b.append(_drops([(20, 46)]))
    elif key == "snow":
        b.append(_cloud(11, 14, 1.05, CLOUD_DK))
        b.append(_flakes([(20, 45), (30, 45), (40, 45)]))
    elif key == "sleet":
        b.append(_cloud(11, 14, 1.05, CLOUD_DK))
        b.append(_drops([(21, 46), (37, 46)]))
        b.append(_flakes([(29, 45)]))
    elif key == "fog":
        b.append(_cloud(11, 12, 1.0, CLOUD))
        b.append("".join(
            f'<line class="wxfog" x1="{14 + (i % 2) * 4}" y1="{46 + i * 7}" x2="{50 - (i % 2) * 5}" '
            f'y2="{46 + i * 7}" stroke="{FOG}" stroke-width="3.2" stroke-linecap="round"/>'
            for i in range(2)))
    else:
        b.append(_cloud(11, 18, 1.05, CLOUD))
    return (f'<svg class="{cls}" viewBox="0 0 64 64" width="{size}" height="{size}" '
            f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{"".join(b)}</svg>')


ALL_KEYS = ["sun", "moon", "sun_cloud", "moon_cloud", "cloud", "sun_rain",
            "moon_rain", "rain", "thunder", "snow", "sleet", "fog"]
