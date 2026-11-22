#!/usr/bin/env python3
"""THE WORLD IN A DAY -- front page for Sunday 22 November 2026.

This program paints a complete newspaper front page using nothing but
code: a small software rasterizer, a hand-drawn 5x7 bitmap typeface and
a home-grown PNG writer built on zlib. It reads no files, touches no
network and uses only the Python 3.13 standard library.

The page reports the day's verified headlines: the COP31 climate
summit in Antalya ending with no deal, a Russian drone strike on a
Kyiv-region apartment block, Iranian strikes at US positions in
Bahrain, the Nigeria funeral-boat toll, the Cikande factory fire and
a cargo ship ablaze in the Gulf of Finland.

Output: $MAKEFUN_OUTPUT_DIR/entry.png (default /output).
The drawing is fully deterministic: two runs write identical bytes.
"""

import math
import os
import struct
import zlib

PAGE_W = 1024
PAGE_H = 1024

# ---------------------------------------------------------------- palette
COL = {
    "paper": (248, 244, 233),   # warm newsprint
    "ink": (24, 22, 20),        # body ink
    "red": (172, 30, 28),       # accent red
    "navy": (28, 62, 128),      # section navy
    "gold": (192, 148, 34),     # badge gold
    "grey": (110, 108, 100),    # caption grey
    "rule": (208, 204, 192),    # pale rule
    "sea": (170, 198, 218),     # scene sky / sea
    "land": (52, 128, 66),      # globe landmass
    "smoke": (148, 146, 142),   # smoke grey
    "flame": (224, 104, 26),    # fire orange
    "white": (255, 255, 255),
    "black": (8, 8, 8),
}


# ------------------------------------------------------------------- sheet
class Sheet:
    """A flat RGB pixel buffer with primitive drawing operations."""

    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)
        self.box(0, 0, w, h, bg)

    def dot(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = c[0]
            self.buf[i + 1] = c[1]
            self.buf[i + 2] = c[2]

    def box(self, x, y, w, h, c):
        xa = max(0, x)
        ya = max(0, y)
        xb = min(self.w, x + w)
        yb = min(self.h, y + h)
        if xa >= xb or ya >= yb:
            return
        row = bytes(c) * (xb - xa)
        for yy in range(ya, yb):
            start = (yy * self.w + xa) * 3
            self.buf[start:start + len(row)] = row

    def frame(self, x, y, w, h, c, t=2):
        self.box(x, y, w, t, c)
        self.box(x, y + h - t, w, t, c)
        self.box(x, y, t, h, c)
        self.box(x + w - t, y, t, h, c)

    def seg(self, x0, y0, x1, y1, c, t=1):
        # integer Bresenham walk from (x0, y0) to (x1, y1)
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            if t <= 1:
                self.dot(x, y, c)
            else:
                self.box(x - t // 2, y - t // 2, t, t, c)
            if x == x1 and y == y1:
                return
            e2 = err * 2
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def disc(self, cx, cy, r, c):
        r2 = r * r
        for dy in range(-r, r + 1):
            span = int(math.sqrt(r2 - dy * dy))
            self.box(cx - span, cy + dy, span * 2 + 1, 1, c)

    def ring(self, cx, cy, r, c, t=2):
        for k in range(t):
            rr = r - k
            for step in range(720):
                a = math.radians(step / 2.0)
                self.dot(cx + int(rr * math.cos(a)),
                         cy + int(rr * math.sin(a)), c)

    def poly(self, pts, c):
        # scanline fill, even-odd rule
        top = max(0, min(p[1] for p in pts))
        bot = min(self.h - 1, max(p[1] for p in pts))
        n = len(pts)
        for y in range(top, bot + 1):
            hits = []
            for i in range(n):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % n]
                if (ay <= y < by) or (by <= y < ay):
                    hits.append(ax + (y - ay) * (bx - ax) / (by - ay))
            hits.sort()
            for j in range(0, len(hits) - 1, 2):
                xa = int(hits[j])
                xb = int(hits[j + 1])
                self.box(xa, y, xb - xa + 1, 1, c)

    def tri(self, p, q, r, c):
        self.poly([p, q, r], c)


# -------------------------------------------------------------------- font
# A 5x7 bitmap typeface. Each glyph is seven strings of five cells;
# '#' marks an inked cell, '.' leaves the paper showing.
GLYPHS = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".####", "#....", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#..##", "#.#.#", "##..#", "#...#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", "..#..", "..#..", "..#.."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    ",": (".....", ".....", ".....", ".....", ".##..", ".##..", ".#..."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    ";": (".....", ".##..", ".##..", ".....", ".##..", ".##..", ".#..."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "/": ("....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."),
    "%": ("##..#", "##.#.", "...#.", "..#..", ".#...", "#.##.", "#..##"),
    "'": ("..#..", "..#..", ".#...", ".....", ".....", ".....", "....."),
    '"': (".#.#.", ".#.#.", ".#.#.", ".....", ".....", ".....", "....."),
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    "&": (".##..", "#..#.", "#..#.", ".#...", "#.#.#", "#..#.", ".##.#"),
    "$": ("..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    "=": (".....", ".....", "#####", ".....", "#####", ".....", "....."),
    "*": (".....", ".#.#.", ".###.", "#####", ".###.", ".#.#.", "....."),
    "\u2022": (".....", ".....", ".##..", ".##..", ".....", ".....", "....."),
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
}

EMPTY_GLYPH = (".....",) * 7


def measure(s, scale):
    """Pixel width of a string at the given integer scale."""
    if not s:
        return 0
    return len(s) * 6 * scale - scale


def stamp(sh, x, y, s, scale, colour):
    """Draw one line of text with its top-left corner at (x, y)."""
    pen = x
    for ch in s:
        rows = GLYPHS.get(ch, EMPTY_GLYPH)
        for r in range(7):
            line = rows[r]
            for cx in range(5):
                if line[cx] == "#":
                    sh.box(pen + cx * scale, y + r * scale, scale, scale, colour)
        pen += 6 * scale


def stamp_mid(sh, centre_x, y, s, scale, colour):
    stamp(sh, centre_x - measure(s, scale) // 2, y, s, scale, colour)


def wrap_lines(s, limit):
    """Greedy word wrap to at most `limit` characters per line."""
    out = []
    for para in s.split("\n"):
        cur = ""
        for word in para.split(" "):
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= limit:
                cur = cur + " " + word
            else:
                out.append(cur)
                cur = word
        if cur:
            out.append(cur)
    return out


def stamp_block(sh, x, y, s, scale, colour, limit, leading):
    """Draw wrapped text; returns the y just below the last line."""
    lines = wrap_lines(s, limit)
    for i, ln in enumerate(lines):
        stamp(sh, x, y + i * leading, ln, scale, colour)
    return y + len(lines) * leading


# ------------------------------------------------------------------ scenes
def scene_summit(sh, x, y, w, h):
    """Lead picture: a cracked globe above a conference table of
    delegates -- the Antalya summit that could not agree."""
    ink = COL["ink"]
    sh.box(x, y, w, h, (226, 232, 236))
    # hanging placard naming the summit
    sh.box(x + w - 128, y + 10, 116, 30, COL["white"])
    sh.frame(x + w - 128, y + 10, 116, 30, ink, 2)
    stamp_mid(sh, x + w - 70, y + 16, "COP31", 2, COL["red"])
    # the globe, split by a jagged crack
    gx, gy, gr = x + 128, y + 82, 56
    sh.disc(gx, gy, gr, COL["navy"])
    sh.disc(gx - 22, gy - 16, 17, COL["land"])
    sh.disc(gx + 14, gy + 6, 20, COL["land"])
    sh.disc(gx + 26, gy - 30, 11, COL["land"])
    sh.disc(gx - 6, gy + 34, 12, COL["land"])
    sh.ring(gx, gy, gr, ink, 2)
    crack = [(gx - 30, gy - gr + 4), (gx - 12, gy - 26), (gx - 20, gy - 4),
             (gx + 2, gy + 14), (gx - 6, gy + 32), (gx + 10, gy + gr - 4)]
    for i in range(len(crack) - 1):
        sh.seg(crack[i][0], crack[i][1], crack[i + 1][0], crack[i + 1][1],
               COL["paper"], 4)
        sh.seg(crack[i][0] + 3, crack[i][1], crack[i + 1][0] + 3,
               crack[i + 1][1], ink, 1)
    # two flag poles flanking the globe
    for fx in (x + 216, x + 240):
        sh.seg(fx, y + 18, fx, y + 108, ink, 2)
    sh.poly([(x + 216, y + 18), (x + 240, y + 24), (x + 216, y + 34)], COL["red"])
    sh.poly([(x + 240, y + 18), (x + 264, y + 24), (x + 240, y + 34)], COL["gold"])
    # conference table with a row of delegates
    table_y = y + h - 40
    sh.box(x + 12, table_y, w - 24, 10, (96, 74, 52))
    sh.box(x + 12, table_y + 10, w - 24, h - (table_y - y) - 10, (70, 54, 40))
    heads = 9
    for i in range(heads):
        hx = x + 44 + i * ((w - 88) // (heads - 1))
        sh.disc(hx, table_y - 14, 9, (216, 178, 140))
        sh.box(hx - 11, table_y - 6, 22, 7, COL["navy"] if i % 2 else COL["ink"])
        sh.box(hx - 8, table_y + 2, 16, 5, COL["white"])  # nameplate


def icon_drone(sh, x, y, s):
    """Quadcopter drone seen from the front."""
    ink = COL["ink"]
    cx, cy = x + s // 2, y + s // 2
    for (ox, oy) in ((-11, -9), (11, -9), (-11, 9), (11, 9)):
        sh.seg(cx, cy, cx + ox, cy + oy, ink, 2)
        sh.ring(cx + ox, cy + oy, 5, ink, 2)
    sh.box(cx - 6, cy - 4, 12, 8, COL["red"])
    sh.disc(cx, cy + 8, 3, ink)


def icon_missile(sh, x, y, s):
    """A missile climbing diagonally with a flame tail."""
    ink = COL["ink"]
    sh.seg(x + 10, y + s - 8, x + s - 10, y + 8, ink, 5)
    sh.tri((x + s - 10, y + 8), (x + s - 16, y + 16), (x + s - 4, y + 18),
           COL["red"])
    sh.tri((x + 12, y + s - 14), (x + 6, y + s - 2), (x + 18, y + s - 4),
           ink)
    sh.tri((x + 10, y + s - 8), (x + 2, y + s - 2), (x + 6, y + s - 14),
           COL["flame"])
    sh.tri((x + 10, y + s - 8), (x + 12, y + s - 16), (x + 4, y + s - 12),
           COL["gold"])


def icon_boat(sh, x, y, s):
    """A small boat on wavy water."""
    ink = COL["ink"]
    sh.poly([(x + 3, y + 16), (x + s - 3, y + 16), (x + s - 8, y + 24),
             (x + 8, y + 24)], COL["red"])
    sh.seg(x + s // 2, y + 16, x + s // 2, y + 4, ink, 2)
    sh.tri((x + s // 2, y + 4), (x + s // 2, y + 14), (x + s // 2 + 8, y + 14),
           COL["gold"])
    for wx in (x + 2, x + 12, x + 22):
        sh.seg(wx, y + s - 3, wx + 4, y + s - 6, COL["navy"], 2)
        sh.seg(wx + 4, y + s - 6, wx + 8, y + s - 3, COL["navy"], 2)


def icon_flame(sh, x, y, s):
    """A three-layer flame."""
    cx = x + s // 2
    sh.tri((x + 5, y + s - 4), (x + s - 5, y + s - 4), (cx, y + 2),
           COL["flame"])
    sh.tri((x + 9, y + s - 4), (x + s - 9, y + s - 4), (cx, y + 10),
           COL["red"])
    sh.tri((x + 12, y + s - 4), (x + s - 12, y + s - 4), (cx, y + 17),
           COL["gold"])


# -------------------------------------------------------------------- page
def panel(sh, x, y, w, h, kicker, headline, body, icon):
    """One boxed news panel: red rule, kicker, icon, headline, body."""
    ink = COL["ink"]
    sh.box(x, y, w, h, COL["white"])
    sh.frame(x, y, w, h, ink, 2)
    sh.box(x, y, w, 4, COL["red"])
    pad = 12
    stamp(sh, x + pad, y + 12, kicker, 2, COL["red"])
    icon(sh, x + w - pad - 30, y + 6, 30)
    hy = y + 36
    for i, ln in enumerate(headline):
        stamp(sh, x + pad, hy + i * 24, ln, 3, ink)
    by = hy + len(headline) * 24 + 8
    stamp_block(sh, x + pad, by, body, 2, ink, 30, 18)


def compose():
    """Assemble the whole front page and return the finished Sheet."""
    ink = COL["ink"]
    sh = Sheet(PAGE_W, PAGE_H, COL["paper"])

    # ---- masthead
    sh.box(0, 0, PAGE_W, 10, COL["red"])
    stamp_mid(sh, PAGE_W // 2, 26, "THE WORLD IN A DAY", 8, ink)
    stamp_mid(sh, PAGE_W // 2, 92, "SUNDAY 22 NOVEMBER 2026", 4, COL["red"])
    sh.box(20, 126, PAGE_W - 40, 3, ink)
    sh.box(20, 132, PAGE_W - 40, 1, ink)

    # ---- lead story: the COP31 collapse (left, tall)
    lx, ly, lw, lh = 20, 144, 576, 684
    sh.box(lx, ly, lw, lh, COL["white"])
    sh.frame(lx, ly, lw, lh, ink, 2)
    stamp(sh, lx + 14, ly + 12, "ANTALYA, TURKIYE - CLIMATE", 2, COL["red"])
    stamp(sh, lx + 14, ly + 36, "COP31 ENDS", 5, ink)
    stamp(sh, lx + 14, ly + 76, "WITH NO DEAL", 5, ink)
    stamp(sh, lx + 14, ly + 122, "SUMMIT COLLAPSES OVER FOSSIL FUELS", 2, ink)
    scene_summit(sh, lx + 14, ly + 150, lw - 28, 170)
    stamp(sh, lx + 14, ly + 328,
          "DELEGATES AFTER THE FINAL PLENARY BROKE UP.", 2,
          COL["grey"])
    lead_body = (
        "THE UN CLIMATE SUMMIT IN ANTALYA ENDED ON SUNDAY WITH NO "
        "AGREEMENT, AFTER TALKS RAN TWO DAYS INTO OVERTIME. THE EU, "
        "BRITAIN AND OTHERS FORMALLY REJECTED THE FINAL DRAFT BECAUSE "
        "IT NEVER MENTIONED FOSSIL FUELS. OIL STATES LED BY SAUDI "
        "ARABIA OPPOSED ANY PHASE-OUT LANGUAGE. NO TARGET WAS AGREED "
        "TO TRIPLE ADAPTATION FINANCE. IT IS THE FIRST COP TO END "
        "WITH NO DEAL SINCE THE HAGUE IN 2000."
    )
    stamp_block(sh, lx + 14, ly + 356, lead_body, 2, ink, 46, 18)
    # the summit in numbers
    nx, ny, nw, nh = lx + 14, ly + 556, lw - 28, 112
    sh.box(nx, ny, nw, nh, COL["paper"])
    sh.frame(nx, ny, nw, nh, ink, 2)
    stamp_mid(sh, nx + nw // 2, ny + 10, "THE SUMMIT IN NUMBERS", 2, COL["red"])
    stamp_mid(sh, nx + nw // 2, ny + 36, "NEARLY 200 COUNTRIES - 13 DAYS", 3, ink)
    stamp_mid(sh, nx + nw // 2, ny + 66, "FIRST NO-DEAL COP SINCE 2000", 3, ink)

    # ---- four panels down the right-hand column
    px, pw, ph, gap = 612, 392, 168, 8
    stories = [
        ("UKRAINE - WAR",
         ["DRONE HIT FLATTENS", "FLATS NEAR KYIV"],
         "A RUSSIAN DRONE STRUCK A FIVE-STOREY BLOCK IN DYMER. "
         "14 PEOPLE UNACCOUNTED FOR; 9 PULLED OUT.",
         icon_drone),
        ("BAHRAIN - MIDEAST",
         ["IRAN HITS US BASES"],
         "IRAN'S GUARDS FIRED MISSILES AND DRONES AT US POSITIONS "
         "IN BAHRAIN. BAHRAIN SAYS THEY WERE INTERCEPTED; A CIVIL "
         "PLANT CAUGHT FIRE.",
         icon_missile),
        ("NIGERIA - AFRICA",
         ["FUNERAL BOAT TOLL", "RISES TO 24"],
         "A CROWDED BOAT CARRYING MOURNERS TO A FUNERAL CAPSIZED "
         "IN BAYELSA STATE. 24 BODIES FOUND; 24 RESCUED.",
         icon_boat),
        ("INDONESIA - ASIA",
         ["FACTORY FIRE:", "DOZENS MISSING"],
         "RESCUERS SEARCH A BURNT-OUT CANDY FACTORY IN CIKANDE. "
         "AT LEAST 3 DEAD, DOZENS MISSING.",
         icon_flame),
    ]
    for i, (kicker, headline, body, icon) in enumerate(stories):
        panel(sh, px, 144 + i * (ph + gap), pw, ph, kicker, headline, body, icon)

    # ---- bottom strip: the burning cargo ship
    sy = 840
    sh.box(20, sy, PAGE_W - 40, 72, COL["white"])
    sh.frame(20, sy, PAGE_W - 40, 72, ink, 2)
    stamp(sh, 34, sy + 12, "BALTIC", 3, COL["red"])
    stamp(sh, 34, sy + 36, "SHIP FIRE", 3, COL["red"])
    strip = ("A RUSSIA-BOUND CARGO SHIP CAUGHT FIRE IN THE GULF OF "
             "FINLAND AFTER A SUSPECTED UKRAINIAN DRONE STRIKE.")
    stamp_block(sh, 210, sy + 14, strip, 2, ink, 62, 20)

    # ---- ticker along the foot of the page
    ty = 924
    sh.box(20, ty, PAGE_W - 40, 84, COL["black"])
    stamp(sh, 34, ty + 12,
          "ALSO SUNDAY: GULF MARKETS FALL \u2022 SAUDI FORCES DOWN HOUTHI MISSILE",
          2, COL["white"])
    stamp(sh, 34, ty + 34,
          "EU ADDS 1BN EUROS AID FOR UKRAINE \u2022 JEWELLER PAOLO BULGARI DIES AT 89",
          2, COL["white"])
    stamp(sh, 34, ty + 56,
          "OKINAWA MARKS SHURI CASTLE HALL RESTORED, 7 YEARS AFTER THE FIRE",
          2, COL["white"])
    return sh


# --------------------------------------------------------------------- png
def _chunk(tag, payload):
    body = tag + payload
    return (struct.pack(">I", len(payload)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


def png_bytes(w, h, rgb):
    """Encode an RGB buffer as a PNG with one IDAT, filter 0 rows."""
    stride = w * 3
    raw = bytearray()
    for yy in range(h):
        raw.append(0)
        raw += rgb[yy * stride:(yy + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    page = compose()
    data = png_bytes(PAGE_W, PAGE_H, page.buf)
    path = os.path.join(out_dir, "entry.png")
    with open(path, "wb") as fh:
        fh.write(data)
    print("wrote %s (%d bytes)" % (path, len(data)))


if __name__ == "__main__":
    main()
