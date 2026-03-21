from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
  ConfigEntryAuthFailed,
  ConfigEntryNotReady,
)

from .const import (
  CONF_FAMILY_ID,
  CONF_INTERNATIONAL_CODE,
  CONF_PHONE_NUMBER,
  DOMAIN,
)
from .client_lib import SuningDependencyError, load_client_lib
from .coordinator import SuningDataUpdateCoordinator

PLATFORMS: tuple[Platform, ...] = (Platform.CLIMATE,)


@dataclass(slots=True)
class SuningRuntimeData:
  client: object
  coordinator: SuningDataUpdateCoordinator


type SuningConfigEntry = ConfigEntry[SuningRuntimeData]


def session_state_path(
  hass: HomeAssistant,
  international_code: str,
  phone_number: str,
) -> Path:
  return Path(
    hass.config.path(
      ".storage",
      f"{DOMAIN}_{international_code}_{phone_number}.json",
    )
  )


async def async_setup_entry(hass: HomeAssistant, entry: SuningConfigEntry) -> bool:
  phone_number = entry.data[CONF_PHONE_NUMBER]
  international_code = entry.data[CONF_INTERNATIONAL_CODE]
  try:
    client_lib = load_client_lib()
  except SuningDependencyError as error:
    raise ConfigEntryNotReady(str(error)) from error
  client = client_lib.SuningSmartHomeClient(
    state_path=session_state_path(hass, international_code, phone_number),
  )
  client.state.phone_number = phone_number
  client.state.international_code = international_code

  coordinator = SuningDataUpdateCoordinator(
    hass=hass,
    config_entry=entry,
    client=client,
    family_id=entry.data[CONF_FAMILY_ID],
  )
  try:
    await coordinator.async_config_entry_first_refresh()
  except client_lib.AuthenticationError as error:
    raise ConfigEntryAuthFailed(str(error)) from error
  except (client_lib.SuningError, requests.RequestException) as error:
    raise ConfigEntryNotReady(str(error)) from error

  entry.runtime_data = SuningRuntimeData(client=client, coordinator=coordinator)
  await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
  return True


async def async_unload_entry(hass: HomeAssistant, entry: SuningConfigEntry) -> bool:
  return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
