"""Release helper for the automated GitHub release.

Used by ``.github/workflows/release.yaml`` and runnable locally:

    python script/release.py version          # print the manifest version
    python script/release.py check            # validate a release of that version
    python script/release.py notes            # print the release notes path
    python script/release.py zip OUT.zip      # build the HACS release zip

``check`` fails with one line per problem (GitHub ``::error::`` annotations)
when the release is not ready: the manifest version is not ``X.Y.Z``, the
README badge or the changelog name another version, ``hacs.json`` does not
describe the zip release, or ``release-notes/v<version>.md`` is missing or
empty.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = Path("custom_components") / "twincat_iot_communicator"
MANIFEST = INTEGRATION_DIR / "manifest.json"
HACS = Path("hacs.json")
README = Path("README.md")
CHANGELOG = Path("docs") / "changelog.md"
NOTES_DIR = Path("release-notes")

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
BADGE_RE = re.compile(r"badge/Version-([0-9A-Za-z.\-]+?)-blue")
# Files that never belong into the release zip.
ZIP_EXCLUDE_DIRS = {"__pycache__"}
ZIP_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
# Fixed timestamp so the same tree always gives the same zip.
ZIP_DATE = (2020, 1, 1, 0, 0, 0)


class ReleaseError(Exception):
    """A release precondition is not met."""


def manifest_version(root: Path = ROOT) -> str:
    """Return the version from manifest.json."""
    data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str):
        raise ReleaseError(f"{MANIFEST} has no version")
    return version


def tag_for(version: str) -> str:
    """Return the git tag of a version (``v0.0.21``)."""
    return f"v{version}"


def notes_path(version: str, root: Path = ROOT) -> Path:
    """Return the path of the release notes of a version."""
    return root / NOTES_DIR / f"{tag_for(version)}.md"


def check_release(root: Path = ROOT) -> list[str]:
    """Return every problem that blocks a release of the manifest version."""
    try:
        version = manifest_version(root)
    except (OSError, ValueError, ReleaseError) as err:
        return [f"Cannot read the manifest version: {err}"]

    problems: list[str] = []
    if not VERSION_RE.match(version):
        problems.append(f"{MANIFEST} version {version!r} is not X.Y.Z")

    try:
        hacs = json.loads((root / HACS).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        problems.append(f"Cannot read {HACS}: {err}")
    else:
        if hacs.get("zip_release") is not True:
            problems.append(f"{HACS} must set zip_release to true")
        if hacs.get("filename") != "twincat_iot_communicator.zip":
            problems.append(f"{HACS} filename must be twincat_iot_communicator.zip")

    try:
        badge = BADGE_RE.search((root / README).read_text(encoding="utf-8"))
    except OSError as err:
        problems.append(f"Cannot read {README}: {err}")
    else:
        if badge is None:
            problems.append(f"{README} has no version badge")
        elif badge.group(1) != version:
            problems.append(
                f"{README} badge names {badge.group(1)}, the manifest {version}"
            )

    try:
        changelog = (root / CHANGELOG).read_text(encoding="utf-8")
    except OSError as err:
        problems.append(f"Cannot read {CHANGELOG}: {err}")
    else:
        if f"## [{version}]" not in changelog:
            problems.append(f"{CHANGELOG} has no section ## [{version}]")

    notes = notes_path(version, root)
    rel_notes = notes.relative_to(root)
    if not notes.is_file():
        problems.append(f"Release notes {rel_notes} are missing")
    elif not notes.read_text(encoding="utf-8").strip():
        problems.append(f"Release notes {rel_notes} are empty")

    return problems


def build_zip(out: Path, root: Path = ROOT) -> list[str]:
    """Build the HACS release zip and return the archived names.

    The integration files sit at the root of the archive, as HACS expects
    for ``zip_release``. Caches are left out; entries are sorted and carry a
    fixed timestamp.
    """
    source = root / INTEGRATION_DIR
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and not ZIP_EXCLUDE_DIRS.intersection(path.relative_to(source).parts)
        and path.suffix not in ZIP_EXCLUDE_SUFFIXES
    )
    if source / "manifest.json" not in files:
        raise ReleaseError(f"{INTEGRATION_DIR} has no manifest.json")
    names: list[str] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
            names.append(name)
    return names


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the manifest version")
    sub.add_parser("check", help="validate a release of the manifest version")
    sub.add_parser("notes", help="print the release notes path")
    zip_cmd = sub.add_parser("zip", help="build the HACS release zip")
    zip_cmd.add_argument("out", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "version":
            print(manifest_version())
        elif args.command == "notes":
            print(notes_path(manifest_version()).relative_to(ROOT).as_posix())
        elif args.command == "check":
            problems = check_release()
            for problem in problems:
                print(f"::error::{problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"Release {tag_for(manifest_version())} is ready")
        elif args.command == "zip":
            names = build_zip(args.out)
            print(f"{args.out}: {len(names)} files")
    except (OSError, ValueError, ReleaseError) as err:
        print(f"::error::{err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
