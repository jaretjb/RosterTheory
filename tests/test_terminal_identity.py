import argparse
import io
import re
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from roster_theory import cli
from roster_theory._colosseum import build_logo
from scripts.render_terminal_logo import render_svg
from roster_theory.terminal import (
    TerminalCapabilities,
    render_banner,
    render_compact_mark,
    sideline_rule,
    status_token,
    styled,
    visible_width,
)


def capabilities(*, interactive=True, width=80, color=False, unicode=True):
    return TerminalCapabilities(
        interactive=interactive,
        redirected=not interactive,
        width=width,
        ansi_supported=color,
        color_enabled=color,
        unicode_supported=unicode,
    )


class TerminalIdentityTests(unittest.TestCase):
    def test_visual_primitives_are_deterministic_and_width_safe(self):
        cap = capabilities(color=True, width=100)
        value = styled("READY", status_token("ready"), cap)
        self.assertEqual(visible_width(value), 5)
        self.assertEqual(status_token("uncalibrated"), "degraded")
        for unicode in (True, False):
            with self.subTest(unicode=unicode):
                self.assertEqual(len(sideline_rule(72, unicode=unicode)), 72)

    def test_standard_full_name_banner_snapshot(self):
        lines = render_banner(capabilities()).splitlines()
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(len(line) == 78 for line in lines[:-1]))
        self.assertIn("R O S T E R   T H E O R Y", lines[1])
        self.assertIn("FANTASY FOOTBALL ASSISTANT", lines[2])
        self.assertIn("DRAFT  /  TRADE  /  WAIVER", lines[3])
        self.assertNotIn("[RT]", "\n".join(lines))

    def test_colosseum_wide_banner_has_stadium_and_horizontal_wordmark(self):
        banner = render_banner(capabilities(width=110, color=True))
        self.assertIn("\x1b[38;2;255;211;69", banner)
        self.assertIn("ROSTER THEORY", banner)
        self.assertIn("FANTASY FOOTBALL ASSISTANT", banner)
        self.assertIn("DRAFT  ◆  TRADE  ◆  WAIVER", banner)
        self.assertGreater(sum(0x2800 <= ord(char) <= 0x28FF for char in banner), 500)
        self.assertGreater(sum(char in "∑≈∞π√×−=∫∂λδ" for char in banner), 200)
        self.assertNotIn("▀", banner)
        self.assertEqual(len(banner.splitlines()), 39)
        self.assertNotIn("IDENTITY STUDY", banner)
        self.assertNotIn("THE COLOSSEUM", banner)

    def test_colosseum_is_width_safe_in_color_monochrome_and_ascii(self):
        for width in (100, 110, 122, 123, 132, 160):
            for color in (False, True):
                for unicode in (False, True):
                    with self.subTest(width=width, color=color, unicode=unicode):
                        banner = render_banner(capabilities(
                            width=width, color=color, unicode=unicode
                        ))
                        self.assertIn("ROSTER THEORY", banner)
                        self.assertTrue(all(
                            visible_width(line) <= min(width, 132)
                            for line in banner.splitlines()
                        ))
                        if not color:
                            self.assertNotIn("\x1b", banner)
                        if not unicode:
                            banner.encode("ascii")

    def test_monochrome_colosseum_preserves_the_selected_mathematical_weave(self):
        banner = render_banner(capabilities(width=132))
        self.assertNotIn("\x1b", banner)
        headline = banner.splitlines()[26:32]
        self.assertEqual(len(headline), 6)
        self.assertEqual([line[10:17] for line in headline], [
            "∑×∞=√≈−", "∞=√  π∑", "√≈−π∑×∞",
            "−π∑×∞= ", "∑×∞ √≈ ", "∞=√ −π∑",
        ])
        colored = render_banner(capabilities(width=132, color=True))
        colored_headline = re.sub(r"\x1b\[[0-9;]*m", "", colored).splitlines()[26:32]
        self.assertEqual(headline, [line.rstrip() for line in colored_headline])

    def test_ascii_colosseum_keeps_the_weave_silhouettes_without_block_fill(self):
        for width in (100, 122, 123, 132):
            with self.subTest(width=width):
                unicode = render_banner(capabilities(width=width)).splitlines()[26:32]
                ascii = render_banner(capabilities(width=width, unicode=False)).splitlines()[26:32]
                self.assertEqual(
                    [[i for i, char in enumerate(line) if char != " "] for line in unicode],
                    [[i for i, char in enumerate(line) if char != " "] for line in ascii],
                )
                self.assertTrue(all(set(line) <= set(" S~8pvx-=fdl") for line in ascii))

    def test_wide_colosseum_stays_out_of_suppressed_and_redirected_output(self):
        for width in (100, 132, 160):
            self.assertEqual(render_banner(capabilities(width=width), suppressed=True), "")
            self.assertEqual(
                render_banner(capabilities(width=width, interactive=False)), ""
            )

    def test_narrow_redirected_and_suppressed_fallbacks(self):
        self.assertEqual(
            render_banner(capabilities(width=28)),
            "Roster Theory\nFantasy Football Assistant\nDraft / Trade / Waiver\n\n",
        )
        compact = render_banner(capabilities(width=50))
        self.assertIn(">> ROSTER THEORY <<", compact)
        self.assertIn("FANTASY FOOTBALL ASSISTANT", compact)
        self.assertIn("DRAFT  /  TRADE  /  WAIVER", compact)
        self.assertEqual(render_banner(capabilities(interactive=False)), "")
        self.assertEqual(render_banner(capabilities(), suppressed=True), "")
        self.assertEqual(render_compact_mark(capabilities()), ">> ROSTER THEORY <<\n")
        self.assertEqual(
            render_compact_mark(capabilities(color=True)),
            "\x1b[1;38;5;220m>> ROSTER THEORY <<\x1b[0m\n",
        )
        self.assertEqual(render_compact_mark(capabilities(interactive=False)), "")
        self.assertEqual(render_compact_mark(capabilities(), suppressed=True), "")

    def test_full_name_identity_is_on_bare_welcome_and_guided_help(self):
        stream = io.StringIO()
        with patch("roster_theory.cli.detect_stdout", return_value=capabilities()), \
                patch("sys.argv", ["roster-theory"]), redirect_stdout(stream):
            cli.main()
        self.assertTrue(stream.getvalue().startswith("╔"))
        self.assertIn("R O S T E R   T H E O R Y", stream.getvalue())
        self.assertIn("Start here:", stream.getvalue())

        stream = io.StringIO()
        with patch("roster_theory.cli.detect_stdout", return_value=capabilities()), \
                redirect_stdout(stream):
            cli.command_help(cli.build_parser().parse_args(["help"]))
        self.assertTrue(stream.getvalue().startswith("╔"))
        self.assertIn("R O S T E R   T H E O R Y", stream.getvalue())
        self.assertIn("League setup", stream.getvalue())

    def test_no_banner_before_or_after_help_and_on_bare_welcome(self):
        for arguments in (["--no-banner", "help"], ["help", "--no-banner"]):
            with self.subTest(arguments=arguments):
                stream = io.StringIO()
                with patch("roster_theory.cli.detect_stdout", return_value=capabilities()), \
                        redirect_stdout(stream):
                    cli.command_help(cli.build_parser().parse_args(arguments))
                self.assertEqual(stream.getvalue(), cli.GUIDED_HELP)

        stream = io.StringIO()
        with patch("roster_theory.cli.detect_stdout", return_value=capabilities()), \
                patch("sys.argv", ["roster-theory", "--no-banner"]), \
                redirect_stdout(stream):
            cli.main()
        self.assertEqual(stream.getvalue(), cli.WELCOME)

    def test_compact_mark_stays_out_of_json_and_redirected_reports(self):
        for args, cap, expected in (
            (
                argparse.Namespace(json=False, no_banner=False),
                capabilities(unicode=False),
                None,
            ),
            (argparse.Namespace(json=False, no_banner=False), capabilities(interactive=False), "report\n"),
            (
                argparse.Namespace(json=False, no_banner=True),
                capabilities(),
                "Roster Theory / Report\nreport\n",
            ),
            (argparse.Namespace(json=True, no_banner=False), capabilities(), "report\n"),
        ):
            with self.subTest(args=args, cap=cap):
                stream = io.StringIO()
                with patch("roster_theory.cli.detect_stdout", return_value=cap), \
                        redirect_stdout(stream):
                    cli._print_human_report(args, "report")
                if expected is None:
                    self.assertTrue(stream.getvalue().startswith("+"))
                    self.assertIn("ROSTER THEORY / REPORT", stream.getvalue())
                    self.assertTrue(stream.getvalue().endswith("report\n"))
                else:
                    self.assertEqual(stream.getvalue(), expected)

    def test_interactive_command_help_has_small_full_name_masthead(self):
        stream = io.StringIO()
        with patch("roster_theory.cli.detect_stdout", return_value=capabilities(width=50)), \
                patch("sys.stdout", stream), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["waiver", "search", "--help"])
        output = stream.getvalue()
        self.assertIn("Roster Theory / waiver search help", output)
        self.assertIn("usage: roster-theory waiver search", output)

    def test_main_prints_one_early_masthead_for_routine_human_command(self):
        stream = io.StringIO()
        args = argparse.Namespace(
            command="trade",
            trade_command="diagnose",
            waiver_command=None,
            json=False,
            no_banner=False,
            func=lambda _args: print("done"),
        )
        parser = unittest.mock.Mock()
        parser.parse_args.return_value = args
        with patch("roster_theory.cli.build_parser", return_value=parser), \
                patch("roster_theory.cli.detect_stdout", return_value=capabilities(width=50)), \
                patch("sys.argv", ["roster-theory", "trade", "diagnose"]), \
                redirect_stdout(stream):
            cli.main()
        self.assertEqual(stream.getvalue().count("Roster Theory / Trade Diagnose"), 1)
        self.assertTrue(stream.getvalue().endswith("done\n"))

    def test_readme_colosseum_matches_cli_geometry_and_replaces_old_artwork(self):
        root = Path(__file__).resolve().parents[1]
        logo = (root / "docs/assets/roster-theory-colosseum.svg").read_text(
            encoding="utf-8"
        )
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertEqual(logo, render_svg(build_logo()))
        svg = ET.fromstring(logo)
        ns = {"svg": "http://www.w3.org/2000/svg"}
        self.assertEqual(svg.attrib["role"], "img")
        self.assertIn("Colosseum", svg.find("svg:title", ns).text)
        for name in ("stadium", "wordmark"):
            group = svg.find(f"svg:g[@id='{name}']", ns)
            self.assertEqual(len(group.findall("svg:text", ns)), 0)
        stadium = svg.find("svg:g[@id='stadium']", ns)
        self.assertGreater(len(stadium.findall("svg:path", ns)), 0)
        wordmark = svg.find("svg:g[@id='wordmark']", ns)
        self.assertIn("Mathematical Weave", svg.find("svg:title", ns).text)
        outlines = {path.attrib["id"] for path in svg.findall("svg:defs/svg:path", ns)}
        symbols = wordmark.findall("svg:use", ns)
        self.assertGreater(len(symbols), 200)
        self.assertTrue(all(symbol.attrib["href"][1:] in outlines for symbol in symbols))
        self.assertEqual(len(wordmark.findall("svg:rect", ns)), 0)
        self.assertIn("#ffd345", logo.lower())
        self.assertIn("FANTASY FOOTBALL ASSISTANT", logo)
        self.assertIn("DRAFT  ◆  TRADE  ◆  WAIVER", logo)
        self.assertNotIn("READ-ONLY", logo.upper())
        self.assertNotIn("IDENTITY STUDY", logo)
        self.assertIn("docs/assets/roster-theory-colosseum.svg", readme)
        self.assertNotIn("roster-theory-terminal-90s.svg", readme)
        self.assertFalse((root / "docs/assets/roster-theory-terminal-90s.svg").exists())


if __name__ == "__main__":
    unittest.main()
