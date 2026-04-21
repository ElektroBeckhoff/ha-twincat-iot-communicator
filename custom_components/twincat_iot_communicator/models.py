"""Data models for TwinCAT IoT Communicator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    META_DISPLAY_NAME,
    META_MAX_VALUE,
    META_MIN_VALUE,
    META_READ_ONLY,
    META_UNIT,
    META_WIDGET_TYPE,
)


@dataclass
class WidgetMetaData:
    """Parsed metadata for a single widget from iot.* keys."""

    display_name: str = ""
    widget_type: str = ""
    read_only: bool = False
    unit: str = ""
    min_value: float | None = None
    max_value: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WidgetData:
    """Represents a discovered widget with its current values and metadata."""

    widget_id: str
    path: str
    metadata: WidgetMetaData
    values: dict[str, Any] = field(default_factory=dict)
    friendly_path: str = ""
    view_prefix: str = ""
    field_metadata: dict[str, dict[str, str]] = field(default_factory=dict)

    def effective_display_name(self) -> str:
        """Return the best available display name.

        Priority: runtime sDisplayName from values, then iot.DisplayName from
        metadata, then the raw widget_id as last resort.
        """
        return (
            str(self.values.get("sDisplayName") or "")
            or self.metadata.display_name
            or self.widget_id
        )

    @property
    def platform_type(self) -> str:
        """Return the iot.WidgetType string."""
        return self.metadata.widget_type

    def field_min(self, field_name: str, default: float = 0) -> float:
        """Return iot.MinValue for a specific value field."""
        fm = self.field_metadata.get(field_name, {})
        try:
            return float(fm[META_MIN_VALUE])
        except (KeyError, ValueError, TypeError):
            return default

    def field_max(self, field_name: str, default: float = 100) -> float:
        """Return iot.MaxValue for a specific value field."""
        fm = self.field_metadata.get(field_name, {})
        try:
            return float(fm[META_MAX_VALUE])
        except (KeyError, ValueError, TypeError):
            return default

    def field_unit(self, field_name: str) -> str:
        """Return iot.Unit for a specific value field."""
        return self.field_metadata.get(field_name, {}).get(META_UNIT, "")


@dataclass
class ViewData:
    """Represents a view node (non-widget) in the PLC hierarchy."""

    path: str
    display_name: str
    icon: str
    parent_path: str | None = None
    permitted_users: str | None = None
    read_only: bool = False


@dataclass
class TcIotMessage:
    """A single PLC push message from the Messages topic."""

    message_id: str
    timestamp: str
    text: str
    message_type: str = "Default"
    acknowledged: bool = False
    acknowledgement_text: str | None = None


@dataclass
class DeviceContext:
    """Per-device state tracked by the coordinator."""

    device_name: str
    widgets: dict[str, WidgetData] = field(default_factory=dict)
    known_widget_paths: set[str] = field(default_factory=set)
    stale_widget_paths: set[str] = field(default_factory=set)
    denied_view_paths: set[str] = field(default_factory=set)
    widget_path_prefixes: set[str] = field(default_factory=set)
    views: dict[str, ViewData] = field(default_factory=dict)
    widget_parent_view: dict[str, str] = field(default_factory=dict)
    messages: dict[str, TcIotMessage] = field(default_factory=dict)
    online: bool = True
    icon_name: str | None = None
    permitted_users: str | None = None
    desc_timestamp: str | None = None
    last_desc_received: float | None = None
    desc_interval: float | None = None
    desc_count: int = 0
    registered: bool = False
    awaiting_full_snapshot: bool = True
    snapshot_accumulated_paths: set[str] = field(default_factory=set)
    snapshot_started_at: float | None = None
    snapshot_stable_count: int = 0
    # None = probe pending, True = PLC responds to active=1, False = not supported
    supports_active_snapshot: bool | None = None
    areas_from_views_done: bool = False


def parse_metadata(raw: dict[str, Any]) -> WidgetMetaData:
    """Parse iot.* metadata dict into WidgetMetaData."""
    read_only_str = raw.get(META_READ_ONLY, "false")
    read_only = read_only_str.lower() == "true"

    min_val = None
    max_val = None
    if META_MIN_VALUE in raw:
        try:
            min_val = float(raw[META_MIN_VALUE])
        except (ValueError, TypeError):
            pass
    if META_MAX_VALUE in raw:
        try:
            max_val = float(raw[META_MAX_VALUE])
        except (ValueError, TypeError):
            pass

    return WidgetMetaData(
        display_name=raw.get(META_DISPLAY_NAME, ""),
        widget_type=raw.get(META_WIDGET_TYPE, ""),
        read_only=read_only,
        unit=raw.get(META_UNIT, ""),
        min_value=min_val,
        max_value=max_val,
        raw=raw,
    )
