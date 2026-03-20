from __future__ import annotations

from collections.abc import Mapping
import logging

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

  async def _async_update_data(self) -> dict[str, object]:
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

    return {status.device_id: status for status in statuses}

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
