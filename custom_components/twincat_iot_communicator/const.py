"""Constants for the TwinCAT IoT Communicator integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "twincat_iot_communicator"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.EVENT,
    Platform.FAN,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

# ── Config flow keys ─────────────────────────────────────────────

CONF_USE_TLS = "use_tls"
CONF_MAIN_TOPIC = "main_topic"
CONF_SELECTED_DEVICES = "selected_devices"
CONF_AUTH_MODE = "auth_mode"
CONF_AUTH_URL = "auth_url"
CONF_JWT_TOKEN = "jwt_token"

AUTH_MODE_CREDENTIALS = "credentials"
AUTH_MODE_ONLINE = "online"

AUTH_CALLBACK_PATH = "/auth/tc_iot/callback"
AUTH_CALLBACK_NAME = "auth:tc_iot:callback"

DEFAULT_CLIENT_ID = "tc_iot_communicator"

# ── Default values ───────────────────────────────────────────────

DEFAULT_PORT = 1883
DEFAULT_PORT_TLS = 8883  # reserved – auto-set in config_flow when TLS is toggled
DEFAULT_MAIN_TOPIC = "IotApp.Sample"

# ── MQTT topic templates (per-device, for publishing) ────────────

TOPIC_TX = "{main_topic}/{device_name}/TcIotCommunicator/Json/Tx/Data"  # reserved – subscribe via TOPIC_SUB_TX
TOPIC_RX = "{main_topic}/{device_name}/TcIotCommunicator/Json/Rx/Data"
TOPIC_DESC = "{main_topic}/{device_name}/TcIotCommunicator/Desc"  # reserved – subscribe via TOPIC_SUB_DESC
TOPIC_COMM = "{main_topic}/{device_name}/TcIotCommunicator/Communicator/{client_id}"
TOPIC_COMM_HEARTBEAT = "{main_topic}/{device_name}/TcIotCommunicator/Communicator/{client_id}/heartbeat"
TOPIC_COMM_ACTIVE = "{main_topic}/{device_name}/TcIotCommunicator/Communicator/{client_id}/active"

# ── MQTT wildcard topic templates (for subscribing, auto-discovery) ──

TOPIC_SUB_TX = "{main_topic}/+/TcIotCommunicator/Json/Tx/Data"
TOPIC_SUB_DESC = "{main_topic}/+/TcIotCommunicator/Desc"
TOPIC_SUB_MESSAGES = "{main_topic}/+/TcIotCommunicator/Messages/+"

# ── MQTT per-device message topic (for publishing ack / delete) ──

TOPIC_MESSAGE = "{main_topic}/{device_name}/TcIotCommunicator/Messages/{message_id}"

# ── Messages JSON keys ───────────────────────────────────────────

MSG_TIMESTAMP = "Timestamp"
MSG_MESSAGE = "Message"
MSG_TYPE = "Type"
MSG_TYPE_DEFAULT = "Default"
MSG_TYPE_INFO = "Info"
MSG_TYPE_WARNING = "Warning"
MSG_TYPE_ERROR = "Error"
MSG_TYPE_CRITICAL = "Critical"
MSG_ACKNOWLEDGEMENT = "Acknowledgement"
MSG_SENT = "sent"

HEARTBEAT_INTERVAL = 1

# ── Tx/Data JSON top-level keys ─────────────────────────────────

JSON_TIMESTAMP = "Timestamp"  # reserved – present in Tx/Data payloads
JSON_GROUP_NAME = "GroupName"  # reserved – present in Tx/Data payloads
JSON_VALUES = "Values"
JSON_METADATA = "MetaData"
JSON_FORCE_UPDATE = "ForceUpdate"

# ── Desc JSON keys ──────────────────────────────────────────────

DESC_TIMESTAMP = "Timestamp"
DESC_ONLINE = "Online"
DESC_ICON = "Icon"
DESC_PERMITTED_USERS = "PermittedUsers"

TCIOT_ICON_MAP: dict[str, str] = {
    "Baby": "mdi:baby-carriage",
    "Bath": "mdi:bathtub",
    "Beach": "mdi:beach",
    "Bed": "mdi:bed",
    "Bell": "mdi:bell",
    "Blinds": "mdi:blinds",
    "Car": "mdi:car",
    "Charging_Station": "mdi:ev-station",
    "Clipboard": "mdi:clipboard-text",
    "Clock": "mdi:clock-outline",
    "Clothes_Hook": "mdi:hanger",
    "Cloud_Moon": "mdi:weather-night",
    "Cloud_Sun": "mdi:weather-partly-cloudy",
    "Co2": "mdi:molecule-co2",
    "Co2_Filled": "mdi:molecule-co2",
    "Color_Palette": "mdi:palette",
    "Desk_Lamp": "mdi:desk-lamp",
    "Dining": "mdi:silverware-fork-knife",
    "Door_Closed": "mdi:door-closed",
    "Door_Open": "mdi:door-open",
    "Droplet": "mdi:water",
    "Fan": "mdi:fan",
    "Fan_Green": "mdi:fan",
    "Fitness": "mdi:dumbbell",
    "Floor": "mdi:floor-plan",
    "Floor_Lamp": "mdi:floor-lamp",
    "Garage": "mdi:garage",
    "Garden": "mdi:flower",
    "Gate": "mdi:gate",
    "Gear": "mdi:cog",
    "Guest": "mdi:account",
    "Heat": "mdi:radiator",
    "Heat_Red": "mdi:radiator",
    "Home_Theater": "mdi:theater",
    "House": "mdi:home",
    "Key": "mdi:key",
    "Kitchen": "mdi:countertop",
    "Laundry": "mdi:washing-machine",
    "Light_Group": "mdi:lightbulb-group",
    "Lightbulb": "mdi:lightbulb",
    "Lightning": "mdi:flash",
    "Lock": "mdi:lock",
    "Motion": "mdi:motion-sensor",
    "Music_Note": "mdi:music",
    "PC": "mdi:desktop-classic",
    "Plug": "mdi:power-plug",
    "Room": "mdi:floor-plan",
    "Shirt": "mdi:tshirt-crew",
    "Snowflake": "mdi:snowflake",
    "Snowflake_Blue": "mdi:snowflake",
    "Sofa": "mdi:sofa",
    "Storage": "mdi:archive",
    "Switch": "mdi:toggle-switch",
    "Teddy": "mdi:teddy-bear",
    "Temperature": "mdi:thermometer",
    "Terrace": "mdi:balcony",
    "Toilet": "mdi:toilet",
    "Toilet_Paper": "mdi:paper-roll",
    "Tools": "mdi:tools",
    "TwinCAT": "mdi:cat",
    "Unlock": "mdi:lock-open",
    "Window_Closed": "mdi:window-closed",
    "Window_Open": "mdi:window-open",
}

# ── iot.WidgetType values ────────────────────────────────────────

WIDGET_TYPE_LIGHTING = "Lighting"
WIDGET_TYPE_BLINDS = "Blinds"
WIDGET_TYPE_SIMPLE_BLINDS = "SimpleBlinds"
WIDGET_TYPE_PLUG = "Plug"
WIDGET_TYPE_GENERAL = "General"
WIDGET_TYPE_RGBW = "RGBW"
WIDGET_TYPE_RGBW_EL2564 = "RGBWEL2564"
WIDGET_TYPE_AIRCON = "AC"
WIDGET_TYPE_VENTILATION = "Ventilation"
WIDGET_TYPE_CHARGING_STATION = "ChargingStation"
WIDGET_TYPE_ENERGY_MONITORING = "EnergyMonitoring"
WIDGET_TYPE_BAR_CHART = "BarChart"
WIDGET_TYPE_TIME_SWITCH = "TimeSwitch"

# ── Synthetic datatype widget types (no iot.WidgetType in PLC) ───
# ReadOnly is never encoded in the type — it lives in widget_meta.read_only
# and can change at runtime via PLC metadata updates.

DATATYPE_BOOL = "_dt_bool"
DATATYPE_NUMBER = "_dt_number"
DATATYPE_STRING = "_dt_string"

DATATYPE_FIELD_MAP: dict[str, str] = {
    "bBOOL": "bool",
    "nINT": "number",
    "nSINT": "number",
    "nDINT": "number",
    "nLINT": "number",
    "nUSINT_BYTE": "number",
    "nUINT_WORD": "number",
    "nUDINT_DWORD": "number",
    "nULINT": "number",
    "fREAL": "number",
    "fLREAL": "number",
    "sSTRING": "string",
}

# ── Widget type → HA platform map ────────────────────────────────

WIDGET_PLATFORM_MAP: dict[str, Platform] = {
    WIDGET_TYPE_LIGHTING: Platform.LIGHT,
    WIDGET_TYPE_RGBW: Platform.LIGHT,
    WIDGET_TYPE_RGBW_EL2564: Platform.LIGHT,
    WIDGET_TYPE_BLINDS: Platform.COVER,
    WIDGET_TYPE_SIMPLE_BLINDS: Platform.COVER,
    WIDGET_TYPE_PLUG: Platform.SWITCH,
    WIDGET_TYPE_AIRCON: Platform.CLIMATE,
    WIDGET_TYPE_VENTILATION: Platform.FAN,
    WIDGET_TYPE_ENERGY_MONITORING: Platform.SENSOR,
    DATATYPE_BOOL: Platform.SWITCH,
    DATATYPE_NUMBER: Platform.NUMBER,
    DATATYPE_STRING: Platform.TEXT,
}

# Widget types that route to multiple platforms simultaneously.
# The coordinator delivers the same WidgetData to each listed platform;
# each platform file decides which sub-entities to create.
WIDGET_MULTI_PLATFORM_MAP: dict[str, list[Platform]] = {
    WIDGET_TYPE_GENERAL: [
        Platform.SWITCH,
        Platform.LIGHT,
        Platform.NUMBER,
        Platform.SELECT,
    ],
}

# ═══════════════════════════════════════════════════════════════════
#  MetaData iot.* key constants
# ═══════════════════════════════════════════════════════════════════

# ── Common (all widget types + views) ────────────────────────────

META_DISPLAY_NAME = "iot.DisplayName"
META_WIDGET_TYPE = "iot.WidgetType"
META_READ_ONLY = "iot.ReadOnly"
META_NESTED_STRUCT_ICON = "iot.NestedStructIcon"
META_ICON = "iot.Icon"
META_DECIMAL_PRECISION = "iot.DecimalPrecision"
META_PERMITTED_USERS = "iot.PermittedUsers"
META_VALUE_TEXT_COLOR = "iot.ValueTextColor"
META_VALUE_TEXT_COLOR_DARK = "iot.ValueTextColorDark"

# ── Field-level (per-value sub-entries) ──────────────────────────

META_UNIT = "iot.Unit"
META_MIN_VALUE = "iot.MinValue"
META_MAX_VALUE = "iot.MaxValue"

# ── Lighting / RGBW ─────────────────────────────────────────────

META_LIGHT_VALUE_VISIBLE = "iot.LightValueVisible"
META_LIGHT_SLIDER_VISIBLE = "iot.LightSliderVisible"
META_LIGHT_MODE_VISIBLE = "iot.LightModeVisible"
META_LIGHT_MODE_CHANGEABLE = "iot.LightModeChangeable"
META_LIGHT_COLOR_PALETTE_VISIBLE = "iot.LightColorPaletteVisible"
META_LIGHT_COLOR_PALETTE_MODE = "iot.LightColorPaletteMode"
META_LIGHT_COLOR_TEMP_SLIDER_VISIBLE = "iot.LightColorTemperatureSliderVisible"
META_LIGHT_WHITE_SLIDER_VISIBLE = "iot.LightWhiteSliderVisible"

# ── Blinds ───────────────────────────────────────────────────────

META_BLINDS_POSITION_VALUE_VISIBLE = "iot.BlindsPositionValueVisible"
META_BLINDS_POSITION_SLIDER_VISIBLE = "iot.BlindsPositionSliderVisible"
META_BLINDS_ANGLE_VALUE_VISIBLE = "iot.BlindsAngleValueVisible"
META_BLINDS_ANGLE_SLIDER_VISIBLE = "iot.BlindsAngleSliderVisible"
META_BLINDS_MODE_VISIBLE = "iot.BlindsModeVisible"
META_BLINDS_MODE_CHANGEABLE = "iot.BlindsModeChangeable"

# ── Plug ─────────────────────────────────────────────────────────

META_PLUG_MODE_VISIBLE = "iot.PlugModeVisible"
META_PLUG_MODE_CHANGEABLE = "iot.PlugModeChangeable"

# ── General ──────────────────────────────────────────────────────

META_GENERAL_VALUE1_SWITCH_VISIBLE = "iot.GeneralValue1SwitchVisible"
META_GENERAL_VALUE2_VISIBLE = "iot.GeneralValue2Visible"
META_GENERAL_VALUE2_SLIDER_VISIBLE = "iot.GeneralValue2SliderVisible"
META_GENERAL_VALUE2_SLIDER_VALUES_VISIBLE = "iot.GeneralValue2SliderValuesVisible"
META_GENERAL_VALUE2_SLIDER_BUTTONS_VISIBLE = "iot.GeneralValue2SliderButtonsVisible"
META_GENERAL_VALUE2_SLIDER_BUTTONS_INVERTED = "iot.GeneralValue2SliderButtonsInverted"
META_GENERAL_VALUE3_VISIBLE = "iot.GeneralValue3Visible"
META_GENERAL_VALUE3_SLIDER_VISIBLE = "iot.GeneralValue3SliderVisible"
META_GENERAL_VALUE3_SLIDER_VALUES_VISIBLE = "iot.GeneralValue3SliderValuesVisible"
META_GENERAL_VALUE3_SLIDER_BUTTONS_VISIBLE = "iot.GeneralValue3SliderButtonsVisible"
META_GENERAL_VALUE3_SLIDER_BUTTONS_INVERTED = "iot.GeneralValue3SliderButtonsInverted"
META_GENERAL_MODE1_VISIBLE = "iot.GeneralMode1Visible"
META_GENERAL_MODE1_CHANGEABLE = "iot.GeneralMode1Changeable"
META_GENERAL_MODE2_VISIBLE = "iot.GeneralMode2Visible"
META_GENERAL_MODE2_CHANGEABLE = "iot.GeneralMode2Changeable"
META_GENERAL_MODE3_VISIBLE = "iot.GeneralMode3Visible"
META_GENERAL_MODE3_CHANGEABLE = "iot.GeneralMode3Changeable"
META_GENERAL_WIDGET_COLOR = "iot.GeneralWidgetColor"
META_GENERAL_WIDGET_ICON = "iot.GeneralWidgetIcon"

# ── AC (AirCon / Climate) ───────────────────────────────────────

META_AC_SLIDER_VISIBLE = "iot.ACSliderVisible"
META_AC_VALUE_REQUEST_VISIBLE = "iot.ACValueRequestVisible"
META_AC_MODE_VISIBLE = "iot.ACModeVisible"
META_AC_MODE_CHANGEABLE = "iot.ACModeChangeable"
META_AC_MODE_STRENGTH_VISIBLE = "iot.ACModeStrengthVisible"
META_AC_MODE_STRENGTH_CHANGEABLE = "iot.ACModeStrengthChangeable"
META_AC_MODE_LAMELLA_VISIBLE = "iot.ACModeLamellaVisible"
META_AC_MODE_LAMELLA_CHANGEABLE = "iot.ACModeLamellaChangeable"

# ── TimeSwitch ───────────────────────────────────────────────────

META_TIMESWITCH_MODE_VISIBLE = "iot.TimeSwitchModeVisible"
META_TIMESWITCH_MODE_CHANGEABLE = "iot.TimeSwitchModeChangeable"
META_TIMESWITCH_START_TIME_VISIBLE = "iot.TimeSwitchStartTimeVisible"
META_TIMESWITCH_END_TIME_VISIBLE = "iot.TimeSwitchEndTimeVisible"
META_TIMESWITCH_START_DATE_VISIBLE = "iot.TimeSwitchStartDateVisible"
META_TIMESWITCH_END_DATE_VISIBLE = "iot.TimeSwitchEndDateVisible"
META_TIMESWITCH_DATE_YEARLY_VISIBLE = "iot.TimeSwitchDateYearlyVisible"
META_TIMESWITCH_DAYS_VISIBLE = "iot.TimeSwitchDaysVisible"

# ── Ventilation ──────────────────────────────────────────────────

META_VENTILATION_ON_SWITCH_VISIBLE = "iot.VentilationOnSwitchVisible"
META_VENTILATION_SLIDER_VISIBLE = "iot.VentilationSliderVisible"
META_VENTILATION_VALUE_REQUEST_VISIBLE = "iot.VentilationValueRequestVisible"
META_VENTILATION_MODE_VISIBLE = "iot.VentilationModeVisible"
META_VENTILATION_MODE_CHANGEABLE = "iot.VentilationModeChangeable"

# ── RGBW EL2564 (4-channel LED) ─────────────────────────────────

META_LED_RED_SLIDER_VISIBLE = "iot.LedRedSliderVisible"
META_LED_GREEN_SLIDER_VISIBLE = "iot.LedGreenSliderVisible"
META_LED_BLUE_SLIDER_VISIBLE = "iot.LedBlueSliderVisible"
META_LED_WHITE_SLIDER_VISIBLE = "iot.LedWhiteSliderVisible"
META_LED_MODE_VISIBLE = "iot.LedModeVisible"
META_LED_MODE_CHANGEABLE = "iot.LedModeChangeable"

# ── BarChart ─────────────────────────────────────────────────────

META_CHART_X_AXIS_LABEL = "iot.ChartXAxisLabel"
META_CHART_Y_AXIS_LABEL = "iot.ChartYAxisLabel"
META_CHART_LEGEND_VISIBLE = "iot.ChartLegendVisible"
META_CHART_VALUES_VISIBLE = "iot.ChartValuesVisible"
META_CHART_BAR_COLOR1 = "iot.ChartBarColor1"
META_CHART_BAR_COLOR2 = "iot.ChartBarColor2"

# ── ChargingStation ──────────────────────────────────────────────

META_CHARGING_STATION_RESERVE_VISIBLE = "iot.ChargingStationReserveVisible"
META_CHARGING_STATION_PHASE2_VISIBLE = "iot.ChargingStationPhase2Visible"
META_CHARGING_STATION_PHASE3_VISIBLE = "iot.ChargingStationPhase3Visible"

# ── EnergyMonitoring ─────────────────────────────────────────────

META_ENERGY_MONITORING_PHASE2_VISIBLE = "iot.EnergyMonitoringPhase2Visible"
META_ENERGY_MONITORING_PHASE3_VISIBLE = "iot.EnergyMonitoringPhase3Visible"

# ═══════════════════════════════════════════════════════════════════
#  Value key constants (keys inside widget Values dicts)
# ═══════════════════════════════════════════════════════════════════

VAL_DISPLAY_NAME = "sDisplayName"  # reserved – display names come from MetaData

# ── Lighting / RGBW values ───────────────────────────────────────

VAL_LIGHT_ON = "bLight"
VAL_LIGHT_LEVEL = "nLight"
VAL_LIGHT_HUE = "nHueValue"
VAL_LIGHT_SATURATION = "nSaturation"
VAL_LIGHT_RED = "nRed"
VAL_LIGHT_GREEN = "nGreen"
VAL_LIGHT_BLUE = "nBlue"
VAL_LIGHT_WHITE = "nWhite"
VAL_LIGHT_COLOR_TEMP = "nColorTemperature"
VAL_LIGHT_COLOR_MODE = "nColorMode"

# nColorMode bitmask — each bit tells the PLC which data fields are included
PLC_CM_ONOFF = 1        # bit 0: bLight toggled
PLC_CM_BRIGHTNESS = 2   # bit 1: nLight
PLC_CM_COLOR_TEMP = 4   # bit 2: nColorTemperature
PLC_CM_HS = 8           # bit 3: nHueValue + nSaturation
PLC_CM_RGB = 16         # bit 4: nRed + nGreen + nBlue
PLC_CM_WHITE = 32       # bit 5: nWhite

# ── Blinds values ────────────────────────────────────────────────

VAL_BLINDS_ACTIVE = "bActive"
VAL_BLINDS_POSITION_UP = "bPositionUp"
VAL_BLINDS_POSITION_DOWN = "bPositionDown"
VAL_BLINDS_ANGLE_UP = "bAngleUp"
VAL_BLINDS_ANGLE_DOWN = "bAngleDown"
VAL_BLINDS_POSITION_VALUE = "nPositionValue"
VAL_BLINDS_POSITION_REQUEST = "nPositionRequest"
VAL_BLINDS_ANGLE_VALUE = "nAngleValue"
VAL_BLINDS_ANGLE_REQUEST = "nAngleRequest"

# ── Plug values ──────────────────────────────────────────────────

VAL_PLUG_ON = "bOn"

# ── General values ───────────────────────────────────────────────

VAL_GENERAL_VALUE1 = "bValue1"
VAL_GENERAL_VALUE2 = "nValue2"
VAL_GENERAL_VALUE2_REQUEST = "nValue2Request"
VAL_GENERAL_VALUE2_UP = "bValue2Up"
VAL_GENERAL_VALUE2_DOWN = "bValue2Down"
VAL_GENERAL_VALUE3 = "nValue3"
VAL_GENERAL_VALUE3_REQUEST = "nValue3Request"
VAL_GENERAL_VALUE3_UP = "bValue3Up"
VAL_GENERAL_VALUE3_DOWN = "bValue3Down"

# ── AC values ────────────────────────────────────────────────────

VAL_AC_MODE = "nAcMode"
VAL_AC_TEMPERATURE = "nTemperature"
VAL_AC_TEMPERATURE_REQUEST = "nTemperatureRequest"

# ── TimeSwitch values ────────────────────────────────────────────

VAL_TIMESWITCH_ON = "bOn"
VAL_TIMESWITCH_START_TIME = "tStartTime"
VAL_TIMESWITCH_END_TIME = "tEndTime"
VAL_TIMESWITCH_START_DATE = "dStartDate"
VAL_TIMESWITCH_END_DATE = "dEndDate"
VAL_TIMESWITCH_YEARLY = "bYearly"
VAL_TIMESWITCH_MONDAY = "bMonday"
VAL_TIMESWITCH_TUESDAY = "bTuesday"
VAL_TIMESWITCH_WEDNESDAY = "bWednesday"
VAL_TIMESWITCH_THURSDAY = "bThursday"
VAL_TIMESWITCH_FRIDAY = "bFriday"
VAL_TIMESWITCH_SATURDAY = "bSaturday"
VAL_TIMESWITCH_SUNDAY = "bSunday"

# ── Datatype value (synthetic widgets: _dt_*) ────────────────────

VAL_DATATYPE_VALUE = "value"

# ── Shared values (used by multiple widget types) ────────────────

VAL_MODE = "sMode"
VAL_MODES = "aModes"
VAL_MODE_STRENGTH = "sMode_Strength"
VAL_MODES_STRENGTH = "aModes_Strength"
VAL_MODE_LAMELLA = "sMode_Lamella"
VAL_MODES_LAMELLA = "aModes_Lamella"
VAL_GENERAL_MODE1 = "sMode1"
VAL_GENERAL_MODES1 = "aModes1"
VAL_GENERAL_MODE2 = "sMode2"
VAL_GENERAL_MODES2 = "aModes2"
VAL_GENERAL_MODE3 = "sMode3"
VAL_GENERAL_MODES3 = "aModes3"

# ── Ventilation values ───────────────────────────────────────────

VAL_VENTILATION_ON = "bOn"
VAL_VENTILATION_VALUE = "nValue"
VAL_VENTILATION_VALUE_REQUEST = "nValueRequest"

# ── RGBW EL2564 values ──────────────────────────────────────────

VAL_LED_ON = "bOn"
VAL_LED_RED = "nRed"
VAL_LED_GREEN = "nGreen"
VAL_LED_BLUE = "nBlue"
VAL_LED_WHITE = "nWhite"

# ── BarChart values ──────────────────────────────────────────────

VAL_CHART_DATA_SERIES = "aDataSeries"
VAL_CHART_COMPARISM_DATA_SERIES = "aComparismDataSeries"
VAL_CHART_DATA_SERIES_IDENTIFIER = "aDataSeriesIdentifier"
VAL_CHART_LEGEND_LABELS = "aLegendLabels"

# ── ChargingStation values ───────────────────────────────────────

VAL_CHARGING_START = "bStartCharging"
VAL_CHARGING_STOP = "bStopCharging"
VAL_CHARGING_RESERVE = "bReserveCharging"
VAL_CHARGING_STATUS = "sStatus"
VAL_CHARGING_BATTERY_LEVEL = "nBatteryLevel"
VAL_CHARGING_CURRENT_POWER = "nCurrentPower"
VAL_CHARGING_THREE_PHASE_MAX_POWER = "aThreePhaseMaxPower"
VAL_CHARGING_THREE_PHASE_CURRENT_POWER = "aThreePhaseCurrentPower"
VAL_CHARGING_THREE_PHASE_AMPERAGE = "aThreePhaseAmperage"
VAL_CHARGING_THREE_PHASE_VOLTAGE = "aThreePhaseVoltage"
VAL_CHARGING_TIME = "nChargingTime"
VAL_CHARGING_ENERGY = "nChargingEnergy"

# ── EnergyMonitoring values ──────────────────────────────────────

VAL_ENERGY_STATUS = "sStatus"
VAL_ENERGY_THREE_PHASE_MAX_POWER = "aThreePhaseMaxPower"
VAL_ENERGY_THREE_PHASE_CURRENT_POWER = "aThreePhaseCurrentPower"
VAL_ENERGY_THREE_PHASE_POWER_UNITS = "aThreePhasePowerUnits"
VAL_ENERGY_THREE_PHASE_AMPERAGE = "aThreePhaseAmperage"
VAL_ENERGY_THREE_PHASE_AMPERAGE_UNITS = "aThreePhaseAmperageUnits"
VAL_ENERGY_THREE_PHASE_VOLTAGE = "aThreePhaseVoltage"
VAL_ENERGY_THREE_PHASE_VOLTAGE_UNITS = "aThreePhaseVoltageUnits"
VAL_ENERGY_POWER_QUALITY_FACTOR = "nPowerQualityFactor"
VAL_ENERGY_CURRENT_POWER = "nCurrentPower"
VAL_ENERGY_POWER_UNIT = "sPowerUnit"
VAL_ENERGY_VALUE = "nEnergy"
VAL_ENERGY_UNIT = "sEnergyUnit"
