#!/usr/bin/env python3
"""
Icon generation, with no third-party imaging library.

iOS ignores SVG and emoji for home-screen icons — it wants a real PNG at a real
size. Rather than add Pillow (and a pip install to every environment this runs
in), this writes PNGs directly: zlib and struct are all a truecolour PNG needs.

The mark is a miniature of the app itself — offset coloured bars on a dark
field, the way the schedule grid looks at a glance.
"""

import math
import struct
import zlib

BG = (13, 35, 64)          # dark navy field
BARS = [
    # (y, x0, x1, colour)  — fractions of the canvas
    (0.215, 0.13, 0.60, (200, 16, 46)),
    (0.395, 0.28, 0.87, (255, 115, 0)),
    (0.575, 0.13, 0.52, (45, 104, 196)),
    (0.755, 0.42, 0.87, (0, 132, 74)),
]
BAR_H = 0.115
RADIUS = 0.028             # bar corner radius, also a fraction

# Which mark to draw. "bars" is the wordless original; "cfb" sets CFB over a
# colour strip; "cfb-schedule" adds the second word underneath.
STYLE = "football"
INK = (255, 255, 255)

# Football colours and geometry. The silhouette is a vesica — the overlap of
# two circles — which gives the pointed ends a plain ellipse cannot.
LEATHER = (150, 78, 42)
LACE = (245, 244, 238)
TILT = -22          # degrees; a level football looks like a rugby ball
BALL_A = 0.335      # half length, fraction of canvas
BALL_B = 0.205      # half height

# A 5x7 bitmap face. Drawing letters as blocks avoids bundling a font file and
# suits the subject — it reads like a stadium scoreboard rather than a logo.
GLYPHS = {
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
}


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path, pixels, w, h):
    """pixels: flat list of (r, g, b) rows, top to bottom."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)                       # filter type 0 for this scanline
        for x in range(w):
            raw.extend(pixels[y * w + x])

    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


# ---------------------------------------------------------------- reading

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)


def read_png(path):
    """Decode a non-interlaced 8-bit RGB/RGBA PNG. Returns (pixels, w, h).

    Deliberately narrow: this only has to read an icon someone exported, not
    every PNG in existence. Anything outside that raises with the fix.
    """
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path} is not a PNG. Export it as PNG and retry.")

    idat, meta, pos = bytearray(), None, 8
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            meta = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + ln

    w, h, depth, ctype, _, _, interlace = meta
    if depth != 8 or ctype not in (2, 6) or interlace:
        raise SystemExit(
            f"{path}: need an 8-bit RGB or RGBA PNG with no interlacing "
            f"(found depth={depth}, colour type={ctype}, interlace={interlace}).\n"
            "Re-export it: in Preview use File > Export, format PNG, "
            "and turn off interlacing if offered.")

    bpp = 3 if ctype == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = w * bpp
    out, prev = [], bytearray(stride)

    for y in range(h):
        i = y * (stride + 1)
        ft = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ft == 1:   line[x] = (line[x] + a) & 0xFF
            elif ft == 2: line[x] = (line[x] + b) & 0xFF
            elif ft == 3: line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
            elif ft == 4: line[x] = (line[x] + _paeth(a, b, c)) & 0xFF
        prev = line
        for x in range(w):
            px = line[x * bpp:x * bpp + bpp]
            if bpp == 4 and px[3] < 255:
                # iOS puts black behind transparency, which looks like a
                # printing error. Composite onto the field colour instead.
                al = px[3] / 255
                out.append(tuple(int(px[k] * al + BG[k] * (1 - al))
                                 for k in range(3)))
            else:
                out.append((px[0], px[1], px[2]))
    return out, w, h


def resize(pixels, sw, sh, size):
    """Box-filter down to a square. Non-square sources are centre-cropped."""
    side = min(sw, sh)
    ox, oy = (sw - side) // 2, (sh - side) // 2
    out = []
    for y in range(size):
        y0, y1 = oy + y * side // size, oy + (y + 1) * side // size
        for x in range(size):
            x0, x1 = ox + x * side // size, ox + (x + 1) * side // size
            r = g = b = n = 0
            for yy in range(y0, max(y1, y0 + 1)):
                row = yy * sw
                for xx in range(x0, max(x1, x0 + 1)):
                    c = pixels[row + xx]
                    r += c[0]; g += c[1]; b += c[2]; n += 1
            out.append((r // n, g // n, b // n))
    return out


# ---------------------------------------------------------------- drawing

def _rounded(px, py, x0, y0, x1, y1, r):
    """Is (px, py) inside the rounded rectangle?"""
    if not (x0 <= px <= x1 and y0 <= py <= y1):
        return False
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r),
                   (x0 + r, y1 - r), (x1 - r, y1 - r)):
        if ((px < x0 + r or px > x1 - r) and (py < y0 + r or py > y1 - r)
                and abs(px - cx) < r and abs(py - cy) < r):
            return (px - cx) ** 2 + (py - cy) ** 2 <= r * r
    return True


def _in_vesica(lx, ly, a, b):
    """Point test for the lens formed by two overlapping circles."""
    r = (b + a * a / b) / 2
    d = r - b
    return (lx * lx + (ly - d) ** 2 <= r * r
            and lx * lx + (ly + d) ** 2 <= r * r)


def _football(big, s, cx, cy, a, b, tilt):
    """Draw a tilted football with laces and the two end stripes."""
    th = math.radians(tilt)
    cos, sin = math.cos(th), math.sin(th)
    reach = int(max(a, b) * 1.15 * s)
    px0, px1 = int(cx * s) - reach, int(cx * s) + reach
    py0, py1 = int(cy * s) - reach, int(cy * s) + reach

    for py in range(max(0, py0), min(s, py1)):
        for px in range(max(0, px0), min(s, px1)):
            # into the ball's own frame
            dx, dy = px / s - cx, py / s - cy
            lx = dx * cos + dy * sin
            ly = -dx * sin + dy * cos
            if not _in_vesica(lx, ly, a, b):
                continue

            colour = LEATHER
            u, v = lx / a, ly / b                 # normalised within the ball

            # two stripes near the ends
            if 0.52 <= abs(u) <= 0.60:
                colour = LACE
            # central lacing: a spine with cross ticks
            if abs(u) <= 0.30 and abs(v) <= 0.055:
                colour = LACE
            if abs(u) <= 0.30 and abs(v) <= 0.26:
                for k in (-3, -1, 1, 3):
                    if abs(u - k * 0.075) <= 0.022:
                        colour = LACE

            big[py * s + px] = colour


def _text(big, s, word, cx, cy, unit, colour):
    """Blit a word centred on (cx, cy). All args are fractions of the canvas."""
    gw = 5 * unit
    total = len(word) * gw + (len(word) - 1) * unit      # one unit between
    x = cx - total / 2
    y = cy - 3.5 * unit
    for ch in word:
        rows = GLYPHS.get(ch)
        if rows:
            for ry, row in enumerate(rows):
                for rx, bit in enumerate(row):
                    if bit == "1":
                        px0 = int((x + rx * unit) * s)
                        px1 = int((x + (rx + 1) * unit) * s)
                        py0 = int((y + ry * unit) * s)
                        py1 = int((y + (ry + 1) * unit) * s)
                        for py in range(max(0, py0), min(s, py1)):
                            row_off = py * s
                            for px in range(max(0, px0), min(s, px1)):
                                big[row_off + px] = colour
        x += gw + unit


def render(size, supersample=3, style=None):
    """Draw at 3x and box-filter down, which is cheap anti-aliasing."""
    style = style or STYLE
    s = size * supersample
    big = [BG] * (s * s)

    if style == "bars":
        bars = BARS
    elif style == "football":
        bars = []
    elif style == "football-bars":
        bars = [(0.795, 0.16, 0.46, BARS[0][3]),
                (0.795, 0.50, 0.84, BARS[1][3])]
    elif style == "cfb":
        # Three short bars as a colour strip beneath the word.
        bars = [(0.66, 0.16, 0.46, BARS[0][3]),
                (0.66, 0.50, 0.84, BARS[1][3]),
                (0.79, 0.30, 0.70, BARS[2][3])]
    else:
        bars = [(0.80, 0.16, 0.46, BARS[0][3]),
                (0.80, 0.50, 0.84, BARS[1][3])]

    for fy, fx0, fx1, colour in bars:
        y0, y1 = fy * s, (fy + BAR_H) * s
        x0, x1 = fx0 * s, fx1 * s
        r = RADIUS * s
        for py in range(max(0, int(y0)), min(s, int(y1) + 1)):
            for px in range(max(0, int(x0)), min(s, int(x1) + 1)):
                if _rounded(px, py, x0, y0, x1, y1, r):
                    big[py * s + px] = colour

    if style == "football":
        _football(big, s, 0.5, 0.5, BALL_A, BALL_B, TILT)
    elif style == "football-bars":
        _football(big, s, 0.5, 0.42, BALL_A * 0.88, BALL_B * 0.88, TILT)
    elif style == "cfb":
        _text(big, s, "CFB", 0.5, 0.36, 0.0365, INK)
    elif style == "cfb-schedule":
        _text(big, s, "CFB", 0.5, 0.30, 0.0330, INK)
        _text(big, s, "SCHEDULE", 0.5, 0.58, 0.0140, INK)

    out = []
    n = supersample * supersample
    for y in range(size):
        for x in range(size):
            r = g = b = 0
            for dy in range(supersample):
                row = (y * supersample + dy) * s + x * supersample
                for dx in range(supersample):
                    c = big[row + dx]
                    r += c[0]; g += c[1]; b += c[2]
            out.append((r // n, g // n, b // n))
    return out


def build(outdir, sizes=(32, 180, 192, 512), source="icon-source.png"):
    """Write each icon size.

    If icon-source.png sits beside build.py it is used; otherwise the built-in
    mark is drawn. Either way every size is generated here, so you only ever
    supply one file.
    """
    import os
    src = None
    if os.path.exists(source):
        src = read_png(source)
        print(f"  icon source: {source} ({src[1]}x{src[2]})")

    written = []
    for size in sizes:
        px = resize(src[0], src[1], src[2], size) if src else render(size)
        name = f"icon-{size}.png"
        write_png(os.path.join(outdir, name), px, size, size)
        written.append(name)
    return written


if __name__ == "__main__":
    import sys
    print(build(sys.argv[1] if len(sys.argv) > 1 else "."))
