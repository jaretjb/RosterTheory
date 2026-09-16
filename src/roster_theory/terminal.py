"""Standard-library terminal capabilities for local CLI output."""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping


ANSI_RESET = "\x1b[0m"
PALETTE: Mapping[str, str] = {
    "arcade": "\x1b[1;38;5;220m",
    "amber": "\x1b[38;5;214m",
    "cream": "\x1b[38;5;230m",
    "bronze": "\x1b[38;5;137m",
    "ready": "\x1b[32m",
    "degraded": "\x1b[33m",
    "unavailable": "\x1b[31m",
    "muted": "\x1b[2m",
}
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PRODUCT_DESCRIPTOR = "FANTASY FOOTBALL ASSISTANT"
_MODE_SELECT = "DRAFT  /  TRADE  /  WAIVER"


class WidthTier(str, Enum):
    WIDE = "wide"
    STANDARD = "standard"
    COMPACT = "compact"
    NARROW = "narrow"


@dataclass(frozen=True)
class TerminalCapabilities:
    interactive: bool
    redirected: bool
    width: int
    ansi_supported: bool
    color_enabled: bool
    unicode_supported: bool = True

    @property
    def width_tier(self) -> WidthTier:
        if self.width >= 100:
            return WidthTier.WIDE
        if self.width >= 60:
            return WidthTier.STANDARD
        if self.width >= 40:
            return WidthTier.COMPACT
        return WidthTier.NARROW


def styled(text: str, token: str, capabilities: TerminalCapabilities) -> str:
    """Apply a deterministic palette token only when color is safe."""

    color = PALETTE.get(token)
    return f"{color}{text}{ANSI_RESET}" if color and capabilities.color_enabled else text


def visible_width(text: str) -> int:
    """Return terminal width for the project's single-cell glyph vocabulary."""

    return len(_ANSI_RE.sub("", text))


def status_token(status: str) -> str:
    normalized = status.strip().upper()
    if normalized in {"READY", "COMPLETE", "DRAFT-READY"}:
        return "ready"
    if normalized in {"DEGRADED", "UNCALIBRATED", "PARTIAL"}:
        return "degraded"
    return "unavailable"


def sideline_rule(width: int, *, top: bool = True, unicode: bool = True) -> str:
    """Render the arcade cabinet's double-rule/pip motif at an exact width."""

    width = max(8, width)
    if unicode:
        left, right, fill, mark = ("╔", "╗", "═", "◆") if top else ("╚", "╝", "═", "◆")
    else:
        left, right, fill, mark = ("+", "+", "=", "<>")
    inside = width - 2
    if unicode:
        edge = min(3, max(1, inside // 6))
        middle = max(0, inside - (edge * 2) - 2)
        body = fill * edge + mark + fill * middle + mark + fill * edge
    else:
        edge = min(2, max(1, inside // 6))
        middle = max(0, inside - (edge * 2) - 4)
        body = fill * edge + mark + fill * middle + mark + fill * edge
    return (left + body[:inside] + right)[:width]


def _unicode_is_safe(stream: Any, platform_name: str) -> bool:
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return platform_name != "nt"
    try:
        "╔═◆╗".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


_GLYPHS: Mapping[str, tuple[str, ...]] = {
    "R": ("#### ", "#   #", "#### ", "#  # ", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", " ### "),
    "S": (" ####", "#    ", " ### ", "    #", "#### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  "),
    "E": ("#####", "#    ", "#### ", "#    ", "#####"),
    "H": ("#   #", "#   #", "#####", "#   #", "#   #"),
    "Y": ("#   #", " # # ", "  #  ", "  #  ", "  #  "),
}


def _glyph_word(word: str, *, unicode: bool) -> tuple[str, ...]:
    """Draw one word as horizontally doubled cabinet-pixel lettering."""

    ink = "█" if unicode else "#"
    rows: list[str] = []
    for row in range(5):
        letters = []
        for letter in word:
            pixels = "".join(
                ink * 2 if pixel == "#" else "  "
                for pixel in _GLYPHS[letter][row]
            )
            letters.append(pixels)
        rows.append("  ".join(letters).rstrip())
    return tuple(rows)


def _glyph_wordmark(*, unicode: bool) -> tuple[str, ...]:
    separator = "◆" if unicode else "<>"
    return (
        *_glyph_word("ROSTER", unicode=unicode),
        separator,
        *_glyph_word("THEORY", unicode=unicode),
    )


def _boxed_lines(
    body: tuple[str, ...], width: int, *, unicode: bool
) -> tuple[str, ...]:
    width = max(max(len(line) for line in body) + 4, width)
    vertical = "║" if unicode else "|"
    return (
        sideline_rule(width, top=True, unicode=unicode),
        *(f"{vertical} {line.center(width - 4)} {vertical}" for line in body),
        sideline_rule(width, top=False, unicode=unicode),
    )


def render_banner(capabilities: TerminalCapabilities, *, suppressed: bool = False) -> str:
    """Render the full Roster Theory hero only on an interactive stream."""

    if suppressed or not capabilities.interactive:
        return ""
    if capabilities.width_tier == WidthTier.NARROW:
        labels = ("Roster Theory", "Fantasy Football Assistant", "Draft / Trade / Waiver")
        lines = tuple(
            line
            for label in labels
            for line in textwrap.wrap(
                label,
                width=max(1, capabilities.width),
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
        return "\n".join(lines) + "\n\n"
    if capabilities.width_tier == WidthTier.COMPACT:
        body = (">> ROSTER THEORY <<", _PRODUCT_DESCRIPTOR, _MODE_SELECT)
        rule = "=" * min(max(map(len, body)), capabilities.width)
        return (
            "\n".join(styled(line, "arcade", capabilities) for line in body)
            + "\n"
            + rule
            + "\n\n"
        )
    unicode = capabilities.unicode_supported
    if capabilities.width_tier == WidthTier.WIDE:
        glyphs = _glyph_wordmark(unicode=unicode)
        width = min(capabilities.width, max(92, max(map(len, glyphs)) + 8))
        mode_select = "DRAFT  ◆  TRADE  ◆  WAIVER" if unicode else "DRAFT  <>  TRADE  <>  WAIVER"
        body = (*glyphs, "", _PRODUCT_DESCRIPTOR, mode_select)
    else:
        width = min(capabilities.width, 78)
        title = "▓▒░  R O S T E R   T H E O R Y  ░▒▓" if unicode else ">>>  R O S T E R   T H E O R Y  <<<"
        body = (title, _PRODUCT_DESCRIPTOR, _MODE_SELECT)
    lines = _boxed_lines(body, width, unicode=unicode)
    return "\n".join(styled(line, "arcade", capabilities) for line in lines) + "\n\n"


def render_command_masthead(
    capabilities: TerminalCapabilities,
    command: str,
    *,
    suppressed: bool = False,
    small: bool = False,
) -> str:
    """Render one full-name interactive command masthead."""

    if not capabilities.interactive:
        return ""
    title = f"Roster Theory / {command.strip()}"
    if suppressed or capabilities.width_tier == WidthTier.NARROW:
        return title + "\n"
    if small or capabilities.width_tier == WidthTier.COMPACT:
        arcade_title = f">> {title} <<"
        rule = "=" * min(capabilities.width, max(19, len(arcade_title)))
        return styled(arcade_title, "arcade", capabilities) + "\n" + rule + "\n"
    unicode = capabilities.unicode_supported
    width = min(capabilities.width, 88)
    pip = "◆" if unicode else "<>"
    lines = _boxed_lines((f"{pip}  {title.upper()}  {pip}",), width, unicode=unicode)
    return "\n".join(styled(line, "arcade", capabilities) for line in lines) + "\n"


def render_compact_mark(
    capabilities: TerminalCapabilities, *, suppressed: bool = False
) -> str:
    """Return a compact report mark only for interactive human output."""

    if suppressed or not capabilities.interactive or capabilities.width < 5:
        return ""
    return styled(">> ROSTER THEORY <<", "arcade", capabilities) + "\n"


def _enable_windows_vt(stream: Any) -> bool:
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetConsoleMode.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError):
        return False


def detect_stdout(
    stream: Any = None,
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    width: int | None = None,
    windows_vt: Callable[[Any], bool] | None = None,
) -> TerminalCapabilities:
    """Detect stdout behavior without requiring config, providers, or packages."""

    stream = sys.stdout if stream is None else stream
    environ = os.environ if environ is None else environ
    platform_name = os.name if platform_name is None else platform_name
    try:
        interactive = bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        interactive = False
    if width is None:
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
    width = max(1, width)
    ansi_supported = interactive and environ.get("TERM", "") != "dumb"
    if ansi_supported and platform_name == "nt":
        ansi_supported = (windows_vt or _enable_windows_vt)(stream)
    return TerminalCapabilities(
        interactive=interactive,
        redirected=not interactive,
        width=width,
        ansi_supported=ansi_supported,
        color_enabled=ansi_supported and "NO_COLOR" not in environ,
        unicode_supported=interactive and _unicode_is_safe(stream, platform_name),
    )
