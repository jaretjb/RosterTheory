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

# Fixed contours of the preview's mathematical glyphs, in 2048 units/em.
# SVG export reads no font files and embeds no font dependency.
GLYPH_SCALE = 20 / 2048
MATH_PATHS = {
    "∑": (
        "M296,-146L150,-24L601,614L150,1230L312,1362L847,612L296,-146ZM150,-200L150,-24L1070,"
        "-24L1070,-200L150,-200ZM150,1230L150,1420L1050,1420L1050,1230L150,1230Z"
    ),
    "≈": (
        "M100,776L100,856Q100,1029 164,1107.5Q228,1186 370,1186Q443,1186 507.5,1159Q572,1132 "
        "630,1097Q679,1068 722.5,1039.5Q766,1011 813,1011Q858,1011 878,1039.5Q898,1068 898,11"
        "30L898,1220L1100,1220L1100,1140Q1100,967 1043,888.5Q986,810 860,810Q789,810 725,837."
        "5Q661,865 604,899Q553,930 506.5,957.5Q460,985 409,985Q353,985 327.5,956.5Q302,928 30"
        "2,866L302,776L100,776ZM100,196L100,276Q100,449 164,527.5Q228,606 370,606Q443,606 507"
        ".5,579Q572,552 630,517Q679,488 722.5,459.5Q766,431 813,431Q858,431 878,459.5Q898,488"
        " 898,550L898,640L1100,640L1100,560Q1100,387 1043,308.5Q986,230 860,230Q789,230 725,2"
        "57.5Q661,285 604,319Q553,350 506.5,377.5Q460,405 409,405Q353,405 327.5,376.5Q302,348"
        " 302,286L302,196L100,196Z"
    ),
    "∞": (
        "M349,344Q226,344 151.5,443.5Q77,543 77,706Q77,875 151.5,972.5Q226,1070 349,1070Q451,"
        "1070 517,1008.5Q583,947 630,813L570,813Q617,947 683,1008.5Q749,1070 851,1070Q974,107"
        "0 1048.5,972.5Q1123,875 1123,706Q1123,543 1048.5,443.5Q974,344 851,344Q749,344 683,4"
        "05.5Q617,467 570,600L630,600Q583,467 517,405.5Q451,344 349,344ZM398,512Q461,512 494."
        "5,576.5Q528,641 543,741L543,670Q528,775 494,839.5Q460,904 398,904Q337,904 299.5,850."
        "5Q262,797 262,706Q262,619 299.5,565.5Q337,512 398,512ZM801,512Q863,512 900,565.5Q937"
        ",619 937,706Q937,797 900,850.5Q863,904 801,904Q738,904 704.5,839.5Q671,775 656,670L6"
        "56,741Q671,641 704.5,576.5Q738,512 801,512Z"
    ),
    "π": (
        "M968,-20Q821,-20 755.5,58.5Q690,137 690,310L690,1060L902,1060L902,320Q902,241 925.5,"
        "205.5Q949,170 1028,170Q1042,170 1056.5,172Q1071,174 1090,178L1114,-8Q1077,-15 1046,-"
        "17.5Q1015,-20 968,-20ZM228,0L228,1060L440,1060L440,0L228,0ZM60,870L60,1060L1100,1060"
        "L1100,870L60,870Z"
    ),
    "√": (
        "M274,-200L86,401L292,401L401,-20L419,-20L680,1420L876,1420L556,-200L274,-200ZM680,12"
        "30L680,1420L1130,1420L1130,1230L680,1230Z"
    ),
    "×": (
        "M249,188L1079,1065L951,1188L121,309L249,188ZM951,188L1079,309L249,1188L121,1065L951,"
        "188Z"
    ),
    "−": (
        "M100,616L100,802L1100,802L1100,616L100,616Z"
    ),
    "=": (
        "M100,866L100,1052L1100,1052L1100,866L100,866ZM100,366L100,552L1100,552L1100,366L100,"
        "366Z"
    ),
    "∫": (
        "M402,440L402,890Q402,1440 904,1440Q1018,1440 1124,1420L1102,1236Q1039,1244 991,1247Q"
        "943,1250 898,1250Q614,1250 614,900L614,440L402,440ZM78,-477L68,-289L176,-274Q294,-25"
        "7 348,-179Q402,-101 402,62L402,464L614,464L614,94Q614,-95 566,-212Q518,-329 417,-389"
        "Q316,-449 156,-468L78,-477Z"
    ),
    "∂": (
        "M909,325L862,666Q862,1209 228,1236L248,1426Q671,1406 877.5,1204Q1084,1002 1084,614L1"
        "084,526L909,325ZM584,-20Q361,-20 239.5,106Q118,232 118,460Q118,670 219,785Q320,900 5"
        "06,900Q635,900 724.5,839.5Q814,779 844,668L918,668L918,408L1084,526Q1084,265 954,122"
        ".5Q824,-20 584,-20ZM582,164Q722,164 793,233Q864,302 864,440Q864,572 794,644Q724,716 "
        "596,716Q472,716 405,649.5Q338,583 338,460Q338,319 401.5,241.5Q465,164 582,164Z"
    ),
    "λ": (
        "M1068,-20Q938,-20 858,38.5Q778,97 734,251L479,1140Q452,1235 411.5,1272.5Q371,1310 31"
        "3,1310Q286,1310 251,1302L227,1488Q278,1500 333,1500Q461,1500 539,1444Q617,1388 659,1"
        "240L917,340Q944,245 985.5,207.5Q1027,170 1088,170Q1115,170 1150,178L1174,-8Q1123,-20"
        " 1068,-20ZM67,0L526,1108L662,877L527,836Q543,770 541.5,709Q540,648 518,591L294,0L67,"
        "0Z"
    ),
    "δ": (
        "M603,-20Q453,-20 346.5,30.5Q240,81 183,176.5Q126,272 126,406Q126,582 214.5,684Q303,7"
        "86 466,796L466,862L507,806Q400,837 332,877.5Q264,918 232,973Q200,1028 200,1101Q200,1"
        "263 313.5,1351.5Q427,1440 634,1440Q854,1440 1034,1333L932,1170Q805,1250 634,1250Q517"
        ",1250 464.5,1219.5Q412,1189 412,1121Q412,1063 458,1027Q504,991 616,960Q766,919 870.5"
        ",861Q975,803 1029.5,703Q1084,603 1084,436Q1084,293 1026.5,190.5Q969,88 861.5,34Q754,"
        "-20 603,-20ZM605,164Q730,164 800,241Q870,318 870,456Q870,587 795,666.5Q720,746 596,7"
        "46Q481,746 410.5,661Q340,576 340,436Q340,308 410,236Q480,164 605,164Z"
    ),
}



def hex_color(color):
    return "#" + "".join(f"{channel:02x}" for channel in color)


def dots(cell, x, y):
    bits = ord(cell.char) - 0x2800
    for bit, (dx, dy) in enumerate(BRAILLE):
        if bits & (1 << bit):
            yield x + 3 + dx * 6, y + 4 + dy * 4.5


def render_svg(canvas, *, mono=False):
    """Encode stadium dots and mathematical symbols as self-contained geometry."""
    width = canvas.width * CELL_WIDTH + PADDING * 2
    height = HEIGHT * CELL_HEIGHT + PADDING * 2
    shapes = defaultdict(list)
    labels = []
    symbols, used_symbols = [], set()
    for y, row in enumerate(canvas.cells):
        x = 0
        while x < canvas.width:
            cell = row[x]
            sx = x * CELL_WIDTH + PADDING
            sy = y * CELL_HEIGHT + PADDING
            if cell.char in MATH_PATHS:
                used_symbols.add(cell.char)
                color = CREAM if mono else cell.fg
                symbols.append(
                    f'<use href="#math-{ord(cell.char):x}" '
                    f'transform="translate({sx},{sy+18}) '
                    f'scale({GLYPH_SCALE:g},-{GLYPH_SCALE:g})" '
                    f'fill="{hex_color(color)}"/>'
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
                    if following.fg != cell.fg or following.char in MATH_PATHS or (
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
        '  <title id="title">Roster Theory — Colosseum / Mathematical Weave</title>',
        '  <desc id="description">A detailed gold football stadium above ROSTER THEORY '
        'letterforms woven from mathematical symbols. '
        'FANTASY FOOTBALL ASSISTANT. DRAFT, TRADE, WAIVER.</desc>',
        f'  <rect width="{width}" height="{height}" fill="{hex_color(BG)}"/>',
        '  <defs>',
    ]
    for char in sorted(used_symbols):
        lines.append(f'    <path id="math-{ord(char):x}" d="{MATH_PATHS[char]}"/>')
    lines.append('  </defs>')
    for layer in ("stadium", "wordmark"):
        lines.append(f'  <g id="{layer}">')
        for (name, color), paths in shapes.items():
            if name == layer:
                lines.append(f'    <path fill="{hex_color(color)}" d="{"".join(paths)}"/>')
        if layer == "wordmark":
            lines.extend("    " + symbol for symbol in symbols)
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
            if 0x2800 <= ord(cell.char) <= 0x28FF:
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
