from __future__ import annotations

from datetime import timedelta

DOMAIN = "suning_biu"
PLATFORMS = ("climate",)

CONF_PHONE_NUMBER = "phone_number"
CONF_INTERNATIONAL_CODE = "international_code"
CONF_HAR_PATH = "har_path"
CONF_FAMILY_ID = "family_id"
CONF_FAMILY_NAME = "family_name"

DEFAULT_INTERNATIONAL_CODE = "0086"
SCAN_INTERVAL = timedelta(minutes=5)
