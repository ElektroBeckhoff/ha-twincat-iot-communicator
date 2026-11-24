"""Resolve PLC icon names to Home Assistant icons.

The PLC sends icon names in ``iot.Icon`` / ``iot.NestedStructIcon`` metadata
and in the ``Icon`` field of the Desc message. Two formats exist:

- predefined icons of the TwinCAT IoT app, e.g. ``Lightbulb``; they always
  resolve through ``TCIOT_ICON_MAP`` to an ``mdi:`` icon
- Google Material Symbols, ``md:`` + Google name in snake_case, e.g.
  ``md:heat_pump`` (TwinCAT IoT app 1.8.2 and later). How they are shown
  depends on the icon mode:

  - ``material``: the original symbol from the bundled frontend icon set,
    ``tciot:heat_pump``; a name the icon set does not know falls back to MDI
  - ``mdi``: the closest Material Design Icon, from the curated table
    (``MATERIAL_ICON_MAP``) or the generated automatic table

An unknown name resolves to ``None`` so the caller keeps its default icon
instead of showing an empty one.
"""

from __future__ import annotations

import logging
from typing import Final

from .const import ICON_MODE_MATERIAL, ICONSET_PREFIX, TCIOT_ICON_MAP
from .material_icons import MATERIAL_ICON_MAP
from .material_icons_auto import MATERIAL_ICON_AUTO_MAP
from .material_symbols import MATERIAL_SYMBOL_NAMES

_LOGGER = logging.getLogger(__name__)

MATERIAL_ICON_PREFIX: Final = "md:"

# Unknown names already logged; keeps the log quiet on repeated metadata.
# Bounded because the names come from the PLC.
_reported_unknown: set[str] = set()
_MAX_REPORTED_UNKNOWN: Final = 256


def normalize_icon_name(name: object) -> str | None:
    """Return the lookup key of a PLC icon name, or ``None`` when empty.

    App icon names are case-sensitive and stay unchanged. Google icon names
    get a lower-case ``md:`` prefix and a snake_case name, so
    ``MD:Heat-Pump`` and ``md:heat_pump`` are the same icon.
    """
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name:
        return None
    if name[: len(MATERIAL_ICON_PREFIX)].lower() == MATERIAL_ICON_PREFIX:
        symbol = (
            name[len(MATERIAL_ICON_PREFIX) :]
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        return f"{MATERIAL_ICON_PREFIX}{symbol}" if symbol else None
    return name


def is_material_icon(name: object) -> bool:
    """Return True when *name* is a Google Material Symbol (``md:...``)."""
    key = normalize_icon_name(name)
    return key is not None and key.startswith(MATERIAL_ICON_PREFIX)


def material_symbol_to_mdi(symbol: str) -> str | None:
    """Return the MDI icon for a Google symbol name, or ``None``."""
    return MATERIAL_ICON_MAP.get(symbol) or MATERIAL_ICON_AUTO_MAP.get(symbol)


def resolve_icon(name: object, mode: str = ICON_MODE_MATERIAL) -> str | None:
    """Return the Home Assistant icon for a PLC icon name, or ``None``.

    *mode* is the configured icon mode for Google Material Symbols
    (``material`` or ``mdi``); it has no effect on app icon names.
    """
    key = normalize_icon_name(name)
    if key is None:
        return None
    if key.startswith(MATERIAL_ICON_PREFIX):
        symbol = key[len(MATERIAL_ICON_PREFIX) :]
        if mode == ICON_MODE_MATERIAL and symbol in MATERIAL_SYMBOL_NAMES:
            return f"{ICONSET_PREFIX}:{symbol}"
        mapped = material_symbol_to_mdi(symbol)
    else:
        mapped = TCIOT_ICON_MAP.get(key)
    if (
        mapped is None
        and key not in _reported_unknown
        and len(_reported_unknown) < _MAX_REPORTED_UNKNOWN
    ):
        _reported_unknown.add(key)
        _LOGGER.debug(
            "PLC icon %r has no Home Assistant mapping; using the default icon",
            name,
        )
    return mapped
