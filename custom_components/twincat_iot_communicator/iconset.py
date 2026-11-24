"""Frontend icon set with the original Google Material Symbols.

The integration ships a small frontend module (``frontend/tciot-icons.js``)
and the symbol paths (``frontend/material_symbols/*.json``, Apache-2.0). The
module registers the custom icon set ``tciot`` in the Home Assistant
frontend, so an entity icon ``tciot:heat_pump`` shows the original symbol.
Paths are loaded on demand from Home Assistant itself, so no internet access
is needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, FRONTEND_ICONSET_JS, FRONTEND_URL_BASE

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"
DATA_ICONSET: HassKey[bool] = HassKey(f"{DOMAIN}_iconset")


def iconset_available(hass: HomeAssistant) -> bool:
    """Return True when the frontend icon set has been registered."""
    return hass.data.get(DATA_ICONSET, False)


async def async_register_iconset(hass: HomeAssistant) -> bool:
    """Serve the icon set and load it into the frontend (once per start).

    Returns False when the frontend or http component is not loaded; the
    integration then shows Google symbols as MDI icons.
    """
    if DATA_ICONSET in hass.data:
        return hass.data[DATA_ICONSET]
    hass.data[DATA_ICONSET] = False

    if "frontend" not in hass.config.components or hass.http is None:
        _LOGGER.debug("Frontend not loaded; Google symbols use MDI icons")
        return False

    # Imported here: the frontend component is an after_dependency only.
    from homeassistant.components.frontend import (  # noqa: PLC0415
        add_extra_js_url,
    )
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version or "0")
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, str(FRONTEND_DIR), True)],
        )
    except RuntimeError:
        # Path already registered (e.g. after a reload of the integration).
        _LOGGER.debug("Static path %s already registered", FRONTEND_URL_BASE)
    # The version in the URL busts the browser cache after an update; the
    # module passes it on to the symbol files.
    add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/{FRONTEND_ICONSET_JS}?v={version}")
    hass.data[DATA_ICONSET] = True
    return True
