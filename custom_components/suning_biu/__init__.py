from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from suning_biu_ha import AuthenticationError, SuningError, SuningSmartHomeClient

from .const import (
  CONF_FAMILY_ID,
  CONF_HAR_PATH,
  CONF_INTERNATIONAL_CODE,
  CONF_PHONE_NUMBER,
  DOMAIN,
)
from .coordinator import SuningDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (Platform.CLIMATE,)


@dataclass(slots=True)
class SuningRuntimeData:
  client: SuningSmartHomeClient
  coordinator: SuningDataUpdateCoordinator


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
  phone_number = entry.data[CONF_PHONE_NUMBER]
  international_code = entry.data[CONF_INTERNATIONAL_CODE]
  client = SuningSmartHomeClient(
    state_path=session_state_path(hass, international_code, phone_number),
    har_path=entry.data[CONF_HAR_PATH],
  )
  client.state.phone_number = phone_number
  client.state.international_code = international_code

  coordinator = SuningDataUpdateCoordinator(
    hass=hass,
    client=client,
    family_id=entry.data[CONF_FAMILY_ID],
  )
  try:
    await coordinator.async_config_entry_first_refresh()
  except AuthenticationError as error:
    raise ConfigEntryAuthFailed(str(error)) from error
  except SuningError as error:
    raise ConfigEntryNotReady(str(error)) from error
  except Exception as error:  # noqa: BLE001
    _LOGGER.exception("Unexpected error while setting up Suning Biu")
    raise ConfigEntryNotReady(str(error)) from error

  entry.runtime_data = SuningRuntimeData(client=client, coordinator=coordinator)
  await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
  return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
  unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
  if unload_ok:
    entry.runtime_data = None
  return unload_ok
