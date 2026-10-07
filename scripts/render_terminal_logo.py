"""Regenerate Colosseum SVG artwork from the same cells used by the CLI.

SVG generation uses the standard library. Optional PNG previews require Pillow.
Example: python scripts/render_terminal_logo.py --png data/exports/colosseum.png
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import html
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roster_theory._colosseum import BG, CREAM, HEIGHT, WIDTH, build_logo  # noqa: E402

CELL_WIDTH, CELL_HEIGHT, PADDING = 12, 24, 30
BRAILLE = ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3))


def hex_color(color):
    return "#" + "".join(f"{channel:02x}" for channel in color)


def dots(cell, x, y):
    bits = ord(cell.char) - 0x2800
    for bit, (dx, dy) in enumerate(BRAILLE):
        if bits & (1 << bit):
            yield x + 3 + dx * 6, y + 4 + dy * 4.5


def render_svg(canvas, *, mono=False):
    """Encode stadium dots and headline blocks as font-independent geometry."""
    width = canvas.width * CELL_WIDTH + PADDING * 2
    height = HEIGHT * CELL_HEIGHT + PADDING * 2
    shapes = defaultdict(list)
    labels = []
    for y, row in enumerate(canvas.cells):
        x = 0
        while x < canvas.width:
            cell = row[x]
            sx = x * CELL_WIDTH + PADDING
            sy = y * CELL_HEIGHT + PADDING
            if cell.char == "▀":
                for dy, color in ((0, cell.fg), (CELL_HEIGHT / 2, cell.bg)):
                    if color != BG:
                        color = CREAM if mono else color
                        shapes[("wordmark", color)].append(
                            f"M{sx},{sy+dy:g}h{CELL_WIDTH}v{CELL_HEIGHT/2:g}h-{CELL_WIDTH}z"
                        )
            elif 0x2800 <= ord(cell.char) <= 0x28FF:
                color = CREAM if mono else cell.fg
                for dx, dy in dots(cell, sx, sy):
                    shapes[("stadium", color)].append(
                        f"M{dx-1:g},{dy:g}a1,1 0 1,0 2,0a1,1 0 1,0 -2,0"
                    )
            elif cell.char != " ":
                # Keep complete accessible labels as text, rather than emitting
                # one text element per character. textLength preserves cells.
                run = cell.char
                while x + len(run) < canvas.width:
                    following = row[x + len(run)]
                    if following.fg != cell.fg or following.char == "▀" or (
                        0x2800 <= ord(following.char) <= 0x28FF
                    ):
                        break
                    run += following.char
                run = run.rstrip()
                if run:
                    color = CREAM if mono else cell.fg
                    labels.append(
                        f'<text x="{sx}" y="{sy+18}" fill="{hex_color(color)}" '
                        f'textLength="{len(run)*CELL_WIDTH}" lengthAdjust="spacingAndGlyphs">'
                        f'{html.escape(run)}</text>'
                    )
                    x += len(run) - 1
            x += 1
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '  <title id="title">Roster Theory — Colosseum</title>',
        '  <desc id="description">A detailed gold football stadium above the angular '
        'ROSTER THEORY wordmark. FANTASY FOOTBALL ASSISTANT. DRAFT, TRADE, WAIVER.</desc>',
        f'  <rect width="{width}" height="{height}" fill="{hex_color(BG)}"/>',
    ]
    for layer in ("stadium", "wordmark"):
        lines.append(f'  <g id="{layer}">')
        for (name, color), paths in shapes.items():
            if name == layer:
                lines.append(f'    <path fill="{hex_color(color)}" d="{"".join(paths)}"/>')
        lines.append("  </g>")
    lines.append('  <g font-family="Cascadia Mono, Consolas, monospace" font-size="20">')
    lines.extend("    " + line for line in labels)
    lines.extend(["  </g>", "</svg>", ""])
    return "\n".join(lines)


def render_png(canvas, path, *, mono=False, font_path=None):
    from PIL import Image, ImageDraw, ImageFont

    scale = 2
    width = canvas.width * CELL_WIDTH + PADDING * 2
    height = HEIGHT * CELL_HEIGHT + PADDING * 2
    image = Image.new("RGB", (width * scale, height * scale), BG)
    draw = ImageDraw.Draw(image)
    candidates = [font_path, "C:/Windows/Fonts/CascadiaMono.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
    font_path = next((p for p in candidates if p and Path(p).is_file()), None)
    font = (ImageFont.truetype(font_path, 20 * scale) if font_path
            else ImageFont.load_default(size=20 * scale))
    for y, row in enumerate(canvas.cells):
        for x, cell in enumerate(row):
            sx = x * CELL_WIDTH + PADDING
            sy = y * CELL_HEIGHT + PADDING
            if cell.char == "▀":
                for dy, color in ((0, cell.fg), (CELL_HEIGHT / 2, cell.bg)):
                    if color != BG:
                        color = CREAM if mono else color
                        draw.rectangle((sx*scale, (sy+dy)*scale,
                                        (sx+CELL_WIDTH)*scale-1,
                                        (sy+dy+CELL_HEIGHT/2)*scale-1), fill=color)
            elif 0x2800 <= ord(cell.char) <= 0x28FF:
                color = CREAM if mono else cell.fg
                for dx, dy in dots(cell, sx, sy):
                    draw.ellipse(((dx-1)*scale, (dy-1)*scale,
                                  (dx+1)*scale-1, (dy+1)*scale-1), fill=color)
            elif cell.char != " ":
                draw.text((sx*scale, (sy-1)*scale), cell.char, font=font,
                          fill=CREAM if mono else cell.fg)
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", type=Path)
    parser.add_argument("--png", type=Path)
    parser.add_argument("--width", type=int, choices=range(100, WIDTH + 1), default=WIDTH)
    parser.add_argument("--mono", action="store_true")
    parser.add_argument("--font", help="Optional monospace font for PNG captions")
    args = parser.parse_args()
    if not args.svg and not args.png:
        args.svg = ROOT / "docs/assets/roster-theory-colosseum.svg"
    canvas = build_logo(args.width)
    if args.svg:
        args.svg.parent.mkdir(parents=True, exist_ok=True)
        args.svg.write_text(render_svg(canvas, mono=args.mono), encoding="utf-8")
    if args.png:
        render_png(canvas, args.png, mono=args.mono, font_path=args.font)


if __name__ == "__main__":
    main()
