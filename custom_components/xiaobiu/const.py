from __future__ import annotations

from datetime import timedelta

DOMAIN = "xiaobiu"
PLATFORMS = ("climate",)

CONF_PHONE_NUMBER = "phone_number"
CONF_INTERNATIONAL_CODE = "international_code"
CONF_FAMILY_ID = "family_id"
CONF_FAMILY_NAME = "family_name"

CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_INTERNATIONAL_CODE = "0086"
# The app keeps the panel fresh through vendor push (Getui/OEM channels),
# which an integration cannot join, so polling is what we have.  A 10 s
# cycle on the 1.2 KB family snapshot costs ~150 ms and keeps a physical
# remote press visible within one cycle.
DEFAULT_SCAN_INTERVAL = 10
SCAN_INTERVAL_OPTIONS = (5, 10, 15, 30, 60)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
KEEP_ALIVE_INTERVAL = timedelta(minutes=30)

PRESET_NONE = "none"
PRESET_ECO = "eco"
PRESET_FRESH_AIR = "fresh_air"
PRESET_AUX_HEAT = "aux_heat"
