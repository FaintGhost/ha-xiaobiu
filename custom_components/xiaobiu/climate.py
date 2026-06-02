from __future__ import annotations

from functools import partial
import logging
from typing import Any

import requests

from homeassistant.components.climate import (
  ClimateEntity,
  ClimateEntityFeature,
  HVACAction,
  HVACMode,
)
from homeassistant.components.climate.const import (
  SWING_HORIZONTAL_OFF,
  SWING_HORIZONTAL_ON,
  SWING_OFF,
  SWING_ON,
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

_LOGGER = logging.getLogger(__name__)

XIAOBIU_TO_HA_HVAC: dict[str, HVACMode] = {
  "off": HVACMode.OFF,
  "cool": HVACMode.COOL,
  "heat": HVACMode.HEAT,
  "heat_cool": HVACMode.HEAT_COOL,
  "auto": HVACMode.AUTO,
  "dry": HVACMode.DRY,
  "fan_only": HVACMode.FAN_ONLY,
  "quick": HVACMode.COOL,
}
HA_TO_XIAOBIU_HVAC: dict[HVACMode, str] = {
  HVACMode.OFF: "off",
  HVACMode.COOL: "cool",
  HVACMode.HEAT: "heat",
  HVACMode.HEAT_COOL: "heat_cool",
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
  _attr_has_entity_name = True
  _attr_translation_key = "suning_air_conditioner"
  _attr_temperature_unit = UnitOfTemperature.CELSIUS
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

  @property
  def _status(self) -> Any:
    return self.coordinator.status_for(self._device_id)

  @property
  def _capabilities(self) -> Any | None:
    return self.coordinator.capabilities_for(self._device_id)

  @property
  def available(self) -> bool:
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
    if caps is None or not caps.hvac_modes:
      _LOGGER.debug(
        "xiaobiu %s: no capabilities, defaulting hvac_modes to safe subset",
        self._device_id,
      )
      return [
        HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT,
        HVACMode.AUTO, HVACMode.DRY, HVACMode.FAN_ONLY,
      ]
    modes: list[HVACMode] = []
    for raw in caps.hvac_modes:
      mapped = XIAOBIU_TO_HA_HVAC.get(raw)
      if mapped is not None and mapped not in modes:
        modes.append(mapped)
    if HVACMode.OFF not in modes:
      modes.append(HVACMode.OFF)
    return modes or [HVACMode.OFF]

  @property
  def hvac_mode(self) -> HVACMode | None:
    status = self._status
    raw = getattr(status, "hvac_mode", None)
    if raw is None:
      if getattr(status, "power_on", None) is False:
        return HVACMode.OFF
      _LOGGER.debug(
        "xiaobiu %s: status.hvac_mode is None and power_on=%r, returning None",
        self._device_id, getattr(status, "power_on", None),
      )
      return None
    value = getattr(raw, "value", raw)
    if value == "off":
      return HVACMode.OFF
    mapped = XIAOBIU_TO_HA_HVAC.get(str(value))
    if mapped is None:
      _LOGGER.debug(
        "xiaobiu %s: unmapped hvac_mode %r, returning None", self._device_id, value,
      )
    return mapped

  @property
  def hvac_action(self) -> HVACAction | None:
    raw = getattr(self._status, "hvac_action", None)
    if raw is None:
      if self.hvac_mode == HVACMode.OFF:
        return HVACAction.OFF
      return HVACAction.IDLE
    value = getattr(raw, "value", raw)
    return XIAOBIU_TO_HA_ACTION.get(str(value))

  @property
  def current_temperature(self) -> float | None:
    return self._status.current_temperature

  @property
  def target_temperature(self) -> float | None:
    return self._status.target_temperature

  @property
  def fan_modes(self) -> list[str] | None:
    caps = self._capabilities
    if caps is None or not caps.fan_modes:
      return ["auto", "low", "medium", "high", "turbo"]
    return list(caps.fan_modes)

  @property
  def fan_mode(self) -> str | None:
    status = self._status
    raw = getattr(status, "fan_mode", None)
    if raw is None:
      return None
    return getattr(raw, "value", raw)

  @property
  def swing_modes(self) -> list[str] | None:
    caps = self._capabilities
    if caps is None:
      return [SWING_ON, SWING_OFF]
    if not caps.supports_vertical_swing:
      return None
    return [SWING_ON, SWING_OFF]

  @property
  def swing_mode(self) -> str | None:
    caps = self._capabilities
    if caps is not None and not caps.supports_vertical_swing:
      return None
    return SWING_ON if self._status.swing_vertical else SWING_OFF

  @property
  def swing_horizontal_modes(self) -> list[str] | None:
    caps = self._capabilities
    if caps is None:
      return [SWING_HORIZONTAL_ON, SWING_HORIZONTAL_OFF]
    if not caps.supports_horizontal_swing:
      return None
    return [SWING_HORIZONTAL_ON, SWING_HORIZONTAL_OFF]

  @property
  def swing_horizontal_mode(self) -> str | None:
    caps = self._capabilities
    if caps is not None and not caps.supports_horizontal_swing:
      return None
    return SWING_HORIZONTAL_ON if self._status.swing_horizontal else SWING_HORIZONTAL_OFF

  @property
  def preset_modes(self) -> list[str] | None:
    caps = self._capabilities
    if caps is None:
      return None
    modes = [PRESET_NONE]
    if caps.supports_eco:
      modes.append(PRESET_ECO)
    if caps.supports_fresh_air:
      modes.append(PRESET_FRESH_AIR)
    if caps.supports_aux_heat:
      modes.append(PRESET_AUX_HEAT)
    return modes

  @property
  def preset_mode(self) -> str | None:
    caps = self._capabilities
    if caps is None:
      return None
    status = self._status
    if caps.supports_aux_heat and status.electric_heating_enabled:
      return PRESET_AUX_HEAT
    if caps.supports_eco and status.eco_enabled:
      return PRESET_ECO
    if caps.supports_fresh_air and status.fresh_air_enabled:
      return PRESET_FRESH_AIR
    return PRESET_NONE

  @property
  def supported_features(self) -> ClimateEntityFeature:
    features = (
      ClimateEntityFeature.TURN_ON
      | ClimateEntityFeature.TURN_OFF
      | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    if self.fan_modes:
      features |= ClimateEntityFeature.FAN_MODE
    if self.swing_modes:
      features |= ClimateEntityFeature.SWING_MODE
    if self.swing_horizontal_modes:
      features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
    if self.preset_modes:
      features |= ClimateEntityFeature.PRESET_MODE
    return features

  @property
  def extra_state_attributes(self) -> dict[str, Any]:
    status = self._status
    caps = self._capabilities
    raw_action = getattr(status, "hvac_action", None)
    action_value = getattr(raw_action, "value", raw_action) if raw_action else None
    raw_mode = getattr(status, "hvac_mode", None)
    mode_value = getattr(raw_mode, "value", raw_mode) if raw_mode else None
    return {
      CONF_FAMILY_ID: status.family_id,
      "group_id": status.group_id,
      "group_name": status.group_name,
      "summary": status.summary,
      "device_record_time": status.device_record_time,
      "refresh_time": status.refresh_time,
      "raw_mode": status.mode_raw,
      "raw_fan_mode": status.fan_mode_raw,
      "online": status.online,
      "hvac_mode": mode_value,
      "hvac_action": action_value,
      "swing_vertical": getattr(status, "swing_vertical", None),
      "swing_horizontal": getattr(status, "swing_horizontal", None),
      "capabilities_loaded": caps is not None,
    }

  @callback
  def _handle_coordinator_update(self) -> None:
    status = self._status
    caps = self._capabilities
    _LOGGER.info(
      "xiaobiu %s: state update — power_on=%s mode_raw=%r hvac_mode=%r "
      "hvac_action=%r fan_raw=%r swing_v=%s swing_h=%s eco=%s fresh=%s aux=%s "
      "caps=%s available=%s current_temp=%s target_temp=%s",
      self._device_id,
      getattr(status, "power_on", None),
      getattr(status, "mode_raw", None),
      getattr(getattr(status, "hvac_mode", None), "value", None),
      getattr(getattr(status, "hvac_action", None), "value", None),
      getattr(status, "fan_mode_raw", None),
      getattr(status, "swing_vertical", None),
      getattr(status, "swing_horizontal", None),
      getattr(status, "eco_enabled", None),
      getattr(status, "fresh_air_enabled", None),
      getattr(status, "electric_heating_enabled", None),
      caps is not None,
      getattr(status, "available", None),
      getattr(status, "current_temperature", None),
      getattr(status, "target_temperature", None),
    )
    self.async_write_ha_state()

  async def _async_execute(self, fn, *args, **kwargs) -> None:
    client_lib = load_client_lib()
    bound = partial(fn, *args, **kwargs)
    try:
      await self.hass.async_add_executor_job(bound)
    except client_lib.AuthenticationError as err:
      _LOGGER.warning(
        "xiaobiu %s: auth error during control: %s", self._device_id, err,
      )
      raise ConfigEntryAuthFailed(str(err)) from err
    except (
      client_lib.SuningError,
      client_lib.SmsRateLimitedError,
      requests.RequestException,
    ) as err:
      _LOGGER.warning(
        "xiaobiu %s: control call failed: %s", self._device_id, err,
      )
      raise HomeAssistantError(f"xiaobiu control failed: {err}") from err
    _LOGGER.info(
      "xiaobiu %s: control call returned, requesting coordinator refresh",
      self._device_id,
    )
    await self.coordinator.async_request_refresh()

  def _resolve_control_ids(self) -> tuple[str, str]:
    status = self._status
    return str(status.family_id), str(status.device_id)

  async def async_turn_on(self) -> None:
    _LOGGER.info("xiaobiu %s: turn_on requested", self._device_id)
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(
      self.coordinator.client.turn_on, family_id, device_id,
    )

  async def async_turn_off(self) -> None:
    _LOGGER.info("xiaobiu %s: turn_off requested", self._device_id)
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(
      self.coordinator.client.turn_off, family_id, device_id,
    )

  async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
    _LOGGER.info(
      "xiaobiu %s: set_hvac_mode requested, hvac_mode=%s",
      self._device_id, hvac_mode,
    )
    xb_mode = HA_TO_XIAOBIU_HVAC.get(hvac_mode)
    if xb_mode is None:
      _LOGGER.error(
        "xiaobiu %s: no xiaobiu mapping for HA mode %s",
        self._device_id, hvac_mode,
      )
      raise HomeAssistantError(f"unsupported HVAC mode: {hvac_mode}")
    family_id, device_id = self._resolve_control_ids()
    _LOGGER.debug(
      "xiaobiu %s: dispatching %s -> xiaobiu mode=%r family=%s device=%s",
      self._device_id, hvac_mode, xb_mode, family_id, device_id,
    )
    if xb_mode == "off":
      await self._async_execute(
        self.coordinator.client.turn_off, family_id, device_id,
      )
      return
    # Suning's app_oper is a single-field command: C_MODE does not imply
    # C_POWER. If the device is currently off, send turn_on first so the
    # subsequent set_hvac_mode actually changes something physical.
    if getattr(self._status, "power_on", True) is False:
      _LOGGER.info(
        "xiaobiu %s: device is off, sending turn_on before set_hvac_mode",
        self._device_id,
      )
      await self._async_execute(
        self.coordinator.client.turn_on, family_id, device_id,
      )
    client_lib = load_client_lib()
    await self._async_execute(
      self.coordinator.client.set_hvac_mode,
      family_id, device_id, client_lib.HvacMode(xb_mode),
    )

  async def async_set_temperature(self, **kwargs: Any) -> None:
    temperature = kwargs.get(ATTR_TEMPERATURE)
    if temperature is None:
      return
    _LOGGER.info(
      "xiaobiu %s: set_temperature requested, target=%s",
      self._device_id, temperature,
    )
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(
      self.coordinator.client.set_temperature,
      family_id, device_id, float(temperature),
    )

  async def async_set_fan_mode(self, fan_mode: str) -> None:
    _LOGGER.info(
      "xiaobiu %s: set_fan_mode requested, fan_mode=%s",
      self._device_id, fan_mode,
    )
    client_lib = load_client_lib()
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(
      self.coordinator.client.set_fan_mode,
      family_id, device_id, client_lib.FanSpeed(fan_mode),
    )

  async def async_set_swing_mode(self, swing_mode: str) -> None:
    _LOGGER.info(
      "xiaobiu %s: set_swing_mode requested, swing_mode=%s",
      self._device_id, swing_mode,
    )
    on = swing_mode == SWING_ON
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(
      self.coordinator.client.set_vertical_swing,
      family_id, device_id, on=on,
    )

  async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
    _LOGGER.info(
      "xiaobiu %s: set_swing_horizontal_mode requested, mode=%s",
      self._device_id, swing_horizontal_mode,
    )
    on = swing_horizontal_mode == SWING_HORIZONTAL_ON
    family_id, device_id = self._resolve_control_ids()
    await self._async_execute(
      self.coordinator.client.set_horizontal_swing,
      family_id, device_id, on=on,
    )

  async def async_set_preset_mode(self, preset_mode: str) -> None:
    _LOGGER.info(
      "xiaobiu %s: set_preset_mode requested, preset=%s",
      self._device_id, preset_mode,
    )
    if preset_mode not in SUPPORTED_PRESETS:
      raise HomeAssistantError(f"unsupported preset mode: {preset_mode}")
    family_id, device_id = self._resolve_control_ids()
    client = self.coordinator.client
    if preset_mode == PRESET_NONE:
      await self._async_execute(client.set_eco, family_id, device_id, on=False)
      await self._async_execute(client.set_fresh_air, family_id, device_id, on=False)
      await self._async_execute(client.set_aux_heat, family_id, device_id, on=False)
      return
    if preset_mode == PRESET_ECO:
      await self._async_execute(client.set_eco, family_id, device_id, on=True)
    elif preset_mode == PRESET_FRESH_AIR:
      await self._async_execute(client.set_fresh_air, family_id, device_id, on=True)
    elif preset_mode == PRESET_AUX_HEAT:
      await self._async_execute(client.set_aux_heat, family_id, device_id, on=True)
