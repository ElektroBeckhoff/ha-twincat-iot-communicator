"""Tests for PLC icon resolution (app icons and Google Material Symbols)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from unittest.mock import AsyncMock, patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.twincat_iot_communicator import icon_helper, iconset
from custom_components.twincat_iot_communicator.binary_sensor import (
    ICON_BINARY_SENSOR_CLASS_MAP,
    TcIotDatatypeBinarySensor,
    TcIotHubStatus,
)
from custom_components.twincat_iot_communicator.const import (
    CONF_ICON_MODE,
    FRONTEND_ICONSET_JS,
    FRONTEND_URL_BASE,
    ICON_MODE_MATERIAL,
    ICON_MODE_MDI,
    META_ICON,
    TCIOT_ICON_MAP,
    WIDGET_TYPE_PLUG,
)
from custom_components.twincat_iot_communicator.coordinator import TcIotCoordinator
from custom_components.twincat_iot_communicator.entity import TcIotEntity
from custom_components.twincat_iot_communicator.icon_helper import (
    is_material_icon,
    material_symbol_to_mdi,
    normalize_icon_name,
    resolve_icon,
)
from custom_components.twincat_iot_communicator.material_icons import (
    MATERIAL_ICON_MAP,
)
from custom_components.twincat_iot_communicator.material_icons_auto import (
    MATERIAL_ICON_AUTO_MAP,
)
from custom_components.twincat_iot_communicator.material_symbols import (
    MATERIAL_SYMBOL_NAMES,
)
from custom_components.twincat_iot_communicator.models import (
    DeviceContext,
    ViewData,
    WidgetData,
    WidgetMetaData,
)
from custom_components.twincat_iot_communicator.sensor import (
    ICON_SENSOR_CLASS_MAP,
    TcIotDatatypeSensor,
)

from .conftest import (
    MOCK_DEVICE_NAME,
    MOCK_ENTRY_DATA,
    attach_entity_to_hass,
    build_device_with_widgets,
    create_mock_coordinator,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYMBOLS_DIR = iconset.FRONTEND_DIR / "material_symbols"


def _read_name_list(name: str) -> list[str]:
    """Read a fixture with one name per line ('#' starts a comment line)."""
    lines = (FIXTURES_DIR / name).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


# Canonical icon names of @mdi/svg 7.4.47, the MDI release of the HA frontend.
MDI_ICONS = frozenset(_read_name_list("mdi_icons_7.4.47.txt"))


@pytest.fixture(autouse=True)
def _reset_unknown_cache() -> None:
    """Every test starts with an empty 'already logged' cache."""
    icon_helper._reported_unknown.clear()


# ── Icon data ─────────────────────────────────────────────────────────


class TestMdiTables:
    """The MDI tables only point to real MDI icons and real Google names."""

    @pytest.mark.parametrize(
        "table",
        [MATERIAL_ICON_MAP, MATERIAL_ICON_AUTO_MAP, TCIOT_ICON_MAP],
        ids=["curated", "auto", "app"],
    )
    def test_values_are_existing_mdi_icons(self, table: dict[str, str]) -> None:
        """Every target is a canonical icon of the MDI release HA ships."""
        bad = {
            k: v
            for k, v in table.items()
            if not v.startswith("mdi:") or v.removeprefix("mdi:") not in MDI_ICONS
        }
        assert bad == {}

    def test_curated_keys_are_google_symbols(self) -> None:
        """Curated keys are Google names in the PLC format that really exist."""
        pattern = re.compile(r"^[a-z0-9][a-z0-9_]*$")
        assert [k for k in MATERIAL_ICON_MAP if not pattern.match(k)] == []
        assert set(MATERIAL_ICON_MAP) - MATERIAL_SYMBOL_NAMES == set()

    def test_auto_table_does_not_shadow_curated(self) -> None:
        """The generated table never redefines a curated entry."""
        assert set(MATERIAL_ICON_AUTO_MAP) & set(MATERIAL_ICON_MAP) == set()
        assert set(MATERIAL_ICON_AUTO_MAP) - MATERIAL_SYMBOL_NAMES == set()

    @pytest.mark.parametrize(
        ("google", "mdi"),
        [
            ("heat_pump", "mdi:heat-pump"),
            ("thermostat", "mdi:thermostat"),
            ("roller_shades", "mdi:roller-shade"),
            ("roller_shades_closed", "mdi:roller-shade-closed"),
            ("detector_smoke", "mdi:smoke-detector"),
            ("window", "mdi:window-closed-variant"),
            ("park", "mdi:tree"),
            ("favorite", "mdi:heart"),
            ("ac_unit", "mdi:air-conditioner"),
            ("ev_charger", "mdi:ev-station"),
        ],
    )
    def test_curated_mappings(self, google: str, mdi: str) -> None:
        """Spot checks, including names whose MDI alias would be misleading."""
        assert material_symbol_to_mdi(google) == mdi

    def test_auto_mapping_covers_other_symbols(self) -> None:
        """Symbols outside the curated table map by name where MDI has them."""
        assert "home" not in MATERIAL_ICON_MAP
        assert material_symbol_to_mdi("home") == "mdi:home"

    def test_device_class_keys_are_known_icons(self) -> None:
        """Device-class maps only use icon names the PLC can actually send."""
        for key in (*ICON_SENSOR_CLASS_MAP, *ICON_BINARY_SENSOR_CLASS_MAP):
            if key.startswith("md:"):
                assert key.removeprefix("md:") in MATERIAL_SYMBOL_NAMES, key
            else:
                assert key in TCIOT_ICON_MAP, key


class TestFrontendIconData:
    """The bundled symbol files match MATERIAL_SYMBOL_NAMES."""

    def test_files_cover_all_names(self) -> None:
        """Every name is drawable and lives in the chunk the module loads."""
        names = json.loads((SYMBOLS_DIR / "names.json").read_text())
        assert set(names) == MATERIAL_SYMBOL_NAMES
        seen: set[str] = set()
        for chunk in SYMBOLS_DIR.glob("*.json"):
            if chunk.name == "names.json":
                continue
            key = chunk.stem
            for name, entry in json.loads(chunk.read_text()).items():
                expected = name[0] if "a" <= name[0] <= "z" else "0"
                assert expected == key, name
                path = entry[0] if isinstance(entry, list) else entry
                assert path, name
                if isinstance(entry, list):
                    assert re.match(r"^-?\d+ -?\d+ \d+ \d+$", entry[1]), name
                seen.add(name)
        assert seen == MATERIAL_SYMBOL_NAMES

    def test_license_and_module_shipped(self) -> None:
        """The Apache-2.0 license and the frontend module are part of the package."""
        assert "Apache License" in (SYMBOLS_DIR / "LICENSE").read_text()
        js = (iconset.FRONTEND_DIR / FRONTEND_ICONSET_JS).read_text()
        assert 'const PREFIX = "tciot";' in js
        assert "window.customIcons[PREFIX]" in js

    def test_common_symbols_present(self) -> None:
        """Current and renamed Google names are both drawable."""
        for name in ("heat_pump", "home", "sensor_door", "delete_outline", "phone"):
            assert name in MATERIAL_SYMBOL_NAMES, name


# ── normalize / resolve ───────────────────────────────────────────────


class TestNormalizeIconName:
    """normalize_icon_name() builds the lookup key."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("md:heat_pump", "md:heat_pump"),
            ("MD:Heat_Pump", "md:heat_pump"),
            ("md:heat-pump", "md:heat_pump"),
            ("  md: heat_pump  ", "md:heat_pump"),
            ("md:heat pump", "md:heat_pump"),
            ("Lightbulb", "Lightbulb"),
            (" Lightbulb ", "Lightbulb"),
            ("lightbulb", "lightbulb"),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        """Google names are case/separator tolerant; app names stay as they are."""
        assert normalize_icon_name(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "md:", "md:   ", 42, ["md:x"]])
    def test_empty_or_invalid(self, raw: object) -> None:
        """Empty strings, a bare prefix and non-strings give no key."""
        assert normalize_icon_name(raw) is None

    def test_is_material_icon(self) -> None:
        """Only the md: prefix marks a Google icon."""
        assert is_material_icon("md:heat_pump")
        assert is_material_icon("MD:heat_pump")
        assert not is_material_icon("Heat")
        assert not is_material_icon("md:")
        assert not is_material_icon(None)


class TestResolveIcon:
    """resolve_icon() turns any PLC icon name into a Home Assistant icon."""

    @pytest.mark.parametrize("mode", [ICON_MODE_MATERIAL, ICON_MODE_MDI])
    def test_app_icon(self, mode: str) -> None:
        """App icons are MDI icons in both modes."""
        assert resolve_icon("Lightbulb", mode) == "mdi:lightbulb"
        assert resolve_icon("TwinCAT", mode) == "mdi:cat"

    def test_app_icon_is_case_sensitive(self) -> None:
        """App icon names are fixed names; another spelling is not guessed."""
        assert resolve_icon("lightbulb") is None

    def test_material_mode_uses_icon_set(self) -> None:
        """Material mode shows the original symbol from the bundled icon set."""
        assert resolve_icon("md:heat_pump", ICON_MODE_MATERIAL) == "tciot:heat_pump"
        assert resolve_icon("MD:Heat-Pump", ICON_MODE_MATERIAL) == "tciot:heat_pump"
        assert resolve_icon("md:home") == "tciot:home"

    def test_material_mode_falls_back_to_mdi(self) -> None:
        """A name the icon set cannot draw still gets an MDI icon if one fits."""
        with patch.object(icon_helper, "MATERIAL_SYMBOL_NAMES", frozenset()):
            assert resolve_icon("md:heat_pump", ICON_MODE_MATERIAL) == "mdi:heat-pump"

    def test_mdi_mode(self) -> None:
        """MDI mode uses the curated table first, then the automatic one."""
        assert resolve_icon("md:heat_pump", ICON_MODE_MDI) == "mdi:heat-pump"
        assert resolve_icon("md:home", ICON_MODE_MDI) == "mdi:home"

    @pytest.mark.parametrize("name", sorted(MATERIAL_SYMBOL_NAMES))
    def test_every_symbol_resolves_in_material_mode(self, name: str) -> None:
        """Each drawable Google symbol resolves to the icon set."""
        assert resolve_icon(f"md:{name}") == f"tciot:{name}"

    @pytest.mark.parametrize("mode", [ICON_MODE_MATERIAL, ICON_MODE_MDI])
    @pytest.mark.parametrize(
        "name", ["md:does_not_exist", "Unknown_App_Icon", "", None, "md:", 7],
    )
    def test_unknown_gives_none(self, name: object, mode: str) -> None:
        """Unknown names keep the platform default instead of an empty icon."""
        assert resolve_icon(name, mode) is None

    def test_unknown_icon_logged_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unmapped name is logged once at debug level, not on every update."""
        caplog.set_level(logging.DEBUG, logger=icon_helper.__name__)
        for _ in range(3):
            resolve_icon("md:my_custom_symbol")
        hits = [r for r in caplog.records if "md:my_custom_symbol" in r.getMessage()]
        assert len(hits) == 1
        assert hits[0].levelno == logging.DEBUG

    def test_unknown_log_cache_is_bounded(self) -> None:
        """PLC-supplied names cannot grow the log cache without bound."""
        for i in range(icon_helper._MAX_REPORTED_UNKNOWN + 50):
            resolve_icon(f"md:unknown_{i}")
        assert len(icon_helper._reported_unknown) == icon_helper._MAX_REPORTED_UNKNOWN


# ── Entities ──────────────────────────────────────────────────────────


def _make_base_entity(
    hass: HomeAssistant, entry, icon: object, mode: str = ICON_MODE_MATERIAL,
) -> tuple[TcIotEntity, WidgetData]:
    meta = WidgetMetaData(
        display_name="Test Widget",
        widget_type=WIDGET_TYPE_PLUG,
        raw={} if icon is None else {META_ICON: icon},
    )
    widget = WidgetData(
        widget_id="stTest.widget",
        path="stTest.widget",
        metadata=meta,
        values={"bOn": True},
        friendly_path="Test Widget",
    )
    dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
    dev.online = True
    dev.widgets[widget.path] = widget
    coordinator = create_mock_coordinator(hass, entry, {MOCK_DEVICE_NAME: dev})
    coordinator.icon_mode = mode
    entity = TcIotEntity(coordinator, MOCK_DEVICE_NAME, widget)
    attach_entity_to_hass(hass, entity, "switch")
    return entity, widget


def _with_icon(widget: WidgetData, icon: object) -> WidgetData:
    raw = dict(widget.metadata.raw)
    if icon is None:
        raw.pop(META_ICON, None)
    else:
        raw[META_ICON] = icon
    meta = WidgetMetaData(
        display_name=widget.metadata.display_name,
        widget_type=widget.metadata.widget_type,
        raw=raw,
    )
    return WidgetData(
        widget_id=widget.widget_id,
        path=widget.path,
        metadata=meta,
        values=dict(widget.values),
        friendly_path=widget.friendly_path,
    )


class TestEntityIcon:
    """The widget entity icon follows iot.Icon, also at runtime."""

    def test_material_icon_on_create(self, hass, mock_config_entry) -> None:
        """A Google icon becomes the icon-set icon in material mode."""
        entity, _ = _make_base_entity(hass, mock_config_entry, "md:heat_pump")
        assert entity.icon == "tciot:heat_pump"

    def test_material_icon_mdi_mode(self, hass, mock_config_entry) -> None:
        """A Google icon becomes the matching MDI icon in MDI mode."""
        entity, _ = _make_base_entity(
            hass, mock_config_entry, "md:heat_pump", ICON_MODE_MDI,
        )
        assert entity.icon == "mdi:heat-pump"

    def test_app_icon_on_create(self, hass, mock_config_entry) -> None:
        """App icons are unchanged."""
        entity, _ = _make_base_entity(hass, mock_config_entry, "Lightbulb")
        assert entity.icon == "mdi:lightbulb"

    def test_unknown_icon_keeps_default(self, hass, mock_config_entry) -> None:
        """An unknown Google icon leaves the icon unset (platform default)."""
        entity, _ = _make_base_entity(hass, mock_config_entry, "md:not_a_symbol")
        assert entity.icon is None

    def test_icon_changes_at_runtime(self, hass, mock_config_entry) -> None:
        """A new iot.Icon sent by the PLC updates the icon."""
        entity, widget = _make_base_entity(hass, mock_config_entry, "Lightbulb")
        entity._on_widget_update(_with_icon(widget, "md:roller_shades"))
        assert entity.icon == "tciot:roller_shades"
        entity._on_widget_update(_with_icon(widget, "Plug"))
        assert entity.icon == "mdi:power-plug"

    def test_icon_removed_at_runtime(self, hass, mock_config_entry) -> None:
        """Removing iot.Icon (or an unknown one) drops the override again."""
        entity, widget = _make_base_entity(hass, mock_config_entry, "md:heat_pump")
        entity._on_widget_update(_with_icon(widget, None))
        assert entity.icon is None
        entity._on_widget_update(_with_icon(widget, "md:heat_pump"))
        entity._on_widget_update(_with_icon(widget, "md:not_a_symbol"))
        assert entity.icon is None

    def test_class_default_icon_restored(self, hass, mock_config_entry) -> None:
        """A subclass default icon comes back once the PLC icon is gone."""

        class _DefaultIconEntity(TcIotEntity):
            _attr_icon = "mdi:led-on"

        entity, widget = _make_base_entity(hass, mock_config_entry, None)
        entity = _DefaultIconEntity(entity.coordinator, MOCK_DEVICE_NAME, widget)
        attach_entity_to_hass(hass, entity, "sensor")
        assert entity.icon == "mdi:led-on"
        entity._on_widget_update(_with_icon(widget, "md:light"))
        assert entity.icon == "tciot:light"
        entity._on_widget_update(_with_icon(widget, None))
        assert entity.icon == "mdi:led-on"


class TestHubStatusIcon:
    """The hub status sensor uses the device icon of the Desc message."""

    @pytest.mark.parametrize(
        ("icon", "mode", "expected"),
        [
            ("md:heat_pump", ICON_MODE_MATERIAL, "tciot:heat_pump"),
            ("md:heat_pump", ICON_MODE_MDI, "mdi:heat-pump"),
            ("TwinCAT", ICON_MODE_MATERIAL, "mdi:cat"),
            ("md:not_a_symbol", ICON_MODE_MATERIAL, "mdi:lan-connect"),
            (None, ICON_MODE_MATERIAL, "mdi:lan-connect"),
        ],
    )
    def test_device_icon(self, hass, mock_config_entry, icon, mode, expected) -> None:
        """Google, app, unknown and missing device icons."""
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        dev.icon_name = icon
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        coordinator.icon_mode = mode
        assert TcIotHubStatus(coordinator, dev).icon == expected


class TestDeviceClassFromMaterialIcon:
    """Google icons drive sensor / binary sensor device classes like app icons."""

    @pytest.mark.parametrize(
        ("icon", "unit", "expected"),
        [
            ("md:thermometer", "°C", SensorDeviceClass.TEMPERATURE),
            ("MD:Device_Thermostat", "K", SensorDeviceClass.TEMPERATURE),
            ("md:humidity_percentage", "%", SensorDeviceClass.HUMIDITY),
            ("md:thermostat_carbon", "ppm", SensorDeviceClass.CO2),
            ("md:water_ph", "", SensorDeviceClass.PH),
            ("md:heat_pump", "", None),
            # A unit that does not fit the icon's device class wins.
            ("md:thermometer", "", None),
            ("md:thermometer", "bar", SensorDeviceClass.PRESSURE),
            ("md:water_ph", "pH", None),
            ("md:humidity_percentage", "°C", SensorDeviceClass.TEMPERATURE),
        ],
    )
    def test_sensor(
        self, hass, mock_config_entry, icon, unit, expected,
    ) -> None:
        """Numeric datatype sensors; the device class must fit the unit."""
        dev = build_device_with_widgets(
            MOCK_DEVICE_NAME, ["datatypes/domain/datatype-lreal.json"],
        )
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw[META_ICON] = icon
        widget.metadata.unit = unit
        sensor = TcIotDatatypeSensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class == expected
        assert sensor.native_unit_of_measurement == (unit or None)

    @pytest.mark.parametrize(
        ("icon", "expected"),
        [
            ("md:sensor_window", BinarySensorDeviceClass.WINDOW),
            ("md:door_front", BinarySensorDeviceClass.DOOR),
            ("md:motion_sensor_active", BinarySensorDeviceClass.MOTION),
            ("md:detector_smoke", BinarySensorDeviceClass.SMOKE),
            ("md:water_damage", BinarySensorDeviceClass.MOISTURE),
            ("md:heat_pump", None),
            ("", None),
        ],
    )
    def test_binary_sensor(self, hass, mock_config_entry, icon, expected) -> None:
        """BOOL datatype binary sensors."""
        dev = build_device_with_widgets(
            MOCK_DEVICE_NAME, ["datatypes/domain/datatype-bool.json"],
        )
        coordinator = create_mock_coordinator(
            hass, mock_config_entry, {MOCK_DEVICE_NAME: dev},
        )
        widget = next(iter(dev.widgets.values()))
        widget.metadata.raw[META_ICON] = icon
        sensor = TcIotDatatypeBinarySensor(coordinator, MOCK_DEVICE_NAME, widget)
        assert sensor.device_class == expected


# ── Coordinator: icon mode and areas ──────────────────────────────────


def _real_coordinator(
    hass: HomeAssistant, options: dict[str, object] | None = None,
) -> TcIotCoordinator:
    entry = MockConfigEntry(
        domain="twincat_iot_communicator",
        data=MOCK_ENTRY_DATA,
        options=options or {},
        unique_id="test",
        version=2,
        minor_version=2,
    )
    return TcIotCoordinator(hass, entry)


class TestCoordinatorIconMode:
    """The effective icon mode depends on the setting and the icon set."""

    def test_default_is_material_with_icon_set(self, hass: HomeAssistant) -> None:
        """Without a setting, material mode is used when the icon set is loaded."""
        hass.data[iconset.DATA_ICONSET] = True
        assert _real_coordinator(hass).icon_mode == ICON_MODE_MATERIAL

    def test_material_without_icon_set_uses_mdi(self, hass: HomeAssistant) -> None:
        """Without the frontend icon set no Google icon may stay empty."""
        hass.data[iconset.DATA_ICONSET] = False
        coord = _real_coordinator(hass, {CONF_ICON_MODE: ICON_MODE_MATERIAL})
        assert coord.icon_mode == ICON_MODE_MDI

    def test_mdi_setting(self, hass: HomeAssistant) -> None:
        """The MDI setting is kept even when the icon set is loaded."""
        hass.data[iconset.DATA_ICONSET] = True
        coord = _real_coordinator(hass, {CONF_ICON_MODE: ICON_MODE_MDI})
        assert coord.icon_mode == ICON_MODE_MDI

    def test_invalid_setting_falls_back(self, hass: HomeAssistant) -> None:
        """An unknown stored value behaves like the default."""
        hass.data[iconset.DATA_ICONSET] = True
        coord = _real_coordinator(hass, {CONF_ICON_MODE: "bogus"})
        assert coord.icon_mode == ICON_MODE_MATERIAL


class TestAreaIcon:
    """Areas created from PLC views get the view icon."""

    @pytest.mark.parametrize("mode", [ICON_MODE_MATERIAL, ICON_MODE_MDI])
    async def test_area_icons(self, hass: HomeAssistant, mode: str) -> None:
        """Google and app view icons become area icons; unknown ones none."""
        hass.data[iconset.DATA_ICONSET] = True
        coord = _real_coordinator(hass, options={CONF_ICON_MODE: mode})
        coord._create_areas = True
        dev = DeviceContext(device_name=MOCK_DEVICE_NAME)
        views = {
            "stHeat": ViewData("stHeat", "Heizraum", "md:heat_pump"),
            "stLiving": ViewData("stLiving", "Wohnen", "Sofa"),
            "stOther": ViewData("stOther", "Sonstiges", "md:not_a_symbol"),
        }
        dev.views.update(views)
        for path in views:
            dev.widget_parent_view[f"{path}.widget"] = path

        coord._create_areas_from_views(dev)

        area_reg = ar.async_get(hass)
        # Areas outlive the integration, so they always get MDI icons.
        assert area_reg.async_get_area_by_name("Heizraum").icon == "mdi:heat-pump"
        assert area_reg.async_get_area_by_name("Wohnen").icon == "mdi:sofa"
        assert area_reg.async_get_area_by_name("Sonstiges").icon is None


# ── Icon set registration ─────────────────────────────────────────────


class TestIconsetRegistration:
    """async_register_iconset() serves the files and loads the module."""

    async def test_without_frontend(self, hass: HomeAssistant) -> None:
        """No frontend component: nothing is registered, MDI is used."""
        assert "frontend" not in hass.config.components
        assert await iconset.async_register_iconset(hass) is False
        assert iconset.iconset_available(hass) is False

    async def test_with_frontend(self, hass: HomeAssistant) -> None:
        """With the frontend: static path and versioned module URL, once."""
        hass.config.components.add("frontend")
        hass.http = AsyncMock()
        with patch(
            "homeassistant.components.frontend.add_extra_js_url",
        ) as add_js:
            assert await iconset.async_register_iconset(hass) is True
            assert await iconset.async_register_iconset(hass) is True

        hass.http.async_register_static_paths.assert_awaited_once()
        (configs,) = hass.http.async_register_static_paths.await_args.args
        assert configs[0].url_path == FRONTEND_URL_BASE
        assert Path(configs[0].path) == iconset.FRONTEND_DIR
        add_js.assert_called_once()
        url = add_js.call_args.args[1]
        assert url.startswith(f"{FRONTEND_URL_BASE}/{FRONTEND_ICONSET_JS}?v=")
        assert iconset.iconset_available(hass) is True

    async def test_static_path_already_registered(self, hass: HomeAssistant) -> None:
        """A path registered before (e.g. reload) does not break the setup."""
        hass.config.components.add("frontend")
        hass.http = AsyncMock()
        hass.http.async_register_static_paths.side_effect = RuntimeError("exists")
        with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
            assert await iconset.async_register_iconset(hass) is True
        add_js.assert_called_once()
