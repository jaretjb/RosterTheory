"""Fail closed on unsafe tracked files and malformed release archives."""

from __future__ import annotations

import argparse
import hashlib
import re
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
# Regression fingerprints, not a complete inventory of personal data. Do not
# store the original identifiers here, even as concatenated string fragments.
PRIVATE_IDENTITY_DIGESTS = frozenset({
    "16f45b99abfda6364208cc5d3308269813641fab3ed9ad56affa18b1783280b7",
    "d119aabe138facc09d5ae4d73ce8ceb9125fc664163e42d1773ca5a4e83e759b",
    "f64d869c1635fe3077572cae2ef3f324613eead9f8721c1d2768975e053d1746",
    "c5c32c4785109d18f3dc482676e61951259f0daad820921cfe79d9431b3463a1",
    "3de7ceaeabe7ab767ee366905ea822af37fcec10ae8bd2bfe490d2f1b725bcce",
    "f169f5c9c3ab1c630fce6ae2fddd73f0c9701b510cac148d6ce47904c6abfbfd",
    "dd03042cba126a109e7483325de0815543c1934bcbabb518344aec5b5c18b15a",
    "dd404d86ff96c2b740d12f992bdc4b9cee4f877f1eef7b331a614b9174b959f9",
    "501084691a6ecac147cfd11534676ad79379cfe07d0f36a8d0a2e05328037457",
    "28245daa13f382495e64870f6525d13b23f081b00b070634950cb41f88bcc5c4",
    "17834500a991304e73a805706e7919c838eb71258f320e39e4fe1404f0a27d67",
    "5d77729db09e070ed3797ecdf5dab2f2828def3aa24a737b2ea4fc5c3cb54b44",
    "c8f001d6e425d6651dd26bb43ff7b039b4bef35d8ab6608d75186da113cf77df",
    "172e9866be1ff6ccecb690a2164c0e7f7ab5d024947f1f296cc03eaa1e3fdbe2",
    "29b6b75cbecfc8a6fd8711f02fa62a239727f5717d0d275a567512a4097c43f0",
    "22b5164e468e5630e4bccfdbf6da3dccfcc34d1c8a5958d029216935fd25e083",
    "a8c7d703d2dc2de984330e15608c022f5513896453845c9e01ee986d4cbed96f",
    "3a341f110cfdca10b6d044374e16a0e22af2fb34e54d44d730f8ce81d7b5b4a2",
})
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
    for index, path in enumerate(sorted(set(paths)), 1):
        reason = forbidden_path_reason(path)
        if reason:
            label = f"tracked path #{index}" if identity_findings(path.encode(), "path") else path
            findings.append(f"{label}: {reason}")
    return findings


def git_tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    )
    return [value.decode("utf-8") for value in result.stdout.split(b"\0") if value]


def identity_findings(
    data: bytes, label: str, digests: frozenset[str] = PRIVATE_IDENTITY_DIGESTS,
) -> list[str]:
    """Report locations without repeating private text in CI logs."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace").replace("\x00", "")
    words = list(re.finditer(r"[^\W_]+", text.casefold()))
    findings = []
    for start, word in enumerate(words):
        candidate = ""
        for following in words[start:start + 4]:
            candidate += following.group()
            if hashlib.sha256(candidate.encode()).hexdigest() in digests:
                line = text.count("\n", 0, word.start()) + 1
                findings.append(f"{label}:{line}: private identity marker")
    return findings


def git_index_contents(root: Path) -> list[tuple[str, bytes]]:
    """Read the entire index, including force-added ignored files and partial stages."""
    listing = subprocess.run(
        ["git", "ls-files", "--stage", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    entries = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, oid, stage = metadata.split()
        if stage != b"0" or mode == b"160000":
            raise ValueError("unmerged index or submodule requires explicit privacy review")
        entries.append((name.decode("utf-8"), oid))
    objects = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, capture_output=True, check=True,
        input=b"".join(oid + b"\n" for _, oid in entries),
    ).stdout
    contents = []
    offset = 0
    for name, oid in entries:
        end = objects.index(b"\n", offset)
        actual_oid, kind, length = objects[offset:end].split()
        if actual_oid != oid or kind != b"blob":
            raise ValueError("index object is not a readable blob")
        start = end + 1
        offset = start + int(length)
        contents.append((name, objects[start:offset]))
        offset += 1
    return contents


def validate_repository(root: Path, *, staged: bool = False) -> list[str]:
    entries = git_index_contents(root)
    findings = validate_tracked_paths(name for name, _ in entries)
    for index, (name, indexed) in enumerate(entries, 1):
        # A private filename must not itself be echoed in diagnostics.
        path_hits = identity_findings(name.encode("utf-8"), f"tracked path #{index}")
        findings.extend(path_hits)
        label = f"tracked path #{index}" if path_hits else name
        try:
            path = root / name
            content = indexed if staged else (
                str(path.readlink()).encode("utf-8") if path.is_symlink() else path.read_bytes()
            )
        except OSError:
            findings.append(f"{label}: tracked file cannot be read")
            continue
        findings.extend(identity_findings(content, label))
    return findings


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


def archive_identity_findings(path: Path) -> list[str]:
    findings = []
    def inspect(name: str, content: bytes, index: int) -> None:
        path_hits = identity_findings(name.encode(), f"{path.name}:member #{index}")
        findings.extend(path_hits)
        label = f"{path.name}:member #{index}" if path_hits else f"{path.name}:{name}"
        findings.extend(identity_findings(content, label))
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for index, member in enumerate(archive.infolist(), 1):
                if not member.is_dir():
                    inspect(member.filename, archive.read(member), index)
    else:
        with tarfile.open(path, "r:gz") as archive:
            for index, member in enumerate(archive.getmembers(), 1):
                if member.isfile():
                    with archive.extractfile(member) as stream:
                        inspect(member.name, stream.read(), index)
    return findings


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
            findings.extend(archive_identity_findings(archive))
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
            findings.append(f"{archive.name}: unreadable archive: {exc}")
            continue
        for member in sorted(members):
            reason = _unsafe_archive_member(member)
            if reason:
                label = "private member path" if identity_findings(member.encode(), "path") else member
                findings.append(f"{archive.name}:{label}: {reason}")
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
    repository = subparsers.add_parser("repository", help="Inspect every Git-tracked path and content")
    repository.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    repository.add_argument("--staged", action="store_true", help="Inspect exact indexed contents")
    distributions = subparsers.add_parser("distributions", help="Inspect wheel and sdist contents")
    distributions.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    if args.command == "repository":
        return _report(validate_repository(args.root, staged=args.staged), "tracked repository contents")
    return _report(validate_distributions(args.directory), "distribution contents")


if __name__ == "__main__":
    raise SystemExit(main())
