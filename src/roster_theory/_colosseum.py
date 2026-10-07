"""Original Colosseum character-cell logo, shared by CLI and artwork export.

The geometry was selected by the user on October 6, 2026. No image files,
fonts, dependencies or provider data are needed to render the terminal hero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

WIDTH, HEIGHT = 132, 38
BG = (9, 12, 16)
GOLD = (255, 211, 69)
CREAM = (255, 242, 196)
BRONZE = (132, 102, 50)
DIM = (78, 67, 45)
MUTED = (159, 155, 138)
RGB = tuple[int, int, int]


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


@dataclass(frozen=True)
class Cell:
    char: str = " "
    fg: RGB = GOLD
    bg: RGB = BG


class Canvas:
    def __init__(self, width=WIDTH):
        self.width = min(WIDTH, width)
        self.cells = [[Cell() for _ in range(self.width)] for _ in range(HEIGHT)]
        self.dots: dict[tuple[int, int], RGB] = {}

    def put(self, x, y, char, fg=GOLD, bg=BG):
        if 0 <= x < self.width and 0 <= y < HEIGHT:
            self.cells[y][x] = Cell(char, fg, bg)

    def text(self, x, y, value, color=GOLD):
        for offset, char in enumerate(value):
            self.put(x + offset, y, char, color)

    def center(self, y, value, color=GOLD):
        self.text((self.width - len(value)) // 2, y, value, color)

    def hline(self, x, y, length, color=BRONZE, char="─"):
        self.text(x, y, char * length, color)

    def dot(self, x, y, color=GOLD):
        x = 8 + (x - 8) * (self.width - 8) / (WIDTH - 8)
        ix, iy = round(x), round(y)
        if 0 <= ix < self.width * 2 and 0 <= iy < HEIGHT * 4:
            self.dots[(ix, iy)] = color

    def line(self, a, b, color=GOLD, dash=0):
        x0, y0 = a
        x1, y1 = b
        count = max(1, math.ceil(max(abs(x1 - x0), abs(y1 - y0)) * 1.7))
        for n in range(count + 1):
            if not dash or (n // dash) % 2 == 0:
                self.dot(x0 + (x1 - x0) * n / count, y0 + (y1 - y0) * n / count, color)

    def path(self, points, color=GOLD, closed=False, dash=0):
        for a, b in zip(points, points[1:]):
            self.line(a, b, color, dash)
        if closed:
            self.line(points[-1], points[0], color, dash)

    def ellipse(self, cx, cy, rx, ry, color=GOLD, angle=0.0, start=0.0, end=math.tau, dash=0):
        n = max(40, math.ceil((rx + ry) * (end - start)))
        ca, sa = math.cos(angle), math.sin(angle)
        points = []
        for i in range(n + 1):
            t = start + (end - start) * i / n
            x, y = rx * math.cos(t), ry * math.sin(t)
            points.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
        self.path(points, color, dash=dash)

    def flush(self):
        mapping = {(0, 0): 0, (0, 1): 1, (0, 2): 2, (1, 0): 3,
                   (1, 1): 4, (1, 2): 5, (0, 3): 6, (1, 3): 7}
        for cy in range(HEIGHT):
            for cx in range(self.width):
                bits, colors = 0, []
                for (dx, dy), bit in mapping.items():
                    color = self.dots.get((cx * 2 + dx, cy * 4 + dy))
                    if color is not None:
                        bits |= 1 << bit
                        colors.append(color)
                if bits:
                    colors.sort(key=lambda c: sum(c), reverse=True)
                    top = colors[:max(1, len(colors) // 2)]
                    fg = tuple(round(sum(c[i] for c in top) / len(top)) for i in range(3))
                    self.put(cx, cy, chr(0x2800 + bits), fg)
        self.dots.clear()

    def plain(self):
        def monochrome(cell):
            if cell.char != "▀":
                return cell.char
            top, bottom = cell.fg != BG, cell.bg != BG
            return "█" if top and bottom else "▀" if top else "▄" if bottom else " "
        return "\n".join("".join(monochrome(c) for c in row).rstrip() for row in self.cells) + "\n"

    def ansi(self):
        rows = []
        for row in self.cells:
            parts, current = [], None
            for cell in row:
                state = (cell.fg, cell.bg)
                if state != current:
                    parts.append("\x1b[38;2;{};{};{};48;2;{};{};{}m".format(*cell.fg, *cell.bg))
                    current = state
                parts.append(cell.char)
            rows.append("".join(parts) + "\x1b[0m")
        return "\n".join(rows) + "\n"

GLYPHS = {
    "R": ([(0, 0), (7, 0), (9, 2), (9, 5), (7, 7), (9, 12), (6, 12), (4, 7), (3, 7), (3, 12), (0, 12)],
          [[(3, 2), (6, 2), (7, 3), (7, 4), (6, 5), (3, 5)]]),
    "O": ([(3, 0), (6, 0), (9, 3), (9, 9), (6, 12), (3, 12), (0, 9), (0, 3)],
          [[(3, 2), (6, 2), (7, 3), (7, 9), (6, 10), (3, 10), (2, 9), (2, 3)]]),
    "S": ([(2, 0), (9, 0), (9, 2), (3, 2), (2, 3), (2, 4), (7, 4), (9, 6), (9, 10), (7, 12), (0, 12), (0, 10), (6, 10), (7, 9), (7, 8), (2, 7), (0, 5), (0, 2)], []),
    "T": ([(0, 0), (9, 0), (9, 3), (6, 3), (6, 12), (3, 12), (3, 3), (0, 3)], []),
    "E": ([(0, 0), (9, 0), (9, 2), (3, 2), (3, 5), (8, 5), (8, 7), (3, 7), (3, 10), (9, 10), (9, 12), (0, 12)], []),
    "H": ([(0, 0), (3, 0), (3, 5), (6, 5), (6, 0), (9, 0), (9, 12), (6, 12), (6, 7), (3, 7), (3, 12), (0, 12)], []),
    "Y": ([(0, 0), (3, 0), (3, 4), (4.5, 6), (6, 4), (6, 0), (9, 0), (9, 5), (6, 8), (6, 12), (3, 12), (3, 8), (0, 5)], []),
}

def inside(x, y, polygon):
    result = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            result = not result
        j = i
    return result


def _word(canvas, value, x, y, *, glyph_width, gap):
    pixels = {}
    for index, letter in enumerate(value):
        outer, counters = GLYPHS[letter]
        for py in range(12):
            for px in range(glyph_width):
                sx, sy = (px + 0.5) * 9 / glyph_width, py + 0.5
                if inside(sx, sy, outer) and not any(inside(sx, sy, p) for p in counters):
                    pixels[(index * (glyph_width + gap) + px, py)] = (
                        CREAM if py < 2 else GOLD
                    )
    word_width = len(value) * glyph_width + (len(value) - 1) * gap
    for row in range(6):
        for col in range(word_width):
            top = pixels.get((col, row * 2), BG)
            bottom = pixels.get((col, row * 2 + 1), BG)
            if top != BG or bottom != BG:
                canvas.put(x + col, y + row, "▀", top, bottom)


def _frame(canvas):
    for y, left, right in ((1, "╭─", "─╮"), (HEIGHT - 2, "╰─", "─╯")):
        canvas.hline(3, y, canvas.width - 6, DIM)
        canvas.text(3, y, left, GOLD)
        canvas.text(canvas.width - 5, y, right, GOLD)


def build_logo(width: int = WIDTH) -> Canvas:
    """Build the approved stadium at 100–132 columns without cropping."""
    if width < 100:
        raise ValueError("The Colosseum hero needs at least 100 columns")
    c = Canvas(width)
    _frame(c)
    cx, cy = 132, 58
    rx, ry = 87, 24
    for i in range(6):
        c.ellipse(cx, cy + i * 1.65, rx - i * 0.6, ry - i * 0.2,
                  BRONZE if i else GOLD, start=0, end=math.pi)
    c.ellipse(cx, cy, rx, ry, GOLD)
    c.ellipse(cx, cy - 2, rx - 6, ry - 3, BRONZE)
    c.ellipse(cx, cy - 2, rx - 18, ry - 8, GOLD)
    c.ellipse(cx, cy - 2, rx - 22, ry - 10, BRONZE)
    for ring in range(5):
        c.ellipse(cx, cy + ring * 0.65, rx - 24 - ring * 2.4, ry - 10 - ring * 0.65,
                  mix(BRONZE, GOLD, 0.28))
    for n in range(64):
        t = n * math.tau / 64
        outside = (cx + (rx - 3) * math.cos(t), cy - 1 + (ry - 1) * math.sin(t))
        inside_pt = (cx + (rx - 20) * math.cos(t), cy - 2 + (ry - 9) * math.sin(t))
        c.line(inside_pt, outside, CREAM if n % 8 == 0 else BRONZE)
        if math.sin(t) > 0:
            c.line(outside, (outside[0], outside[1] + 9), DIM)
    for n in range(44):
        t = (n + 0.5) * math.pi / 44
        c.line((cx + rx * math.cos(t), cy + ry * math.sin(t)),
               (cx + (rx - 1) * math.cos(t), cy + ry * math.sin(t) + 9), BRONZE)

    def field(u, v):
        return cx + u * 45 + v * 13, cy + 5 + v * 7 - u * 4

    c.path([field(-1, -1), field(1, -1), field(1, 1), field(-1, 1)], CREAM, closed=True)
    for n in range(11):
        u = -1 + n / 5
        c.line(field(u, -1), field(u, 1), GOLD if n in (0, 5, 10) else BRONZE)
        for v in (-0.35, 0.35):
            c.line(field(u - 0.024, v), field(u + 0.024, v), CREAM)
    c.ellipse(cx, cy + 5, 6, 2, CREAM)
    for tx, ty, sign in ((49, 42, -1), (215, 42, 1), (64, 68, -1), (200, 68, 1)):
        c.line((tx, ty), (tx, ty - 23), BRONZE)
        c.line((tx - sign * 2, ty), (tx - sign * 2, ty - 22), DIM)
        c.path([(tx - 5, ty - 23), (tx + 5, ty - 23), (tx + 5, ty - 27), (tx - 5, ty - 27)], GOLD, closed=True)
        for offset in (-3, 0, 3):
            c.dot(tx + offset, ty - 25, CREAM)
        c.line((tx, ty - 22), (tx - sign * 16, ty - 5), DIM, dash=5)
    c.ellipse(cx, cy + 13, 95, 27, DIM, start=0.12, end=3.02)
    c.line((34, 96), (96, 96), DIM)
    c.line((168, 96), (230, 96), DIM)
    c.ellipse(cx, 98, 6, 1.6, BRONZE)
    c.flush()
    c.center(4, "ROSTER THEORY", MUTED)
    glyph_width, gap = (7, 2) if c.width >= 123 else (6, 1)
    word_width = 6 * glyph_width + 5 * gap
    x = (c.width - (word_width * 2 + 7)) // 2
    _word(c, "ROSTER", x, 26, glyph_width=glyph_width, gap=gap)
    _word(c, "THEORY", x + word_width + 7, 26, glyph_width=glyph_width, gap=gap)
    c.text(x + word_width + 2, 28, "╱", BRONZE)
    c.center(33, "FANTASY FOOTBALL ASSISTANT", MUTED)
    c.center(35, "DRAFT  ◆  TRADE  ◆  WAIVER", GOLD)
    return c


def render_logo(*, width: int, color: bool, unicode: bool) -> str:
    """Render only character cells; the caller owns TTY and suppression policy."""
    canvas = build_logo(width)
    if not unicode:
        replacements = {"╭": "+", "╮": "+", "╰": "+", "╯": "+",
                        "─": "-", "╱": "/", "◆": "*"}
        density = " .:*+##@@"
        for row in canvas.cells:
            for x, cell in enumerate(row):
                if cell.char == "▀":
                    row[x] = Cell("#", GOLD, BG)
                elif 0x2800 <= ord(cell.char) <= 0x28FF:
                    row[x] = Cell(density[(ord(cell.char) - 0x2800).bit_count()],
                                  cell.fg, BG)
                elif cell.char in replacements:
                    row[x] = Cell(replacements[cell.char], cell.fg, BG)
    return (canvas.ansi() if color else canvas.plain()) + "\n"
