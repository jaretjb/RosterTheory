import io
import hashlib
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
import tomllib

from scripts.release_gate import (
    SDIST_REQUIRED,
    WHEEL_REQUIRED,
    forbidden_path_reason,
    identity_findings,
    validate_distributions,
    validate_repository,
    validate_tracked_paths,
)


class ReleaseGateTests(unittest.TestCase):
    def test_identity_scan_covers_case_separators_and_wrapped_names(self):
        digests = frozenset({hashlib.sha256(b"privateleague20").hexdigest()})
        samples = (
            "PrivateLEAGUE20", "private_league_20", "Private League & 20",
            "PRIVATE\n   LEAGUE 20", "private-league-20",
        )
        for sample in samples:
            for encoding in ("utf-8", "utf-16"):
                findings = identity_findings(sample.encode(encoding), "fixture", digests)
                self.assertTrue(findings)
                self.assertNotIn(sample, repr(findings))
        self.assertEqual(identity_findings(b"fourth pick; League Alpha; synthetic_owner", "safe", digests), [])

    def test_repository_scan_uses_all_tracked_files_and_exact_index(self):
        digests = frozenset({hashlib.sha256(b"privateleague20").hexdigest()})
        def scan(data, label):
            return identity_findings(data, label, digests)
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.release_gate.identity_findings", side_effect=scan,
        ):
            root = Path(directory)
            def git(*args):
                return subprocess.run(
                    ["git", *args], cwd=root, check=True, capture_output=True
                )
            git("init")
            (root / ".gitignore").write_text("COMPLETED_*.md\nlocal.json\n", encoding="utf-8")
            private = "PrivateLeague20"
            doc = root / "COMPLETED_EXPERIMENT.md"
            doc.write_text(private, encoding="utf-8")
            (root / "local.json").write_text(private, encoding="utf-8")
            git("add", ".gitignore")
            git("add", "-f", doc.name)
            self.assertTrue(validate_repository(root))
            self.assertTrue(validate_repository(root, staged=True))
            doc.write_text("League Alpha", encoding="utf-8")
            self.assertEqual(validate_repository(root), [])
            self.assertTrue(validate_repository(root, staged=True))
            git("add", "-f", doc.name)
            self.assertEqual(validate_repository(root, staged=True), [])
            doc.write_text(private, encoding="utf-8")
            self.assertTrue(validate_repository(root))
            self.assertEqual(validate_repository(root, staged=True), [])
            git("rm", "--cached", "-f", doc.name)
            self.assertEqual(validate_repository(root), [])
            named = root / (private + ".txt")
            named.write_text("safe", encoding="utf-8")
            git("add", named.name)
            findings = validate_repository(root)
            self.assertTrue(any("tracked path #" in value for value in findings))
            self.assertNotIn(private, repr(findings))

    def test_ci_matrix_and_release_tools_are_declared_and_blocking(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/release-gates.yml").read_text(encoding="utf-8")
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        for runner in ("ubuntu-latest", "windows-latest", "macos-latest"):
            self.assertIn(runner, workflow)
        for version in ('"3.11"', '"3.12"', '"3.13"'):
            self.assertIn(version, workflow)
        for command in (
            "python -m unittest discover -s tests",
            "tests.test_cli_discovery",
            "tests.test_doctor",
            "tests.test_terminal_identity",
            "tests.test_cli_output_contract",
            "python -m build",
            "release_gate.py distributions",
            "release_gate.py repository --staged",
            "clean_install_smoke.py",
            "python -m pip_audit",
            "python -m ruff",
            "docker://ghcr.io/gitleaks/gitleaks:v8.24.3",
            "GIT_CONFIG_KEY_0: safe.directory",
            "GIT_CONFIG_VALUE_0: /github/workspace",
            "git --redact --verbose --exit-code=1",
            "actions/upload-artifact@v6",
        ):
            self.assertIn(command, workflow)
        self.assertIn(
            "python scripts/release_gate.py repository --staged",
            (root / ".githooks/pre-commit").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            project["project"]["optional-dependencies"]["dev"],
            ["build==1.6.1", "pip-audit==2.10.1", "ruff==0.16.7"],
        )

    def test_repository_gate_rejects_private_and_generated_artifacts(self):
        unsafe = {
            ".env": "environment",
            ".env.production": "environment",
            "config/leagues.json": "private league",
            "data/cache/provider.json": "runtime cache",
            "data/exports/result.csv": "runtime cache",
            "data/manual/rankings.csv": "runtime cache",
            "keys/provider.pem": "credential",
            "credentials.json": "credential",
        }
        for path, expected in unsafe.items():
            with self.subTest(path=path):
                self.assertIn(expected, forbidden_path_reason(path))

    def test_repository_gate_allows_public_synthetic_shapes(self):
        paths = [
            ".env.example", "config/leagues.example.json",
            "examples/manual_import_sample/rankings.csv",
            "tests/fixtures/runtime_inputs/league_alpha.contract.json",
            "src/roster_theory/providers/cache.py",
        ]
        self.assertEqual(validate_tracked_paths(paths), [])

    def test_distribution_gate_requires_both_safe_complete_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "roster_theory-0.1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                for name in WHEEL_REQUIRED:
                    archive.writestr(name, "safe")
                archive.writestr("roster_theory-0.1.0.dist-info/entry_points.txt", "[console_scripts]")
            sdist = root / "roster_theory-0.1.0.tar.gz"
            with tarfile.open(sdist, "w:gz") as archive:
                for name in SDIST_REQUIRED:
                    payload = b"safe"
                    info = tarfile.TarInfo(f"roster_theory-0.1.0/{name}")
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            self.assertEqual(validate_distributions(root), [])

            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("data/manual/private.csv", "private")
            findings = validate_distributions(root)
            self.assertTrue(any("manual-input" in finding for finding in findings))

            digest = frozenset({hashlib.sha256(b"privateleague20").hexdigest()})
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("notes.txt", "PRIVATE\nLEAGUE 20")
            with patch("scripts.release_gate.identity_findings", side_effect=(
                lambda data, label: identity_findings(data, label, digest)
            )):
                self.assertTrue(any("private identity" in value for value in validate_distributions(root)))


if __name__ == "__main__":
    unittest.main()
