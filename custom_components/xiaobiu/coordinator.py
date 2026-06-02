from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client_lib import load_client_lib
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class SuningDataUpdateCoordinator(DataUpdateCoordinator[dict[str, object]]):
  def __init__(
    self,
    *,
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    client: object,
    family_id: str,
  ) -> None:
    super().__init__(
      hass,
      _LOGGER,
      name=f"{DOMAIN}_{family_id}",
      update_interval=SCAN_INTERVAL,
      config_entry=config_entry,
    )
    self.client = client
    self.family_id = family_id
    self._capabilities: dict[str, Any] = {}
    self._capabilities_warned: set[str] = set()

  async def _async_update_data(self) -> dict[str, object]:
    from .climate import (
      C_FIELD_TO_HVAC_MODE,
      FAN_SPEED_FROM_RAW,
      infer_hvac_action_from,
    )

    client_lib = load_client_lib()
    try:
      await self.hass.async_add_executor_job(self.client.keep_alive)
      statuses = await self.hass.async_add_executor_job(
        self.client.list_air_conditioner_statuses,
        self.family_id,
      )
    except client_lib.AuthenticationError as error:
      raise ConfigEntryAuthFailed(str(error)) from error
    except (client_lib.SuningError, requests.RequestException) as error:
      raise UpdateFailed(str(error)) from error

    enriched: dict[str, object] = {}
    for status in statuses:
      # status.SN_MODE is the SNV index; the C_FIELD table below mirrors the
      # HAR queryTemplate keys array (k="1"->制热, k="2"->制冷, k="3"->除湿,
      # k="4"->送风, k="6"->一键通). xiaobiu 0.2.1 ships an incorrect mapping
      # where it confuses SNV and C_FIELD indexing, so we re-derive locally.
      snv = str(getattr(status, "mode_raw", None) or "").strip()
      hvac_mode = C_FIELD_TO_HVAC_MODE.get(snv)
      hvac_action = infer_hvac_action_from(
        power_on=status.power_on,
        hvac_mode=hvac_mode,
        current_temp=status.current_temperature,
        target_temp=status.target_temperature,
      )
      fan_mode = FAN_SPEED_FROM_RAW.get(
        str(getattr(status, "fan_mode_raw", None) or "").strip()
      )
      try:
        status.hvac_mode = hvac_mode  # type: ignore[attr-defined]
        status.hvac_action = hvac_action  # type: ignore[attr-defined]
        status.fan_mode = fan_mode  # type: ignore[attr-defined]
      except (AttributeError, ValueError):
        pass
      enriched[status.device_id] = status
    return enriched

  async def async_load_capabilities(self) -> None:
    """Fetch each AC's device panel template once after the first refresh.

    Capabilities describe the device's control surface (which HVAC/fan/swing
    modes it exposes). They are static, so we load them at setup time and
    surface them via :meth:`capabilities_for`.
    """
    if not self.last_update_success or not self.data:
      return
    client_lib = load_client_lib()
    for device_id in self.data:
      if device_id in self._capabilities:
        continue
      try:
        caps = await self.hass.async_add_executor_job(
          self.client.get_device_panel_template,
          self.family_id,
          device_id,
        )
      except client_lib.AuthenticationError as error:
        raise ConfigEntryAuthFailed(str(error)) from error
      except (client_lib.SuningError, requests.RequestException) as error:
        if device_id not in self._capabilities_warned:
          _LOGGER.warning(
            "xiaobiu capabilities load failed for %s: %s", device_id, error,
          )
          self._capabilities_warned.add(device_id)
        self._capabilities[device_id] = None
      else:
        self._capabilities[device_id] = caps

  def capabilities_for(self, device_id: str) -> Any | None:
    return self._capabilities.get(device_id)

  def status_for(self, device_id: str) -> object:
    status = self.data.get(device_id)
    if status is None:
      raise KeyError(device_id)
    return status

  @property
  def device_ids(self) -> tuple[str, ...]:
    return tuple(self.data)

  @property
  def statuses(self) -> Mapping[str, object]:
    return self.data
