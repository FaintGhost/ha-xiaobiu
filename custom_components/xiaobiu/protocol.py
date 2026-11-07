from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PANEL_QUERY_URL = "https://shcss.suning.com/shcss-web/api/panel/queryTemplate.do"


# python-xiaobiu 0.2.2 verified that status and control use different
# encodings. These tables backport that fix while 0.2.2's dependency metadata
# is incompatible with Home Assistant's pinned cryptography release.
SN_MODE_TO_XIAOBIU: dict[str, str] = {
  "1": "auto",
  "2": "cool",
  "3": "heat",
  "4": "fan_only",
  "5": "dry",
}
C_MODE_TO_XIAOBIU: dict[str, str] = {
  "1": "heat",
  "2": "cool",
  "3": "dry",
  "4": "fan_only",
  "5": "fan_only",
  "6": "auto",
}
XIAOBIU_TO_C_MODE: dict[str, str] = {
  "heat": "1",
  "cool": "2",
  "dry": "3",
  "fan_only": "4",
  "auto": "6",
  "quick": "6",
}
FAN_SPEED_FROM_RAW: dict[str, str] = {
  "0": "auto",
  "1": "silent",
  "2": "low",
  "3": "medium",
  "4": "high",
  "5": "turbo",
}
FAN_SPEED_TO_RAW: dict[str, str] = {
  value: key for key, value in FAN_SPEED_FROM_RAW.items()
}


def normalize_hvac_status(status: Any) -> None:
  """Backport python-xiaobiu 0.2.2's live-verified mode decoding."""

  if not getattr(status, "online", False):
    mode = None
  elif getattr(status, "power_on", None) is False:
    mode = "off"
  elif getattr(status, "power_on", None) is not True:
    mode = None
  else:
    raw_status = getattr(status, "raw_status", None) or {}
    sn_mode = str(raw_status.get("SN_MODE") or "").strip()
    if sn_mode:
      mode = SN_MODE_TO_XIAOBIU.get(sn_mode)
    else:
      c_mode = str(raw_status.get("C_MODE") or status.mode_raw or "").strip()
      mode = C_MODE_TO_XIAOBIU.get(c_mode)

  action = None
  if getattr(status, "online", False):
    action = infer_hvac_action(
      power_on=getattr(status, "power_on", None),
      hvac_mode=mode,
      current_temp=getattr(status, "current_temperature", None),
      target_temp=getattr(status, "target_temperature", None),
    )
  try:
    status.hvac_mode = mode
    status.hvac_action = action
    raw_status = getattr(status, "raw_status", None) or {}
    fresh_air = _parse_bool_flag(
      raw_status.get("C_FRESHAIR")
      if raw_status.get("C_FRESHAIR") not in (None, "")
      else raw_status.get("SN_PURIFY")
    )
    if fresh_air is not None:
      status.fresh_air_enabled = fresh_air
      status.purify_enabled = fresh_air
  except (AttributeError, ValueError):
    return


def _parse_bool_flag(value: Any) -> bool | None:
  normalized = str(value).strip().lower()
  if normalized in {"1", "true", "on", "yes"}:
    return True
  if normalized in {"0", "false", "off", "no"}:
    return False
  return None


def get_device_capabilities(client: Any, status: Any) -> Any | None:
  """Backport 0.2.2's corrected panel request and dynamic mode list."""

  from xiaobiu.ac_control import (
    build_capabilities_from_template,
    parse_panel_components,
  )

  model_id = getattr(status, "model", None)
  if not model_id:
    return None
  query = f"{PANEL_QUERY_URL}?modelId={model_id}&templateId=PANEL_AC"
  headers: dict[str, str] = {}
  try:
    custno = client.session.cookies.get("custno")
  except Exception:
    custno = None
  if custno:
    headers["userid"] = str(custno)
  try:
    response = client.session.get(query, timeout=client.timeout, headers=headers)
    response.raise_for_status()
    payload = response.json()
  except Exception:
    return None
  if not isinstance(payload, Mapping) or str(payload.get("code") or "") != "0":
    return None
  data_block = payload.get("data") or {}
  if not isinstance(data_block, Mapping):
    return None
  components = parse_panel_components(data_block.get("containers") or [])
  if components is None:
    return None
  caps = build_capabilities_from_template(
    device_id=str(status.device_id),
    model_id=str(model_id),
    category_id=str(getattr(status, "category_id", None) or "0002"),
    fields=components,
    raw=data_block,
  )

  mode_field = caps.fields.get("C_MODE")
  advertised = mode_field.raw_values if mode_field is not None else []
  if not advertised:
    advertised = list(C_MODE_TO_XIAOBIU)
  modes = ["off"]
  for raw in advertised:
    mode = C_MODE_TO_XIAOBIU.get(str(raw).strip())
    if mode is not None and mode not in modes:
      modes.append(mode)
  caps.hvac_modes = modes
  return caps


def infer_hvac_action(
  *,
  power_on: bool | None,
  hvac_mode: str | None,
  current_temp: float | None,
  target_temp: float | None,
) -> str | None:
  if power_on is None:
    return None
  if power_on is False or hvac_mode == "off":
    return "off"
  if hvac_mode is None:
    return "idle"
  if hvac_mode == "dry":
    return "drying"
  if hvac_mode == "fan_only":
    return "fan"
  if current_temp is None or target_temp is None:
    return "idle"
  if hvac_mode == "heat":
    return "heating" if current_temp < target_temp else "idle"
  if hvac_mode == "cool":
    return "cooling" if current_temp > target_temp else "idle"
  if hvac_mode in ("auto", "quick", "heat_cool"):
    if current_temp < target_temp:
      return "heating"
    if current_temp > target_temp:
      return "cooling"
  return "idle"
