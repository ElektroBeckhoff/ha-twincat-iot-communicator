"""Repair flows for the TwinCAT IoT Communicator integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class StaleDevicesRepairFlow(RepairsFlow):
    """Repair flow that removes all stale Widget Sub-Devices."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Always redirect to the confirm step.

        HA passes issue data as *user_input* on the first call, so we
        cannot rely on ``user_input is None`` to decide whether to show
        the form.  A dedicated confirm step avoids the auto-submit.
        """
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None,
    ) -> data_entry_flow.FlowResult:
        """Show confirmation and perform cleanup on submit."""
        if user_input is not None:
            removed = await self._remove_stale_devices()
            if removed < 0:
                return self.async_abort(reason="cannot_connect")
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
        )

    async def _remove_stale_devices(self) -> int:
        """Remove all stale Widget Sub-Devices.

        Hub Devices are never removed by the repair flow — they may come
        back online after PLC restart / maintenance and can only be removed
        manually via the device page.

        Returns the number of devices actually removed, or -1 when
        preconditions were not met (entry missing, coordinator gone, …).
        """
        issue_data: dict[str, Any] = self.data or {}
        entry_id: str | None = issue_data.get("entry_id")
        _LOGGER.debug(
            "Repair flow started – issue data: %s, entry_id: %s",
            issue_data, entry_id,
        )

        entry: ConfigEntry | None = None
        if entry_id is not None:
            entry = self.hass.config_entries.async_get_entry(entry_id)

        if entry is None:
            loaded = [
                e for e in self.hass.config_entries.async_entries(DOMAIN)
                if e.state is ConfigEntryState.LOADED
            ]
            if len(loaded) == 1:
                entry = loaded[0]
                entry_id = entry.entry_id
                _LOGGER.info(
                    "Repair flow: entry_id missing in issue data, "
                    "using single loaded entry %s",
                    entry_id,
                )
            else:
                _LOGGER.warning(
                    "Repair flow aborted: entry_id=%s not resolved, "
                    "%d loaded entries",
                    issue_data.get("entry_id"), len(loaded),
                )
                return -1

        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is None:
            _LOGGER.warning("Repair flow aborted: no coordinator on entry %s", entry_id)
            return -1

        for dev in coordinator.devices.values():
            _LOGGER.debug(
                "Repair flow state: device=%s online=%s known=%d stale=%d "
                "widgets=%d stale_paths=%s",
                dev.device_name, dev.online,
                len(dev.known_widget_paths), len(dev.stale_widget_paths),
                len(dev.widgets), dev.stale_widget_paths,
            )

        stale = list(coordinator.get_stale_widget_info())
        _LOGGER.debug(
            "Repair flow: %d stale widget(s) to remove: %s", len(stale), stale,
        )

        dev_reg = dr.async_get(self.hass)
        removed = 0

        for device_name, widget_path in stale:
            await coordinator.async_remove_widget(device_name, widget_path)
            widget_ident = (DOMAIN, f"{entry_id}_{device_name}_{widget_path}")
            widget_dev = dev_reg.async_get_device(identifiers={widget_ident})
            if widget_dev is not None:
                dev_reg.async_remove_device(widget_dev.id)
                removed += 1
                _LOGGER.info(
                    "Removed widget device %s/%s (registry id %s)",
                    device_name, widget_path, widget_dev.id,
                )
            else:
                _LOGGER.warning(
                    "Widget device not found in registry for identifier %s",
                    widget_ident,
                )

        ir.async_delete_issue(self.hass, DOMAIN, "stale_devices")
        _LOGGER.info(
            "Stale widget cleanup completed: %d/%d device(s) removed",
            removed, len(stale),
        )
        return removed


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the appropriate repair flow for the given issue."""
    if issue_id == "stale_devices":
        return StaleDevicesRepairFlow()
    raise ValueError(f"Unknown issue_id: {issue_id}")
