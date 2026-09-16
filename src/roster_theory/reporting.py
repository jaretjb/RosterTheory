"""Human-only CLI framing and restrained interactive progress."""

from __future__ import annotations

import sys
import textwrap
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, TextIO

from roster_theory.terminal import TerminalCapabilities, detect_stdout


@dataclass(frozen=True)
class ReportFrame:
    product: str
    league: str
    horizon: str
    readiness: str
    result: str
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    saved_paths: tuple[str, ...] = ()
    compact: bool = False


def _line(label: str, value: str, width: int) -> str:
    prefix = f"{label}: "
    return textwrap.fill(
        value,
        width=max(24, width),
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
        break_long_words=False,
        break_on_hyphens=False,
    )


def render_report(
    frame: ReportFrame, detail: str, capabilities: TerminalCapabilities
) -> str:
    """Put decision context first without rewriting authoritative detail."""

    width = capabilities.width if capabilities.interactive else 88
    readiness = frame.readiness.upper()
    if capabilities.color_enabled:
        color = "32" if readiness == "READY" else "33" if readiness == "DEGRADED" else "31"
        readiness = f"\x1b[{color}m{readiness}\x1b[0m"
    lines = [
        f"RosterTheory / {frame.product}",
        _line("League / horizon", f"{frame.league} / {frame.horizon}", width),
        _line("Readiness", readiness, width),
        _line("Result", frame.result, width),
    ]
    if frame.warnings:
        lines.append("Warnings:")
        lines.extend(_line("-", warning, width) for warning in frame.warnings)
    elif not frame.compact:
        lines.append("Warnings: none")
    if frame.limitations:
        lines.append("Limitations:")
        lines.extend(_line("-", limitation, width) for limitation in frame.limitations)
    elif not frame.compact:
        lines.append("Limitations: none reported")
    # Legacy formatters may already append this notice. Keep it last and unique.
    detail_lines = [
        line for line in detail.rstrip().splitlines()
        if not line.startswith(("Saved evidence:", "Saved CSV:"))
    ]
    if frame.compact:
        wrapped_detail: list[str] = []
        for line in detail_lines:
            if not line or (line.isupper() and len(line) <= 28):
                wrapped_detail.append(line)
                continue
            indent = "  " if line.startswith("- ") else ""
            wrapped_detail.extend(
                textwrap.fill(
                    line,
                    width=max(24, width),
                    subsequent_indent=indent,
                    break_long_words=False,
                    break_on_hyphens=False,
                ).splitlines()
            )
        detail_lines = wrapped_detail
    if detail_lines:
        lines.extend(("", *detail_lines) if frame.compact else ("", "Details:", *detail_lines))
    if frame.saved_paths:
        lines.append("")
        lines.extend(
            f"Saved {'CSV' if path.lower().endswith('.csv') else 'evidence'}: {path}"
            for path in frame.saved_paths
        )
    return "\n".join(lines)


@contextmanager
def interactive_progress(
    label: str,
    *,
    machine_output: bool = False,
    stream: TextIO | None = None,
    capabilities: TerminalCapabilities | None = None,
) -> Iterator[None]:
    """Emit only start/end states; cancellation remains ordinary Ctrl-C."""

    stream = sys.stdout if stream is None else stream
    capabilities = detect_stdout(stream) if capabilities is None else capabilities
    visible = capabilities.interactive and not machine_output
    if visible:
        print(f"{label}... (Ctrl-C to cancel)", file=stream, flush=True)
    try:
        yield
    except KeyboardInterrupt:
        if visible:
            print(f"{label}: cancelled", file=stream, flush=True)
        raise
    except Exception:
        if visible:
            print(f"{label}: failed", file=stream, flush=True)
        raise
    else:
        if visible:
            print(f"{label}: complete", file=stream, flush=True)
