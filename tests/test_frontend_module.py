"""Tests for the frontend icon set module and how Home Assistant serves it.

The module itself (``frontend/tciot-icons.js``) runs in Node with a
file-backed ``fetch`` (``tests/frontend/iconset_harness.mjs``); the serving
side is tested against the real Home Assistant HTTP server.
"""

from __future__ import annotations

from http import HTTPStatus
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest

from custom_components.twincat_iot_communicator import iconset
from custom_components.twincat_iot_communicator.const import (
    DOMAIN,
    FRONTEND_ICONSET_JS,
    FRONTEND_URL_BASE,
    ICON_MODE_MATERIAL,
    ICON_MODES,
    ICONSET_PREFIX,
)
from custom_components.twincat_iot_communicator.icon_helper import resolve_icon
from custom_components.twincat_iot_communicator.material_symbols import (
    MATERIAL_SYMBOL_NAMES,
)

COMPONENT_DIR = iconset.FRONTEND_DIR.parent
SYMBOLS_DIR = iconset.FRONTEND_DIR / "material_symbols"
HARNESS = Path(__file__).parent / "frontend" / "iconset_harness.mjs"
DEFAULT_VIEWBOX = "0 -960 960 960"


def _chunk(key: str) -> dict[str, Any]:
    return json.loads((SYMBOLS_DIR / f"{key}.json").read_text(encoding="utf-8"))


def _expected(name: str) -> dict[str, str]:
    """Return what getIcon() must give for a symbol, read from the data files."""
    key = name[0] if "a" <= name[0] <= "z" else "0"
    entry = _chunk(key)[name]
    if isinstance(entry, list):
        return {"path": entry[0], "viewBox": entry[1]}
    return {"path": entry, "viewBox": DEFAULT_VIEWBOX}


# ── The module in Node ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    """Run the module in Node once and return the harness report."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is required to test the frontend module in CI")
        pytest.skip("node is not installed")
    result = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [node, str(HARNESS), str(iconset.FRONTEND_DIR / FRONTEND_ICONSET_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestFrontendModule:
    """Behaviour of the custom icon set in the browser."""

    def test_registers_icon_set(self, report: dict[str, Any]) -> None:
        """The set is added under its prefix; other icon sets stay."""
        assert report["api"] == ["function", "function"]
        assert report["otherKept"] is True

    def test_get_icon(self, report: dict[str, Any]) -> None:
        """An icon is the path of the data file with its view box."""
        assert report["heatPump"] == _expected("heat_pump")
        assert report["home"] == _expected("home")
        assert report["heatPump"]["path"]

    def test_names_are_normalized(self, report: dict[str, Any]) -> None:
        """Case, spaces and hyphens do not matter, like in the backend."""
        assert report["normalized"] == _expected("heat_pump")
        assert report["spaced"] == _expected("heat_pump")

    def test_digit_names_use_shared_chunk(self, report: dict[str, Any]) -> None:
        """Names that do not start with a letter live in 0.json."""
        assert report["digit"] == _expected("10k")
        assert report["digitRequests"] == 1

    def test_unknown_names_give_empty_icon(self, report: dict[str, Any]) -> None:
        """Unknown or empty names never throw; the icon is just empty."""
        assert report["unknown"] == {"path": ""}
        assert report["empty"] == {"path": ""}
        assert report["notAString"] == {"path": ""}

    def test_chunk_is_loaded_once(self, report: dict[str, Any]) -> None:
        """Four icons of one chunk, also requested in parallel: one download."""
        assert report["hRequests"] == 1

    def test_failed_load_is_retried(self, report: dict[str, Any]) -> None:
        """A failed download gives an empty icon once and is not cached."""
        assert report["failed"] == {"path": ""}
        assert report["warnedOnFailure"] == 1
        assert report["retried"] == _expected("water_drop")
        assert report["wRequests"] == 2
        assert report["warnings"] == 1

    def test_icon_list(self, report: dict[str, Any]) -> None:
        """The icon picker list has every symbol and is downloaded once."""
        assert report["listLength"] == len(MATERIAL_SYMBOL_NAMES)
        assert report["listShapeOk"] is True
        assert all(e["name"] in MATERIAL_SYMBOL_NAMES for e in report["listSample"])
        assert report["namesRequests"] == 1

    def test_requests_are_versioned_and_local(self, report: dict[str, Any]) -> None:
        """Every download carries the cache-busting version and stays local."""
        assert report["allVersioned"] is True
        assert report["allBelowModule"] is True

    def test_backend_and_frontend_agree(self) -> None:
        """Every icon the backend hands out exists in the chunk the module loads."""
        chunks: dict[str, dict[str, Any]] = {}
        for name in MATERIAL_SYMBOL_NAMES:
            icon = resolve_icon(f"md:{name}", ICON_MODE_MATERIAL)
            assert icon == f"{ICONSET_PREFIX}:{name}"
            key = name[0] if "a" <= name[0] <= "z" else "0"
            if key not in chunks:
                chunks[key] = _chunk(key)
            assert name in chunks[key], name

    def test_module_prefix_matches_backend(self) -> None:
        """The prefix in the module is the one the backend uses."""
        js = (iconset.FRONTEND_DIR / FRONTEND_ICONSET_JS).read_text(encoding="utf-8")
        assert f'const PREFIX = "{ICONSET_PREFIX}";' in js
        assert "http://" not in js
        assert "https://" not in js


# ── Serving through Home Assistant ────────────────────────────────────


@pytest.fixture
async def served(hass: HomeAssistant, hass_client_no_auth: Any) -> Any:
    """Set up the integration with the real HTTP server and a frontend."""
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
    client = await hass_client_no_auth()
    return client, add_js


class TestServedByHomeAssistant:
    """async_setup serves the icon set through the real HTTP server."""

    async def test_module_url_is_served(self, hass: HomeAssistant, served: Any) -> None:
        """The URL given to the frontend returns the module, with caching."""
        client, add_js = served
        add_js.assert_called_once()
        assert add_js.call_args.args[0] is hass
        url = add_js.call_args.args[1]
        manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text())
        assert url == (
            f"{FRONTEND_URL_BASE}/{FRONTEND_ICONSET_JS}?v={manifest['version']}"
        )
        assert iconset.iconset_available(hass) is True

        resp = await client.get(url)
        assert resp.status == HTTPStatus.OK
        assert "javascript" in resp.headers["Content-Type"]
        assert "max-age" in resp.headers.get("Cache-Control", "")
        body = await resp.text()
        assert body == (iconset.FRONTEND_DIR / FRONTEND_ICONSET_JS).read_text(
            encoding="utf-8",
        )

    async def test_symbol_files_are_served(self, served: Any) -> None:
        """Chunks and the name list are reachable where the module looks."""
        client, _ = served
        resp = await client.get(f"{FRONTEND_URL_BASE}/material_symbols/h.json?v=1")
        assert resp.status == HTTPStatus.OK
        assert (await resp.json(content_type=None))["heat_pump"] == _chunk("h")[
            "heat_pump"
        ]
        resp = await client.get(f"{FRONTEND_URL_BASE}/material_symbols/names.json")
        assert resp.status == HTTPStatus.OK
        assert set(await resp.json(content_type=None)) == MATERIAL_SYMBOL_NAMES

    @pytest.mark.parametrize(
        "path",
        [
            "/material_symbols/missing.json",
            "/../manifest.json",
            "/%2e%2e/manifest.json",
            "/../const.py",
        ],
    )
    async def test_nothing_else_is_served(self, served: Any, path: str) -> None:
        """Only the frontend folder is public, not the integration code."""
        client, _ = served
        resp = await client.get(f"{FRONTEND_URL_BASE}{path}")
        assert resp.status in (HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN)

    async def test_only_public_files_in_frontend_dir(self) -> None:
        """The served folder holds nothing but the module, data and license."""
        files = {
            p.relative_to(iconset.FRONTEND_DIR).as_posix()
            for p in iconset.FRONTEND_DIR.rglob("*")
            if p.is_file()
        }
        allowed = {FRONTEND_ICONSET_JS, "material_symbols/LICENSE"}
        extra = {f for f in files - allowed if not f.endswith(".json")}
        assert extra == set()
        assert all(f.startswith("material_symbols/") for f in files - allowed)


class TestSetupWithoutFrontend:
    """A Home Assistant without frontend still sets the integration up."""

    async def test_setup_without_frontend(self, hass: HomeAssistant) -> None:
        """No frontend: setup succeeds and the icon set is reported missing."""
        assert await async_setup_component(hass, DOMAIN, {})
        assert iconset.iconset_available(hass) is False


# ── Texts and packaging ───────────────────────────────────────────────


def _keys(node: Any, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return {prefix}
    out: set[str] = set()
    for key, value in node.items():
        out |= _keys(value, f"{prefix}/{key}")
    return out


class TestTexts:
    """The option is translated completely."""

    @pytest.mark.parametrize("language", ["en", "de"])
    def test_translations_match_strings(self, language: str) -> None:
        """Every language has exactly the keys of strings.json."""
        strings = json.loads((COMPONENT_DIR / "strings.json").read_text("utf-8"))
        lang = json.loads(
            (COMPONENT_DIR / "translations" / f"{language}.json").read_text("utf-8"),
        )
        assert _keys(lang) == _keys(strings)

    @pytest.mark.parametrize("file", ["strings.json", "translations/de.json"])
    def test_icon_mode_texts(self, file: str) -> None:
        """Options form and every selectable mode have a text."""
        data = json.loads((COMPONENT_DIR / file).read_text("utf-8"))
        init = data["options"]["step"]["init"]
        assert init["data"]["icon_mode"]
        assert init["data_description"]["icon_mode"]
        assert set(data["selector"]["icon_mode"]["options"]) == set(ICON_MODES)
        for step in ("select_devices", "reconfigure"):
            assert "icon_mode" not in data["config"]["step"][step]["data"]

    def test_version_is_consistent(self) -> None:
        """Manifest, README badge and changelog name the same version."""
        root = COMPONENT_DIR.parent.parent
        version = json.loads((COMPONENT_DIR / "manifest.json").read_text())["version"]
        assert f"Version-{version}-" in (root / "README.md").read_text("utf-8")
        changelog = (root / "docs" / "changelog.md").read_text("utf-8")
        first = next(line for line in changelog.splitlines() if line.startswith("## "))
        assert first == f"## [{version}]"
