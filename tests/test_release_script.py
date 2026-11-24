"""Tests for script/release.py (automated release checks and zip)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("release", REPO / "script" / "release.py")
assert _spec is not None and _spec.loader is not None
release = importlib.util.module_from_spec(_spec)
sys.modules["release"] = release
_spec.loader.exec_module(release)


def _make_repo(tmp_path: Path, version: str = "1.2.3") -> Path:
    """Create a minimal repository that is ready for release ``version``."""
    integration = tmp_path / release.INTEGRATION_DIR
    integration.mkdir(parents=True)
    (integration / "manifest.json").write_text(
        json.dumps({"domain": "twincat_iot_communicator", "version": version}),
    )
    (integration / "__init__.py").write_text("")
    (integration / "translations").mkdir()
    (integration / "translations" / "en.json").write_text("{}")
    (tmp_path / "hacs.json").write_text(
        json.dumps({"zip_release": True, "filename": "twincat_iot_communicator.zip"}),
    )
    (tmp_path / "README.md").write_text(
        f"![Version](https://img.shields.io/badge/Version-{version}-blue.svg)\n",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "changelog.md").write_text(f"# Changelog\n\n## [{version}]\n\n- x\n")
    (tmp_path / "release-notes").mkdir()
    (tmp_path / "release-notes" / f"v{version}.md").write_text("Notes\n")
    return tmp_path


class TestRepository:
    """The real repository is consistent."""

    def test_current_version_is_releasable(self) -> None:
        """Manifest, badge, changelog, hacs.json and release notes agree."""
        assert release.check_release(REPO) == []

    def test_every_release_note_has_a_changelog_section(self) -> None:
        """Each release-notes/v<version>.md belongs to a changelog version."""
        changelog = (REPO / release.CHANGELOG).read_text(encoding="utf-8")
        for notes in (REPO / release.NOTES_DIR).glob("v*.md"):
            assert f"## [{notes.stem[1:]}]" in changelog, notes.name


class TestCheckRelease:
    """check_release reports every problem that blocks a release."""

    def test_ready(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        assert release.check_release(repo) == []
        assert release.manifest_version(repo) == "1.2.3"
        assert release.notes_path("1.2.3", repo) == repo / "release-notes" / "v1.2.3.md"

    def test_missing_notes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "release-notes" / "v1.2.3.md").unlink()
        assert release.check_release(repo) == [
            "Release notes release-notes/v1.2.3.md are missing",
        ]

    def test_empty_notes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "release-notes" / "v1.2.3.md").write_text("  \n")
        assert release.check_release(repo) == [
            "Release notes release-notes/v1.2.3.md are empty",
        ]

    def test_badge_mismatch(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "README.md").write_text("badge/Version-1.2.2-blue.svg")
        assert release.check_release(repo) == [
            "README.md badge names 1.2.2, the manifest 1.2.3",
        ]

    def test_missing_badge(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "README.md").write_text("# Readme")
        assert release.check_release(repo) == ["README.md has no version badge"]

    def test_changelog_without_section(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "docs" / "changelog.md").write_text("# Changelog\n\n## [1.2.2]\n")
        assert release.check_release(repo) == [
            "docs/changelog.md has no section ## [1.2.3]",
        ]

    def test_hacs_zip_release(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "hacs.json").write_text(json.dumps({"filename": "other.zip"}))
        assert release.check_release(repo) == [
            "hacs.json must set zip_release to true",
            "hacs.json filename must be twincat_iot_communicator.zip",
        ]

    def test_invalid_version(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, version="1.2")
        assert release.check_release(repo) == [
            f"{release.MANIFEST} version '1.2' is not X.Y.Z",
        ]

    def test_unreadable_manifest(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / release.MANIFEST).write_text(json.dumps({"domain": "x"}))
        [problem] = release.check_release(repo)
        assert problem.startswith("Cannot read the manifest version")


class TestBuildZip:
    """The zip holds the integration at its root, without caches."""

    def test_layout(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        cache = repo / release.INTEGRATION_DIR / "__pycache__"
        cache.mkdir()
        (cache / "x.cpython-313.pyc").write_bytes(b"\0")
        (repo / release.INTEGRATION_DIR / "stray.pyc").write_bytes(b"\0")
        out = tmp_path / "out" / "twincat_iot_communicator.zip"

        names = release.build_zip(out, repo)

        assert names == ["__init__.py", "manifest.json", "translations/en.json"]
        with zipfile.ZipFile(out) as archive:
            assert archive.namelist() == names
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == "1.2.3"

    def test_reproducible(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        first = tmp_path / "a.zip"
        second = tmp_path / "b.zip"
        release.build_zip(first, repo)
        release.build_zip(second, repo)
        assert first.read_bytes() == second.read_bytes()

    def test_without_manifest(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        (repo / release.MANIFEST).unlink()
        with pytest.raises(release.ReleaseError):
            release.build_zip(tmp_path / "x.zip", repo)

    def test_real_integration(self, tmp_path: Path) -> None:
        """The zip of the repository holds the manifest of this version."""
        out = tmp_path / "twincat_iot_communicator.zip"
        names = release.build_zip(out, REPO)
        assert "manifest.json" in names
        assert not any("__pycache__" in name for name in names)
        with zipfile.ZipFile(out) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == release.manifest_version(REPO)


class TestCli:
    """Command line interface."""

    def test_check_fails_with_annotation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = _make_repo(tmp_path)
        (repo / "release-notes" / "v1.2.3.md").unlink()
        monkeypatch.setattr(release, "ROOT", repo)
        monkeypatch.setattr(release.check_release, "__defaults__", (repo,))
        assert release.main(["check"]) == 1
        assert "::error::Release notes release-notes/v1.2.3.md are missing" in capsys.readouterr().err

    def test_version_and_notes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.setattr(release.manifest_version, "__defaults__", (repo,))
        monkeypatch.setattr(release.notes_path, "__defaults__", (repo,))
        monkeypatch.setattr(release, "ROOT", repo)
        assert release.main(["version"]) == 0
        assert release.main(["notes"]) == 0
        assert capsys.readouterr().out.split() == ["1.2.3", "release-notes/v1.2.3.md"]

    def test_zip(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        out = tmp_path / "z.zip"
        assert release.main(["zip", str(out)]) == 0
        assert out.is_file()
        shutil.rmtree(tmp_path)
