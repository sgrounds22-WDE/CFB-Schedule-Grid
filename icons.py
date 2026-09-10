#!/usr/bin/env python3
"""
Icon generation, with no third-party imaging library.

iOS ignores SVG and emoji for home-screen icons — it wants a real PNG at a real
size. Rather than add Pillow (and a pip install to every environment this runs
in), this writes PNGs directly: zlib and struct are all a truecolour PNG needs.

The mark is a miniature of the app itself — offset coloured bars on a dark
field, the way the schedule grid looks at a glance.
"""

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


def render(size, supersample=3):
    """Draw at 3x and box-filter down, which is cheap anti-aliasing."""
    s = size * supersample
    big = [BG] * (s * s)

    for fy, fx0, fx1, colour in BARS:
        y0, y1 = fy * s, (fy + BAR_H) * s
        x0, x1 = fx0 * s, fx1 * s
        r = RADIUS * s
        for py in range(max(0, int(y0)), min(s, int(y1) + 1)):
            for px in range(max(0, int(x0)), min(s, int(x1) + 1)):
                if _rounded(px, py, x0, y0, x1, y1, r):
                    big[py * s + px] = colour

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


def build(outdir, sizes=(32, 180, 192, 512)):
    """Write each icon size; returns the filenames written."""
    import os
    written = []
    for size in sizes:
        name = f"icon-{size}.png"
        write_png(os.path.join(outdir, name), render(size), size, size)
        written.append(name)
    return written


if __name__ == "__main__":
    import sys
    print(build(sys.argv[1] if len(sys.argv) > 1 else "."))
