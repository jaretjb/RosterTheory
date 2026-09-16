from __future__ import annotations

import io
import unittest

from roster_theory.reporting import ReportFrame, interactive_progress, render_report
from roster_theory.terminal import TerminalCapabilities


def capabilities(*, interactive: bool, width: int = 88, color: bool = False) -> TerminalCapabilities:
    return TerminalCapabilities(
        interactive=interactive, redirected=not interactive, width=width,
        ansi_supported=color, color_enabled=color,
    )


class ReportTests(unittest.TestCase):
    def test_section_order_detail_and_saved_path(self) -> None:
        frame = ReportFrame(
            "Waiver", "league_alpha", "week 2", "DEGRADED", "No action",
            ("Incomplete projection inputs",), ("Week-specific expert rank only",),
            ("evidence.json",),
        )
        detail = "Original expert basis\nSaved evidence: evidence.json"
        output = render_report(frame, detail, capabilities(interactive=False))
        sections = ["League / horizon:", "Readiness:", "Result:", "Warnings:",
                    "Limitations:", "Details:", "Saved evidence:"]
        positions = [output.index(section) for section in sections]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Original expert basis", output)
        self.assertEqual(output.count("Saved evidence: evidence.json"), 1)
        self.assertTrue(output.endswith("Saved evidence: evidence.json"))
        self.assertNotIn("\x1b[", output)

    def test_narrow_and_color_statuses(self) -> None:
        for status in ("READY", "DEGRADED", "INCOMPLETE", "UNCALIBRATED"):
            with self.subTest(status=status):
                frame = ReportFrame("Draft", "beta", "preseason draft", status,
                                    "A longer result needing ordinary line wrapping")
                narrow = render_report(frame, "Detail remains intact", capabilities(interactive=True, width=30))
                self.assertIn(f"Readiness: {status}", narrow)
                self.assertIn("Detail remains intact", narrow)
                self.assertNotIn("\x1b[", narrow)
                colored = render_report(frame, "Detail", capabilities(interactive=True, color=True))
                self.assertIn("\x1b[", colored)
                self.assertIn(status, colored)

    def test_long_summary_wraps_without_rewriting_detail(self) -> None:
        frame = ReportFrame("Trade", "league", "rest of season", "READY",
                            "One two three four five six seven eight nine ten eleven")
        output = render_report(frame, "  original  spacing", capabilities(interactive=True, width=28))
        self.assertIn("  original  spacing", output)
        self.assertGreater(output.count("\n"), 6)

    def test_compact_frame_omits_empty_chrome_but_keeps_context_and_path(self) -> None:
        frame = ReportFrame(
            "Waiver search",
            "league_alpha",
            "weeks 2-17",
            "DEGRADED",
            "NO ACTION",
            saved_paths=("evidence.json",),
            compact=True,
        )
        output = render_report(
            frame,
            "BEST IDEA\nHold for now.",
            capabilities(interactive=False),
        )
        self.assertIn("Result: NO ACTION", output)
        self.assertIn("BEST IDEA", output)
        self.assertNotIn("Warnings:", output)
        self.assertNotIn("Limitations:", output)
        self.assertNotIn("Details:", output)
        self.assertTrue(output.endswith("Saved evidence: evidence.json"))

        narrow = render_report(
            frame,
            "BEST IDEA\nA long manager-facing reason that must remain readable in a narrow terminal window.",
            capabilities(interactive=True, width=30),
        )
        self.assertLessEqual(max(len(line) for line in narrow.splitlines()), 30)


class ProgressTests(unittest.TestCase):
    def test_interactive_success_and_failure(self) -> None:
        stream = io.StringIO()
        with interactive_progress("Refresh", stream=stream, capabilities=capabilities(interactive=True)):
            pass
        self.assertEqual(stream.getvalue(), "Refresh... (Ctrl-C to cancel)\nRefresh: complete\n")
        stream = io.StringIO()
        with self.assertRaisesRegex(ValueError, "bad"):
            with interactive_progress("Refresh", stream=stream, capabilities=capabilities(interactive=True)):
                raise ValueError("bad")
        self.assertTrue(stream.getvalue().endswith("Refresh: failed\n"))

    def test_cancel_rethrows(self) -> None:
        stream = io.StringIO()
        with self.assertRaises(KeyboardInterrupt):
            with interactive_progress("Simulation", stream=stream, capabilities=capabilities(interactive=True)):
                raise KeyboardInterrupt
        self.assertTrue(stream.getvalue().endswith("Simulation: cancelled\n"))

    def test_machine_and_piped_modes_are_silent(self) -> None:
        for interactive, machine in ((True, True), (False, False), (False, True)):
            with self.subTest(interactive=interactive, machine=machine):
                stream = io.StringIO()
                with interactive_progress("Simulation", machine_output=machine, stream=stream,
                                          capabilities=capabilities(interactive=interactive)):
                    pass
                self.assertEqual(stream.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
