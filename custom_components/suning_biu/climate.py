from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from suning_biu_ha import AirConditionerStatus

from . import SuningRuntimeData
from .const import CONF_FAMILY_ID, DOMAIN
from .coordinator import SuningDataUpdateCoordinator


async def async_setup_entry(
  hass: HomeAssistant,
  entry: ConfigEntry,
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


class SuningClimateEntity(CoordinatorEntity[SuningDataUpdateCoordinator], ClimateEntity):
  _attr_has_entity_name = True
  _attr_translation_key = "suning_air_conditioner"
  _attr_temperature_unit = UnitOfTemperature.CELSIUS
  _attr_target_temperature_step = 1.0
  _enable_turn_on_off_backwards_compatibility = False

  def __init__(
    self,
    *,
    coordinator: SuningDataUpdateCoordinator,
    entry: ConfigEntry,
    device_id: str,
  ) -> None:
    super().__init__(coordinator)
    self._entry = entry
    self._device_id = device_id
    self._attr_unique_id = f"{entry.entry_id}_{device_id}"

  @property
  def _status(self) -> AirConditionerStatus:
    return self.coordinator.status_for(self._device_id)

  @property
  def available(self) -> bool:
    return self._status.available

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
  def hvac_modes(self) -> list[HVACMode]:
    return [HVACMode.OFF]

  @property
  def hvac_mode(self) -> HVACMode | None:
    preview = self._status.ha_climate_preview
    if preview is None or preview.hvac_mode is None:
      return None
    if preview.hvac_mode == "off":
      return HVACMode.OFF
    return None

  @property
  def current_temperature(self) -> float | None:
    return self._status.current_temperature

  @property
  def target_temperature(self) -> float | None:
    return self._status.target_temperature

  @property
  def fan_mode(self) -> str | None:
    preview = self._status.ha_climate_preview
    if preview is None:
      return None
    return preview.fan_mode

  @property
  def swing_mode(self) -> str | None:
    preview = self._status.ha_climate_preview
    if preview is None:
      return None
    return preview.swing_mode

  @property
  def preset_mode(self) -> str | None:
    preview = self._status.ha_climate_preview
    if preview is None:
      return None
    return preview.preset_mode

  @property
  def extra_state_attributes(self) -> dict[str, Any]:
    status = self._status
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
    }
