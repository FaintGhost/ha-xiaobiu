from __future__ import annotations

from functools import partial
import logging
from typing import Any, Callable

import requests

from homeassistant.components.climate import (
  ClimateEntity,
  ClimateEntityFeature,
  HVACAction,
  HVACMode,
)
from homeassistant.components.climate.const import (
  SWING_BOTH,
  SWING_HORIZONTAL,
  SWING_OFF,
  SWING_VERTICAL,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SuningConfigEntry, SuningRuntimeData
from .client_lib import load_client_lib
from .const import (
  CONF_FAMILY_ID,
  DOMAIN,
  PRESET_AUX_HEAT,
  PRESET_ECO,
  PRESET_FRESH_AIR,
  PRESET_NONE,
)
from .coordinator import SuningDataUpdateCoordinator
from .protocol import (
  FAN_SPEED_FROM_RAW,
  FAN_SPEED_TO_RAW,
  XIAOBIU_TO_C_MODE,
)

_LOGGER = logging.getLogger(__name__)


# python-xiaobiu values are deliberately translated only at the HA boundary.
# The dependency owns the protocol-level SN_MODE/C_MODE tables.
XIAOBIU_TO_HA_HVAC: dict[str, HVACMode] = {
  "off": HVACMode.OFF,
  "cool": HVACMode.COOL,
  "heat": HVACMode.HEAT,
  "auto": HVACMode.AUTO,
  "quick": HVACMode.AUTO,
  "dry": HVACMode.DRY,
  "fan_only": HVACMode.FAN_ONLY,
}
HA_TO_XIAOBIU_HVAC: dict[HVACMode, str] = {
  HVACMode.OFF: "off",
  HVACMode.COOL: "cool",
  HVACMode.HEAT: "heat",
  HVACMode.AUTO: "auto",
  HVACMode.DRY: "dry",
  HVACMode.FAN_ONLY: "fan_only",
}
XIAOBIU_TO_HA_ACTION: dict[str, HVACAction] = {
  "off": HVACAction.OFF,
  "preheating": HVACAction.PREHEATING,
  "heating": HVACAction.HEATING,
  "cooling": HVACAction.COOLING,
  "drying": HVACAction.DRYING,
  "fan": HVACAction.FAN,
  "idle": HVACAction.IDLE,
  "defrosting": HVACAction.DEFROSTING,
}

SUPPORTED_PRESETS: tuple[str, ...] = (
  PRESET_NONE,
  PRESET_ECO,
  PRESET_FRESH_AIR,
  PRESET_AUX_HEAT,
)
PRESET_STATUS_FIELDS: dict[str, str] = {
  PRESET_ECO: "eco_enabled",
  PRESET_FRESH_AIR: "fresh_air_enabled",
  PRESET_AUX_HEAT: "electric_heating_enabled",
}


async def async_setup_entry(
  hass: HomeAssistant,
  entry: SuningConfigEntry,
  async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
  runtime_data: SuningRuntimeData = entry.runtime_data
  async_add_entities(
    SuningClimateEntity(
      coordinator=runtime_data.coordinator,
      entry=entry,
      device_id=device_id,
    )
    for device_id in runtime_data.coordinator.device_ids
  )


class SuningClimateEntity(
  CoordinatorEntity[SuningDataUpdateCoordinator], ClimateEntity,
):
  """Home Assistant climate representation of a Xiaobiu air conditioner."""

  _attr_has_entity_name = True
  _attr_translation_key = "suning_air_conditioner"
  _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
  _attr_target_temperature_step = 1.0

  def __init__(
    self,
    *,
    coordinator: SuningDataUpdateCoordinator,
    entry: SuningConfigEntry,
    device_id: str,
  ) -> None:
    super().__init__(coordinator, context=device_id)
    self._entry = entry
    self._device_id = device_id
    self._attr_unique_id = f"{entry.entry_id}_{device_id}"
    self._last_non_off_hvac_mode: HVACMode | None = None
    current_mode = self.hvac_mode
    if current_mode not in (None, HVACMode.OFF):
      self._last_non_off_hvac_mode = current_mode

  @property
  def _status(self) -> Any:
    return self.coordinator.status_for(self._device_id)

  @property
  def _capabilities(self) -> Any | None:
    return self.coordinator.capabilities_for(self._device_id)

  @property
  def available(self) -> bool:
    if not super().available:
      return False
    try:
      return bool(self._status.available)
    except KeyError:
      return False

  @property
  def name(self) -> str | None:
    return None

  @property
  def device_info(self) -> DeviceInfo:
    status = self._status
    return DeviceInfo(
      identifiers={(DOMAIN, status.device_id)},
      name=status.name,
      model=status.model,
      manufacturer="Suning",
      suggested_area=status.group_name,
    )

  @property
  def min_temp(self) -> float:
    caps = self._capabilities
    if caps is not None and caps.min_target_temperature is not None:
      return float(caps.min_target_temperature)
    return 16.0

  @property
  def max_temp(self) -> float:
    caps = self._capabilities
    if caps is not None and caps.max_target_temperature is not None:
      return float(caps.max_target_temperature)
    return 32.0

  @property
  def hvac_modes(self) -> list[HVACMode]:
    caps = self._capabilities
    raw_modes = (
      caps.hvac_modes
      if caps is not None
      else ("off", "heat", "cool", "auto", "dry", "fan_only")
    )
    modes: list[HVACMode] = []
    for raw in raw_modes:
      mapped = XIAOBIU_TO_HA_HVAC.get(str(raw))
      if mapped is not None and mapped not in modes:
        modes.append(mapped)
    if HVACMode.OFF in modes:
      modes.remove(HVACMode.OFF)
    modes.insert(0, HVACMode.OFF)
    return modes

  @property
  def hvac_mode(self) -> HVACMode | None:
    status = self._status
    if getattr(status, "power_on", None) is False:
      return HVACMode.OFF
    raw = getattr(status, "hvac_mode", None)
    if raw is None:
      return None
    value = str(getattr(raw, "value", raw))
    return XIAOBIU_TO_HA_HVAC.get(value)

  @property
  def hvac_action(self) -> HVACAction | None:
    if getattr(self._status, "power_on", None) is False:
      return HVACAction.OFF
    raw = getattr(self._status, "hvac_action", None)
    if raw is None:
      return None
    value = str(getattr(raw, "value", raw))
    return XIAOBIU_TO_HA_ACTION.get(value)

  @property
  def native_current_temperature(self) -> float | None:
    return self._status.current_temperature

  @property
  def native_target_temperature(self) -> float | None:
    return self._status.target_temperature

  @property
  def fan_modes(self) -> list[str] | None:
    caps = self._capabilities
    if caps is None and getattr(self._status, "fan_mode_raw", None) is None:
      return None
    raw_modes = (
      caps.fan_modes
      if caps is not None
      else tuple(FAN_SPEED_FROM_RAW.values())
    )
    supported = set(FAN_SPEED_FROM_RAW.values())
    modes = [str(mode) for mode in raw_modes if str(mode) in supported]
    return list(dict.fromkeys(modes)) or None

  @property
  def fan_mode(self) -> str | None:
    raw = getattr(self._status, "fan_mode_raw", None)
    if raw is None:
      return None
    return FAN_SPEED_FROM_RAW.get(str(raw).strip())

  @property
  def swing_modes(self) -> list[str] | None:
    caps = self._capabilities
    supports_vertical = (
      caps.supports_vertical_swing
      if caps is not None
      else getattr(self._status, "swing_vertical", None) is not None
    )
    supports_horizontal = (
      caps.supports_horizontal_swing
      if caps is not None
      else getattr(self._status, "swing_horizontal", None) is not None
    )
    if not supports_vertical and not supports_horizontal:
      return None
    modes = [SWING_OFF]
    if supports_vertical:
      modes.append(SWING_VERTICAL)
    if supports_horizontal:
      modes.append(SWING_HORIZONTAL)
    if supports_vertical and supports_horizontal:
      modes.append(SWING_BOTH)
    return modes

  @property
  def swing_mode(self) -> str | None:
    modes = self.swing_modes
    if modes is None:
      return None
    vertical = getattr(self._status, "swing_vertical", None)
    horizontal = getattr(self._status, "swing_horizontal", None)
    if vertical is True and horizontal is True:
      return SWING_BOTH
    if vertical is True:
      return SWING_VERTICAL
    if horizontal is True:
      return SWING_HORIZONTAL
    vertical_off = SWING_VERTICAL not in modes or vertical is False
    horizontal_off = SWING_HORIZONTAL not in modes or horizontal is False
    if vertical_off and horizontal_off:
      return SWING_OFF
    return None

  @property
  def preset_modes(self) -> list[str] | None:
    caps = self._capabilities
    if caps is None:
      return None
    advertised = {str(mode) for mode in caps.preset_modes}
    modes = [
      mode for mode in SUPPORTED_PRESETS
      if mode != PRESET_NONE and mode in advertised
    ]
    return [PRESET_NONE, *modes] if modes else None

  @property
  def preset_mode(self) -> str | None:
    if self.preset_modes is None:
      return None
    # HA exposes one current preset. Commands issued by this integration are
    # made exclusive; if the vendor app enables several flags, use a stable
    # priority until the user selects a single preset again.
    for preset in (PRESET_AUX_HEAT, PRESET_FRESH_AIR, PRESET_ECO):
      field = PRESET_STATUS_FIELDS[preset]
      if preset in self.preset_modes and getattr(self._status, field, False):
        return preset
    return PRESET_NONE

  @property
  def supported_features(self) -> ClimateEntityFeature:
    features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    caps = self._capabilities
    if (
      (caps is None and self.native_target_temperature is not None)
      or (caps is not None and caps.supports_target_temperature)
    ):
      features |= ClimateEntityFeature.TARGET_TEMPERATURE
    if self.fan_modes:
      features |= ClimateEntityFeature.FAN_MODE
    if self.swing_modes:
      features |= ClimateEntityFeature.SWING_MODE
    if self.preset_modes:
      features |= ClimateEntityFeature.PRESET_MODE
    return features

  @property
  def extra_state_attributes(self) -> dict[str, Any]:
    status = self._status
    return {
      CONF_FAMILY_ID: self.coordinator.family_id,
      "group_id": status.group_id,
      "group_name": status.group_name,
      "summary": status.summary,
      "device_record_time": status.device_record_time,
      "refresh_time": status.refresh_time,
      "raw_mode": status.mode_raw,
      "raw_fan_mode": status.fan_mode_raw,
      "online": status.online,
      "swing_vertical": getattr(status, "swing_vertical", None),
      "swing_horizontal": getattr(status, "swing_horizontal", None),
      "capabilities_loaded": self._capabilities is not None,
    }

  @callback
  def _handle_coordinator_update(self) -> None:
    current_mode = self.hvac_mode
    if current_mode not in (None, HVACMode.OFF):
      self._last_non_off_hvac_mode = current_mode
    _LOGGER.debug(
      "xiaobiu %s: state update power=%r mode_raw=%r mode=%r action=%r fan=%r available=%r",
      self._device_id,
      getattr(self._status, "power_on", None),
      getattr(self._status, "mode_raw", None),
      current_mode,
      self.hvac_action,
      self.fan_mode,
      getattr(self._status, "available", None),
    )
    super()._handle_coordinator_update()

  async def _async_execute(
    self,
    fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
  ) -> Any:
    client_lib = load_client_lib()
    try:
      return await self.hass.async_add_executor_job(partial(fn, *args, **kwargs))
    except client_lib.AuthenticationError as err:
      raise ConfigEntryAuthFailed(str(err)) from err
    except (
      client_lib.SuningError,
      client_lib.SmsRateLimitedError,
      requests.RequestException,
    ) as err:
      raise HomeAssistantError(f"xiaobiu control failed: {err}") from err

  def _optimistically_update(self, **changes: Any) -> None:
    status = self._status
    for field, value in changes.items():
      try:
        setattr(status, field, value)
      except (AttributeError, ValueError):
        _LOGGER.debug(
          "xiaobiu %s: cannot optimistically set %s=%r",
          self._device_id,
          field,
          value,
        )
    if self.entity_id is not None:
      self.async_write_ha_state()

  def _resolve_control_ids(self) -> tuple[str, str]:
    return str(self.coordinator.family_id), str(self._status.device_id)

  def _turn_on_mode(self) -> HVACMode | None:
    if self._last_non_off_hvac_mode in self.hvac_modes:
      return self._last_non_off_hvac_mode
    if HVACMode.AUTO in self.hvac_modes:
      return HVACMode.AUTO
    return next(
      (mode for mode in self.hvac_modes if mode != HVACMode.OFF),
      None,
    )

  async def async_turn_on(self) -> None:
    family_id, device_id = self._resolve_control_ids()
    target_mode = self._turn_on_mode()
    await self._async_execute(self.coordinator.client.turn_on, family_id, device_id)
    changes: dict[str, Any] = {"power_on": True, "hvac_action": "idle"}
    if target_mode is not None:
      changes["hvac_mode"] = HA_TO_XIAOBIU_HVAC[target_mode]
    self._optimistically_update(**changes)

  async def async_turn_off(self) -> None:
    current_mode = self.hvac_mode
    if current_mode not in (None, HVACMode.OFF):
      self._last_non_off_hvac_mode = current_mode
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(self.coordinator.client.turn_off, family_id, device_id)
    self._optimistically_update(
      power_on=False,
      hvac_mode="off",
      hvac_action="off",
    )

  async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
    if hvac_mode == HVACMode.OFF:
      await self.async_turn_off()
      return
    if hvac_mode not in self.hvac_modes or hvac_mode not in HA_TO_XIAOBIU_HVAC:
      raise HomeAssistantError(f"unsupported HVAC mode: {hvac_mode}")

    _family_id, device_id = self._resolve_control_ids()
    xiaobiu_mode = HA_TO_XIAOBIU_HVAC[hvac_mode]
    c_mode = XIAOBIU_TO_C_MODE[xiaobiu_mode]
    model_id = getattr(self._status, "model", None)
    if not model_id:
      raise HomeAssistantError(
        f"cannot control {device_id}: device model is unavailable"
      )
    command = {"C_MODE": c_mode}
    if getattr(self._status, "power_on", None) is False:
      command["C_POWER"] = "1"
    await self._async_execute(
      self.coordinator.client.app_oper,
      device_id,
      str(model_id),
      command,
    )

    self._last_non_off_hvac_mode = hvac_mode
    optimistic_action = {
      HVACMode.DRY: "drying",
      HVACMode.FAN_ONLY: "fan",
    }.get(hvac_mode, "idle")
    self._optimistically_update(
      power_on=True,
      hvac_mode=HA_TO_XIAOBIU_HVAC[hvac_mode],
      hvac_action=optimistic_action,
    )

  async def async_set_temperature(self, **kwargs: Any) -> None:
    temperature = kwargs.get(ATTR_TEMPERATURE)
    if temperature is None:
      return
    family_id, device_id = self._resolve_control_ids()
    value = float(temperature)
    await self._async_execute(
      self.coordinator.client.set_temperature,
      family_id,
      device_id,
      value,
    )
    self._optimistically_update(target_temperature=value)

  async def async_set_fan_mode(self, fan_mode: str) -> None:
    if self.fan_modes is None or fan_mode not in self.fan_modes:
      raise HomeAssistantError(f"unsupported fan mode: {fan_mode}")
    client_lib = load_client_lib()
    speed = client_lib.FanSpeed(fan_mode)
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(
      self.coordinator.client.set_fan_mode,
      family_id,
      device_id,
      speed,
    )
    raw_speed = FAN_SPEED_TO_RAW.get(speed.value)
    if raw_speed is not None:
      self._optimistically_update(fan_mode_raw=raw_speed)

  async def async_set_swing_mode(self, swing_mode: str) -> None:
    modes = self.swing_modes
    if modes is None or swing_mode not in modes:
      raise HomeAssistantError(f"unsupported swing mode: {swing_mode}")
    _family_id, device_id = self._resolve_control_ids()
    model_id = getattr(self._status, "model", None)
    if not model_id:
      raise HomeAssistantError(
        f"cannot control {device_id}: device model is unavailable"
      )
    vertical = swing_mode in (SWING_VERTICAL, SWING_BOTH)
    horizontal = swing_mode in (SWING_HORIZONTAL, SWING_BOTH)
    command: dict[str, str] = {}
    if SWING_VERTICAL in modes:
      command["C_AIRVERTICAL"] = "1" if vertical else "0"
    if SWING_HORIZONTAL in modes:
      command["C_AIRHORIZONTAL"] = "1" if horizontal else "0"
    await self._async_execute(
      self.coordinator.client.app_oper,
      device_id,
      str(model_id),
      command,
    )
    changes: dict[str, bool] = {}
    if SWING_VERTICAL in modes:
      changes["swing_vertical"] = vertical
    if SWING_HORIZONTAL in modes:
      changes["swing_horizontal"] = horizontal
    self._optimistically_update(**changes)

  async def _async_set_preset_flag(self, preset: str, *, on: bool) -> None:
    fields = {
      PRESET_ECO: "C_ECO",
      PRESET_FRESH_AIR: "C_FRESHAIR",
      PRESET_AUX_HEAT: "C_ELECHEATING",
    }
    _family_id, device_id = self._resolve_control_ids()
    model_id = getattr(self._status, "model", None)
    if not model_id:
      raise HomeAssistantError(
        f"cannot control {device_id}: device model is unavailable"
      )
    await self._async_execute(
      self.coordinator.client.app_oper,
      device_id,
      str(model_id),
      {fields[preset]: "1" if on else "0"},
    )

  async def async_set_preset_mode(self, preset_mode: str) -> None:
    modes = self.preset_modes
    if modes is None or preset_mode not in modes:
      raise HomeAssistantError(f"unsupported preset mode: {preset_mode}")

    if preset_mode == PRESET_NONE:
      for preset in modes:
        if preset != PRESET_NONE:
          await self._async_set_preset_flag(preset, on=False)
    else:
      # Enable first so a rejected command (notably aux heat outside HEAT)
      # does not turn off the currently active preset.
      await self._async_set_preset_flag(preset_mode, on=True)
      for other in modes:
        if other in (PRESET_NONE, preset_mode):
          continue
        field = PRESET_STATUS_FIELDS[other]
        if getattr(self._status, field, False):
          await self._async_set_preset_flag(other, on=False)

    changes = {field: False for field in PRESET_STATUS_FIELDS.values()}
    if preset_mode != PRESET_NONE:
      changes[PRESET_STATUS_FIELDS[preset_mode]] = True
    self._optimistically_update(**changes)
