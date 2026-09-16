import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
import tomllib

from scripts.release_gate import (
    SDIST_REQUIRED,
    WHEEL_REQUIRED,
    forbidden_path_reason,
    validate_distributions,
    validate_tracked_paths,
)


class ReleaseGateTests(unittest.TestCase):
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
            "clean_install_smoke.py",
            "python -m pip_audit",
            "python -m ruff",
            "gitleaks/gitleaks-action@v3",
        ):
            self.assertIn(command, workflow)
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


if __name__ == "__main__":
    unittest.main()
