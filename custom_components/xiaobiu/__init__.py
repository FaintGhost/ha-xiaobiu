from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import logging
from pathlib import Path

import requests
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import ServiceCall
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
  ConfigEntryAuthFailed,
  ConfigEntryNotReady,
)

from .client_lib import SuningDependencyError, load_client_lib
from .const import (
  CONF_FAMILY_ID,
  CONF_INTERNATIONAL_CODE,
  CONF_PHONE_NUMBER,
  DOMAIN,
)
from .coordinator import SuningDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (Platform.CLIMATE,)

SERVICE_SET_TIMER = "set_timer"
ATTR_HOUR = "hour"
ATTR_MINUTE = "minute"
ATTR_WEEKDAYS = "weekdays"
ATTR_POWER_ON = "power_on"
ATTR_ENABLED = "enabled"
ATTR_NAME = "name"

_WEEKDAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _weekday_flags(selected: list[str] | None) -> list[bool]:
  """An empty selection means every day, matching the app's default."""

  if not selected:
    return [True] * 7
  chosen = {str(day).lower()[:3] for day in selected}
  return [day in chosen for day in _WEEKDAY_ORDER]


async def _async_handle_set_timer(hass: HomeAssistant, call) -> None:
  """Forward a ``xiaobiu.set_timer`` call to the Suning cloud."""

  from homeassistant.helpers import entity_registry as er

  entity_ids = call.data.get("entity_id") or []
  if isinstance(entity_ids, str):
    entity_ids = [entity_ids]
  if not entity_ids:
    raise ValueError("xiaobiu.set_timer 需要指定一个 climate 实体")

  registry = er.async_get(hass)
  weekdays = _weekday_flags(call.data.get(ATTR_WEEKDAYS))

  for entity_id in entity_ids:
    registry_entry = registry.async_get(entity_id)
    if registry_entry is None or not registry_entry.unique_id:
      raise ValueError(f"找不到实体 {entity_id} 的注册信息")
    entry_id, _, device_id = registry_entry.unique_id.partition("_")
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
      raise ValueError(f"{entity_id} 不属于 xiaobiu 集成")
    runtime: SuningRuntimeData = entry.runtime_data
    client = runtime.client
    await hass.async_add_executor_job(
      partial(
        client.set_device_timer,
        entry.data[CONF_FAMILY_ID],
        device_id,
        hour=int(call.data[ATTR_HOUR]),
        minute=int(call.data[ATTR_MINUTE]),
        weekdays=weekdays,
        power_on=bool(call.data.get(ATTR_POWER_ON, True)),
        enabled=bool(call.data.get(ATTR_ENABLED, True)),
        name=call.data.get(ATTR_NAME),
      )
    )
    await runtime.coordinator.async_request_refresh()


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
  async def handle_set_timer(call) -> None:
    await _async_handle_set_timer(hass, call)

  hass.services.async_register(
    DOMAIN,
    SERVICE_SET_TIMER,
    handle_set_timer,
    schema=vol.Schema(
      {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(ATTR_HOUR): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Required(ATTR_MINUTE): vol.All(
          vol.Coerce(int), vol.Range(min=0, max=59)
        ),
        vol.Optional(ATTR_WEEKDAYS): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_POWER_ON, default=True): cv.boolean,
        vol.Optional(ATTR_ENABLED, default=True): cv.boolean,
        vol.Optional(ATTR_NAME): cv.string,
      }
    ),
  )
  return True


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
  client = await hass.async_add_executor_job(
    partial(
      client_lib.SuningSmartHomeClient,
      state_path=session_state_path(hass, international_code, phone_number),
    ),
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

  await coordinator.async_load_capabilities()

  entry.runtime_data = SuningRuntimeData(client=client, coordinator=coordinator)
  _LOGGER.info(
    "xiaobiu: setup complete for %s, found %d device(s): %s",
    phone_number,
    len(coordinator.device_ids),
    coordinator.device_ids,
  )
  await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
  _LOGGER.info(
    "xiaobiu: forwarded setup to platforms %s for %s",
    PLATFORMS, phone_number,
  )
  return True


async def async_unload_entry(hass: HomeAssistant, entry: SuningConfigEntry) -> bool:
  return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
