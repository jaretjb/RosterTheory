"""Fail closed on unsafe tracked files and malformed release archives."""

from __future__ import annotations

import argparse
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


FORBIDDEN_DIRECTORY_PARTS = {"cache", "exports", "manual"}
FORBIDDEN_CREDENTIAL_NAMES = {
    ".npmrc", ".pypirc", "credentials.json", "secrets.json", "id_rsa", "id_ed25519",
}
FORBIDDEN_CREDENTIAL_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
WHEEL_REQUIRED = {
    "roster_theory/cli.py",
    "roster_theory/season_prepare.py",
    "roster_theory/waiver_inputs.py",
    "roster_theory/resources/leagues.example.json",
}
SDIST_REQUIRED = {
    "LICENSE", "README.md", "pyproject.toml", "docs/RELEASE_CHECKLIST.md",
    "scripts/release_gate.py",
    "scripts/clean_install_smoke.py", "src/roster_theory/cli.py",
    "tests/test_release_gates.py",
}


def forbidden_path_reason(path: str) -> str | None:
    """Return the release-blocking reason for one repository-relative path."""

    normalized = PurePosixPath(path.replace("\\", "/"))
    lowered = tuple(part.casefold() for part in normalized.parts)
    name = normalized.name.casefold()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "tracked environment/secret file"
    if name == "leagues.json":
        return "private league configuration"
    if name in FORBIDDEN_CREDENTIAL_NAMES or normalized.suffix.casefold() in FORBIDDEN_CREDENTIAL_SUFFIXES:
        return "credential artifact"
    if lowered and lowered[0] == "data" and FORBIDDEN_DIRECTORY_PARTS.intersection(lowered[1:]):
        return "runtime cache/export/manual-input artifact"
    return None


def validate_tracked_paths(paths: Iterable[str]) -> list[str]:
    findings = []
    for path in sorted({value.strip() for value in paths if value.strip()}):
        reason = forbidden_path_reason(path)
        if reason:
            findings.append(f"{path}: {reason}")
    return findings


def git_tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    )
    return [value.decode("utf-8") for value in result.stdout.split(b"\0") if value]


def _archive_members(path: Path) -> set[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return {name for name in archive.namelist() if not name.endswith("/")}
    with tarfile.open(path, "r:gz") as archive:
        raw = {name for member in archive.getmembers() if member.isfile() for name in (member.name,)}
    roots = {PurePosixPath(name).parts[0] for name in raw}
    if len(roots) != 1:
        raise ValueError(f"{path.name} must contain exactly one source root")
    return {str(PurePosixPath(*PurePosixPath(name).parts[1:])) for name in raw}


def _unsafe_archive_member(name: str) -> str | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return "unsafe archive traversal path"
    if "__pycache__" in path.parts or path.suffix == ".pyc":
        return "compiled/cache artifact"
    if ".git" in path.parts or "build" in path.parts or "dist" in path.parts:
        return "repository/build artifact"
    return forbidden_path_reason(name)


def validate_distributions(directory: Path) -> list[str]:
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    findings: list[str] = []
    if len(wheels) != 1:
        findings.append(f"expected exactly one wheel, found {len(wheels)}")
    if len(sdists) != 1:
        findings.append(f"expected exactly one source distribution, found {len(sdists)}")
    for archive, required in [*((path, WHEEL_REQUIRED) for path in wheels), *((path, SDIST_REQUIRED) for path in sdists)]:
        try:
            members = _archive_members(archive)
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
            findings.append(f"{archive.name}: unreadable archive: {exc}")
            continue
        for member in sorted(members):
            reason = _unsafe_archive_member(member)
            if reason:
                findings.append(f"{archive.name}:{member}: {reason}")
        missing = required - members
        if missing:
            findings.append(f"{archive.name}: missing required files: {', '.join(sorted(missing))}")
        if archive.suffix == ".whl":
            entry_points = [name for name in members if name.endswith(".dist-info/entry_points.txt")]
            if len(entry_points) != 1:
                findings.append(f"{archive.name}: expected one entry_points.txt")
    return findings


def _report(findings: list[str], label: str) -> int:
    if findings:
        print(f"RELEASE GATE FAILED: {label}")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(f"RELEASE GATE PASSED: {label}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    repository = subparsers.add_parser("repository", help="Inspect Git-tracked paths")
    repository.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    distributions = subparsers.add_parser("distributions", help="Inspect wheel and sdist contents")
    distributions.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    if args.command == "repository":
        return _report(validate_tracked_paths(git_tracked_paths(args.root)), "tracked repository contents")
    return _report(validate_distributions(args.directory), "distribution contents")


if __name__ == "__main__":
    raise SystemExit(main())
