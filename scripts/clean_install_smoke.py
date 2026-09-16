"""Install one wheel into an isolated environment and smoke-test the public CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def _run(command: list[str], *, cwd: Path, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != expected:
        raise RuntimeError(
            f"Command failed ({result.returncode}, expected {expected}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def smoke_wheel(wheel: Path) -> None:
    wheel = wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError(f"Wheel does not exist: {wheel}")
    with tempfile.TemporaryDirectory(prefix="roster theory clean install ") as directory:
        root = Path(directory)
        environment = root / "isolated venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        cli = environment / ("Scripts/roster-theory.exe" if os.name == "nt" else "bin/roster-theory")
        _run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], cwd=root)

        help_result = _run([str(cli), "--no-banner", "help"], cwd=root)
        if "Season preparation" not in help_result.stdout or "\x1b[" in help_result.stdout:
            raise RuntimeError("Installed guided help is missing or contains redirected terminal styling")

        doctor = _run([str(cli), "doctor", "--json"], cwd=root)
        doctor_value = json.loads(doctor.stdout)
        if doctor_value.get("provider_calls") != 0 or doctor_value.get("sleeper_writes") != 0:
            raise RuntimeError("Installed Doctor crossed an offline/read-only boundary")

        example = _run([str(cli), "example-config"], cwd=root)
        config = root / "private path with spaces" / "leagues.json"
        config.parent.mkdir()
        config.write_text(example.stdout, encoding="utf-8")
        prepared = _run([
            str(cli), "--config", str(config), "inputs", "prepare", "synthetic_league",
            "--assistant", "trade", "--dry-run", "--json",
            "--data-dir", str(root / "runtime data with spaces"),
        ], cwd=root)
        value = json.loads(prepared.stdout)
        if value.get("status") != "planned" or value.get("sleeper_write_performed") is not False:
            raise RuntimeError("Installed preparation smoke test violated its machine contract")
        if (root / "runtime data with spaces").exists():
            raise RuntimeError("Dry-run unexpectedly wrote runtime data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_wheel(args.wheel)
    print("CLEAN INSTALL SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
