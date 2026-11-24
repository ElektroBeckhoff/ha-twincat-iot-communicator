#!/usr/bin/env python3
"""Generate the Google Material Symbols data of the integration.

Run from the repository root:  python3 script/generate_material_icons.py

Inputs (downloaded, versions pinned below):
- @material-symbols/svg-400  outlined SVGs, weight 400 (Apache-2.0)
- Google codepoints file     all icon names incl. renamed (alias) names
- Google repository SVGs     icons the npm package does not ship yet
- @mdi/svg                   MDI icon names and aliases (Apache-2.0 / OFL)

Outputs:
- custom_components/.../frontend/material_symbols/<chunk>.json
    icon paths for the frontend icon set, one file per first character
- custom_components/.../frontend/material_symbols/names.json
    all names, for the Home Assistant icon picker
- custom_components/.../frontend/material_symbols/LICENSE
- custom_components/.../material_symbols.py
    MATERIAL_SYMBOL_NAMES, the names the frontend icon set can draw
- custom_components/.../material_icons_auto.py
    MATERIAL_ICON_AUTO_MAP, automatic MDI fallback for every Google name
    that is not in the curated MATERIAL_ICON_MAP (material_icons.py)

The curated table material_icons.py is maintained by hand and only read here.
"""

from __future__ import annotations

import collections
import concurrent.futures
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import urllib.parse
import urllib.request

SYMBOLS_NPM = (
    "https://registry.npmjs.org/@material-symbols/svg-400/-/svg-400-0.49.0.tgz"
)
CODEPOINTS = (
    "https://raw.githubusercontent.com/google/material-design-icons/master/"
    "variablefont/MaterialSymbolsOutlined%5BFILL%2CGRAD%2Copsz%2Cwght%5D.codepoints"
)
GOOGLE_SVG = (
    "https://raw.githubusercontent.com/google/material-design-icons/master/"
    "symbols/web/{name}/materialsymbolsoutlined/{name}_24px.svg"
)
MDI_NPM = "https://registry.npmjs.org/@mdi/svg/-/svg-7.4.47.tgz"

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "twincat_iot_communicator"
FRONTEND = COMPONENT / "frontend" / "material_symbols"
DEFAULT_VIEWBOX = "0 -960 960 960"
NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        return resp.read()


def _parse_svg(svg: str) -> tuple[str, str]:
    """Return (path data, viewBox) of a single-path Material Symbols SVG."""
    paths = re.findall(r'<path d="([^"]+)"', svg)
    if len(paths) != 1 or re.search(r"<(?!svg|path|/svg)\w+", svg):
        raise ValueError("expected exactly one <path>")
    match = re.search(r'viewBox="([^"]+)"', svg)
    if match:
        return paths[0], match.group(1)
    size = re.search(r'height="(\d+)"', svg)
    side = size.group(1) if size else "24"
    return paths[0], f"0 0 {side} {side}"


def load_symbols() -> tuple[dict[str, tuple[str, str]], str]:
    """Return {name: (path, viewBox)} from the npm package, plus its LICENSE."""
    data = _get(SYMBOLS_NPM)
    icons: dict[str, tuple[str, str]] = {}
    license_text = ""
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            name = member.name
            if name == "package/LICENSE":
                license_text = tar.extractfile(member).read().decode()
                continue
            if not name.startswith("package/outlined/") or not name.endswith(".svg"):
                continue
            icon = name.removeprefix("package/outlined/").removesuffix(".svg")
            if icon.endswith("-fill"):
                continue
            icons[icon] = _parse_svg(tar.extractfile(member).read().decode())
    return icons, license_text


def load_codepoints() -> dict[str, str]:
    """Return {name: codepoint} of every name the Google font knows."""
    result: dict[str, str] = {}
    for line in _get(CODEPOINTS).decode().splitlines():
        if line.strip():
            name, codepoint = line.split()
            result[name] = codepoint
    return result


def complete_symbols(
    icons: dict[str, tuple[str, str]], codepoints: dict[str, str],
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Add renamed names (same codepoint) and icons only Google ships yet.

    Returns the completed icon dict and {alias: canonical name}.
    """
    by_codepoint: dict[str, list[str]] = collections.defaultdict(list)
    for name, codepoint in codepoints.items():
        by_codepoint[codepoint].append(name)

    aliases: dict[str, str] = {}
    missing: list[str] = []
    for name, codepoint in sorted(codepoints.items()):
        if name in icons:
            continue
        twins = sorted(n for n in by_codepoint[codepoint] if n in icons)
        if twins:
            aliases[name] = twins[0]
        else:
            missing.append(name)

    def fetch(name: str) -> tuple[str, tuple[str, str] | None]:
        try:
            return name, _parse_svg(_get(GOOGLE_SVG.format(name=name)).decode())
        except Exception as err:
            print(f"  skip {name}: {err}", file=sys.stderr)
            return name, None

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for name, icon in pool.map(fetch, missing):
            if icon is not None:
                icons[name] = icon

    completed = dict(icons)
    for alias, canonical in aliases.items():
        completed[alias] = icons[canonical]
    return completed, aliases


def load_mdi() -> tuple[set[str], dict[str, str]]:
    """Return canonical non-deprecated MDI names and {alias: canonical}."""
    data = _get(MDI_NPM)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        meta = json.load(tar.extractfile("package/meta.json"))
    names = {icon["name"] for icon in meta if not icon.get("deprecated")}
    aliases = {
        alias: icon["name"]
        for icon in meta
        if not icon.get("deprecated")
        for alias in icon["aliases"]
    }
    return names, aliases


def auto_mdi(
    names: list[str],
    curated: dict[str, str],
    symbol_aliases: dict[str, str],
    mdi_names: set[str],
    mdi_aliases: dict[str, str],
) -> dict[str, str]:
    """MDI fallback for Google names outside the curated table.

    A Google name maps when the same name (snake_case to kebab-case) is an
    MDI icon or an MDI alias. A renamed Google name uses its current name.
    """
    result: dict[str, str] = {}
    for name in names:
        if name in curated:
            continue
        canonical = symbol_aliases.get(name, name)
        if canonical in curated:
            result[name] = curated[canonical]
            continue
        kebab = canonical.replace("_", "-")
        target = kebab if kebab in mdi_names else mdi_aliases.get(kebab)
        if target and target in mdi_names:
            result[name] = f"mdi:{target}"
    return result


def write_frontend(icons: dict[str, tuple[str, str]], license_text: str) -> None:
    FRONTEND.mkdir(parents=True, exist_ok=True)
    for old in FRONTEND.glob("*.json"):
        old.unlink()
    chunks: dict[str, dict[str, object]] = collections.defaultdict(dict)
    for name in sorted(icons):
        path, viewbox = icons[name]
        key = name[0] if name[0].isalpha() else "0"
        chunks[key][name] = path if viewbox == DEFAULT_VIEWBOX else [path, viewbox]
    for key, chunk in chunks.items():
        (FRONTEND / f"{key}.json").write_text(
            json.dumps(chunk, separators=(",", ":")) + "\n", encoding="utf-8",
        )
    (FRONTEND / "names.json").write_text(
        json.dumps(sorted(icons), separators=(",", ":")) + "\n", encoding="utf-8",
    )
    (FRONTEND / "LICENSE").write_text(license_text, encoding="utf-8")


def _py_header(doc: str) -> str:
    return (
        f'"""{doc}\n\nGenerated by script/generate_material_icons.py, do not edit.\n"""\n\n'
        "from __future__ import annotations\n\nfrom typing import Final\n\n"
    )


def write_python(names: list[str], auto: dict[str, str]) -> None:
    body = "".join(f'        "{n}",\n' for n in names)
    (COMPONENT / "material_symbols.py").write_text(
        _py_header(
            "Google Material Symbols the bundled frontend icon set can draw.",
        )
        + "MATERIAL_SYMBOL_NAMES: Final[frozenset[str]] = frozenset(\n    (\n"
        + body
        + "    )\n)\n",
        encoding="utf-8",
    )
    body = "".join(f'    "{k}": "{v}",\n' for k, v in sorted(auto.items()))
    (COMPONENT / "material_icons_auto.py").write_text(
        _py_header(
            "Automatic MDI fallback for Google Material Symbols.\n\n"
            "Covers Google names outside the curated MATERIAL_ICON_MAP whose\n"
            "name (or MDI alias) exists in @mdi/svg 7.4.47. Best effort: the\n"
            "curated table in material_icons.py always wins.",
        )
        + "MATERIAL_ICON_AUTO_MAP: Final[dict[str, str]] = {\n"
        + body
        + "}\n",
        encoding="utf-8",
    )


def main() -> None:
    sys.path.insert(0, str(COMPONENT))
    from material_icons import MATERIAL_ICON_MAP  # noqa: PLC0415

    print("Material Symbols (npm) ...")
    icons, license_text = load_symbols()
    print("Codepoints ...")
    codepoints = load_codepoints()
    icons, symbol_aliases = complete_symbols(icons, codepoints)
    bad = [n for n in icons if not NAME_RE.match(n)]
    if bad:
        raise SystemExit(f"unexpected icon names: {bad[:10]}")
    missing = [n for n in MATERIAL_ICON_MAP if n not in icons]
    if missing:
        raise SystemExit(f"curated icons without SVG: {missing}")
    print("MDI ...")
    mdi_names, mdi_aliases = load_mdi()
    names = sorted(icons)
    auto = auto_mdi(names, MATERIAL_ICON_MAP, symbol_aliases, mdi_names, mdi_aliases)
    write_frontend(icons, license_text)
    write_python(names, auto)
    print(
        f"{len(names)} symbols ({len(symbol_aliases)} renamed names), "
        f"{len(MATERIAL_ICON_MAP)} curated + {len(auto)} automatic MDI mappings",
    )


if __name__ == "__main__":
    main()
