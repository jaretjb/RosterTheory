"""Smoke-test a wheel with venv or pipx, without loading checkout source."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _run(
    command: list[str], *, cwd: Path, expected: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != expected:
        raise RuntimeError(
            f"Command failed ({result.returncode}, expected {expected}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def smoke_wheel(wheel: Path, *, installer: str = "venv") -> None:
    wheel = wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError(f"Wheel does not exist: {wheel}")
    with tempfile.TemporaryDirectory(prefix="roster theory clean install ") as directory:
        root = Path(directory)
        env = os.environ.copy()
        for name in ("PYTHONPATH", "VIRTUAL_ENV", "ROSTER_THEORY_CONFIG"):
            env.pop(name, None)
        # Keep the smoke test independent of the maintainer's real league setup.
        env["ROSTER_THEORY_CONFIG"] = str(root / "missing-private-config.json")
        if installer == "pipx":
            for name in tuple(env):
                if name.startswith("PIPX_"):
                    env.pop(name)
            app_bin = root / "app commands with spaces"
            env.update({
                "PIPX_HOME": str(root / "pipx home with spaces"),
                "PIPX_BIN_DIR": str(app_bin),
                "PIPX_MAN_DIR": str(root / "pipx man"),
                "PIPX_DEFAULT_PYTHON": sys.executable,
                "PATH": str(app_bin) + os.pathsep + env.get("PATH", ""),
            })
            pipx = [sys.executable, "-m", "pipx"]
            _run(pipx + ["install", str(wheel)], cwd=root, env=env)
            cli = app_bin / ("roster-theory.exe" if os.name == "nt" else "roster-theory")
            _verify_cli(cli, root=root, env=env)
            # Local installs must update even while the package version is unchanged.
            _run(pipx + ["reinstall", "roster-theory"], cwd=root, env=env)
            _verify_cli(cli, root=root, env=env)
            shell = (
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
                if os.name == "nt" else ["sh", "-c"]
            )
            help_result = _run(shell + ["roster-theory --no-banner help"], cwd=root, env=env)
            if "Season preparation" not in help_result.stdout:
                raise RuntimeError("The pipx command is not available without activation")
        elif installer == "venv":
            environment = root / "isolated venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            cli = environment / (
                "Scripts/roster-theory.exe" if os.name == "nt" else "bin/roster-theory"
            )
            _run(
                [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
                cwd=root, env=env,
            )
            _verify_cli(cli, root=root, env=env)
        else:
            raise ValueError(f"Unknown installer: {installer}")


def _verify_cli(cli: Path, *, root: Path, env: dict[str, str]) -> None:
    help_result = _run([str(cli), "--no-banner", "help"], cwd=root, env=env)
    if "Season preparation" not in help_result.stdout or "\x1b[" in help_result.stdout:
        raise RuntimeError("Installed guided help is missing or contains redirected terminal styling")

    doctor = _run([str(cli), "doctor", "--json"], cwd=root, env=env)
    doctor_value = json.loads(doctor.stdout)
    if doctor_value.get("provider_calls") != 0 or doctor_value.get("sleeper_writes") != 0:
        raise RuntimeError("Installed Doctor crossed an offline/read-only boundary")

    example = _run([str(cli), "example-config"], cwd=root, env=env)
    config = root / "private path with spaces" / "leagues.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(example.stdout, encoding="utf-8")
    prepared = _run([
        str(cli), "--config", str(config), "inputs", "prepare", "synthetic_league",
        "--assistant", "trade", "--dry-run", "--json",
        "--data-dir", str(root / "runtime data with spaces"),
    ], cwd=root, env=env)
    value = json.loads(prepared.stdout)
    if value.get("status") != "planned" or value.get("sleeper_write_performed") is not False:
        raise RuntimeError("Installed preparation smoke test violated its machine contract")
    if (root / "runtime data with spaces").exists():
        raise RuntimeError("Dry-run unexpectedly wrote runtime data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--installer", choices=("venv", "pipx"), default="venv")
    args = parser.parse_args(argv)
    smoke_wheel(args.wheel, installer=args.installer)
    print(f"CLEAN INSTALL SMOKE PASSED ({args.installer})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
