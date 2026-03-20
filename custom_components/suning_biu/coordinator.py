from __future__ import annotations

from collections.abc import Mapping
import logging

import requests

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from suning_biu_ha import AirConditionerStatus, AuthenticationError, SuningError, SuningSmartHomeClient

from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class SuningDataUpdateCoordinator(DataUpdateCoordinator[dict[str, AirConditionerStatus]]):
  def __init__(
    self,
    *,
    hass: HomeAssistant,
    client: SuningSmartHomeClient,
    family_id: str,
  ) -> None:
    super().__init__(
      hass,
      _LOGGER,
      name=f"{DOMAIN}_{family_id}",
      update_interval=SCAN_INTERVAL,
    )
    self.client = client
    self.family_id = family_id

  async def _async_update_data(self) -> dict[str, AirConditionerStatus]:
    try:
      await self.hass.async_add_executor_job(self.client.keep_alive)
      statuses = await self.hass.async_add_executor_job(
        self.client.list_air_conditioner_statuses,
        self.family_id,
      )
    except AuthenticationError as error:
      raise UpdateFailed(str(error)) from error
    except (SuningError, requests.RequestException) as error:
      raise UpdateFailed(str(error)) from error

    return {status.device_id: status for status in statuses}

  def status_for(self, device_id: str) -> AirConditionerStatus:
    status = self.data.get(device_id)
    if status is None:
      raise KeyError(device_id)
    return status

  @property
  def device_ids(self) -> tuple[str, ...]:
    return tuple(self.data)

  @property
  def statuses(self) -> Mapping[str, AirConditionerStatus]:
    return self.data
