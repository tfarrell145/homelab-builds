#!/usr/bin/env python3
"""App icons for the weather page, drawn from scratch with the standard library.

The rig has no Pillow and no ImageMagick and is not going to grow either, so this
writes PNGs the hard way: raw RGB scanlines, zlib-deflated, wrapped in the four
chunks a PNG needs. Cheap enough that regenerating costs nothing.

The mark is a sun low over a ridge line, drawn in the retro theme's palette, so the home screen matches the theme the page is
actually used in: the mauve-to-tan dusk sky quantised into hard CRT bands, flat
fills, no soft glow anywhere, and a heavy black keyline around everything.
"""
import math
import struct
import zlib

# Bumped whenever the artwork changes. write_icons() compares it against a sidecar
# and redraws when they differ -- the old "write only if missing" check meant a
# palette change silently never reached the disk.
DESIGN = 2

# Straight out of the retro theme's tokens in render.py. --bg-img is already a dusk
# gradient (deep violet down through mauve into a warm tan), which is the whole
# reason this mark works in the palette at all.
SKY_STOPS = [(0.00, (0x4A, 0x3A, 0x6B)),
             (0.42, (0x6E, 0x55, 0x80)),
             (0.78, (0xA2, 0x72, 0x6C)),
             (1.00, (0xB9, 0x8A, 0x63))]
SUN = (0xFF, 0xD8, 0x4D)         # --accent
SUN_LOW = (0xFF, 0x9E, 0x3D)     # the warm end of --rule
INK = (0x10, 0x10, 0x10)         # --icon-stroke
RIDGE = (0x24, 0x1B, 0x44)       # --head-bg
RIDGE_RIM = (0xFF, 0xD8, 0x4D)   # --accent


def _lerp(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _sky(t):
    """The dusk gradient sampled at normalised height t."""
    if t <= SKY_STOPS[0][0]:
        return SKY_STOPS[0][1]
    for (a, ca), (b, cb) in zip(SKY_STOPS, SKY_STOPS[1:]):
        if a <= t <= b:
            return _lerp(ca, cb, (t - a) / (b - a))
    return SKY_STOPS[-1][1]


def _ridge_y(xn, size):
    """Ridge silhouette height at normalised x, as a pixel row."""
    base = 0.72 if size <= 48 else 0.62
    h = (base
         + 0.055 * math.sin(xn * math.pi * 1.6 + 0.7)
         + 0.030 * math.sin(xn * math.pi * 3.7 + 2.1)
         + 0.014 * math.sin(xn * math.pi * 7.3))
    return h * size


def _pixel(x, y, size):
    xn, yn = x / size, y / size
    # At favicon sizes the full composition turns to mud, so the sun grows, sits
    # higher, and the detail bands are dropped until the mark still reads at 32px.
    small = size <= 48
    r_frac = 0.30 if small else 0.212
    cy_frac = 0.40 if small else 0.455
    cx, cy, r = size * 0.50, size * cy_frac, size * r_frac

    ridge_ink = max(1.0, size * 0.030)      # black keyline along the crest
    rim = max(1.0, size * 0.022)            # lit edge above it
    horizon = 0.72 if small else 0.62       # where _ridge_y sits on average
    ry = _ridge_y(xn, size)

    if y >= ry:
        d = y - ry
        # Lit crest, then keyline, then a flat silhouette. Hard steps, not a ramp:
        # retro's marks are flat fills with a heavy outline, never a gradient.
        if small:
            return INK if d < ridge_ink else RIDGE
        if d < rim:
            return RIDGE_RIM
        if d < rim + ridge_ink:
            return INK
        return RIDGE

    # The sky is quantised into hard horizontal bands -- the CRT banding the retro
    # panels carry, and the thing that most immediately reads as "not the dark icon".
    # The gradient is compressed into the sky that is actually visible. Sampled over
    # the full height instead, its warm tan end sits entirely behind the ridge and
    # the mark reads as flatly purple -- half the palette never reaches the screen.
    bands = 5 if small else 9
    t = min(1.0, yn / horizon)
    col = _sky((math.floor(t * bands) + 0.5) / bands)

    d = math.hypot(x - cx, y - cy)
    ring = max(1.0, size * (0.055 if small else 0.038))
    if d <= r + ring:
        if d <= r:
            # Two flat tones rather than a radial blend: the lower third of the disc
            # takes the warm tone, which keeps it reading as a setting sun.
            face = SUN_LOW if (y - cy) > r * 0.34 else SUN
            if d > r - 1.0:                 # a single pixel of edge softening
                return _lerp(face, INK, (d - (r - 1.0)))
            return face
        if d > r + ring - 1.0:
            return _lerp(INK, col, (d - (r + ring - 1.0)))
        return INK
    return col


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_bytes(size):
    rows = bytearray()
    for y in range(size):
        rows.append(0)                      # filter type 0 (None)
        for x in range(size):
            rows.extend(_pixel(x, y, size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)   # 8-bit truecolour
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + _chunk(b"IEND", b""))


def ico_bytes(size):
    """A .ico wrapping a PNG.

    The format allows an entry's payload to be a whole PNG file rather than a DIB,
    which every browser since IE11 reads, and which means no second encoder here.
    """
    png = png_bytes(size)
    offset = 6 + 16                                     # ICONDIR + one ICONDIRENTRY
    dim = size if size < 256 else 0                     # 0 encodes 256
    header = struct.pack("<HHH", 0, 1, 1)               # reserved, type=icon, count
    entry = struct.pack("<BBBBHHII", dim, dim,
                        0, 0,                           # palette size, reserved
                        1, 32,                          # colour planes, bits per px
                        len(png), offset)
    return header + entry + png


SIZES = {"icon-32.png": 32, "icon-180.png": 180, "icon-192.png": 192, "icon-512.png": 512}

# The names iOS and Safari probe at the site root on their own, regardless of what
# the page's <link> tags say. They are requested WITHOUT a query string, so the
# ?v= cache-busting on the tags does nothing for them -- when these 404, iOS gives
# up and uses a screenshot of the page as the home-screen icon. The access log had
# been recording exactly those 404s.
ALIASES = {"apple-touch-icon.png": 180, "apple-touch-icon-precomposed.png": 180}
ICO = {"favicon.ico": 32}
STAMP = "icons.design"


def write_icons(outdir):
    """Redraw when a file is missing or the artwork version has moved on."""
    stamp = outdir / STAMP
    try:
        current = int(stamp.read_text().strip())
    except (OSError, ValueError):
        current = 0
    stale = current != DESIGN

    made = []
    for name, size in list(SIZES.items()) + list(ALIASES.items()):
        p = outdir / name
        if stale or not p.exists():
            p.write_bytes(png_bytes(size))
            made.append(name)
    for name, size in ICO.items():
        p = outdir / name
        if stale or not p.exists():
            p.write_bytes(ico_bytes(size))
            made.append(name)
    if made:
        stamp.write_text(str(DESIGN))
    return made


if __name__ == "__main__":
    import pathlib, sys
    d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    d.mkdir(parents=True, exist_ok=True)
    for name, size in list(SIZES.items()) + list(ALIASES.items()):
        (d / name).write_bytes(png_bytes(size))
        print(f"{name}  {size}x{size}  {(d / name).stat().st_size} bytes")
    for name, size in ICO.items():
        (d / name).write_bytes(ico_bytes(size))
        print(f"{name}  {size}x{size}  {(d / name).stat().st_size} bytes")
