from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from homeassistant import config_entries
from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError

from custom_components.suning_biu import async_setup_entry, resolve_har_path
from custom_components.suning_biu.client_lib import SuningDependencyError, load_client_lib
from custom_components.suning_biu.climate import SuningClimateEntity, async_setup_entry as climate_async_setup_entry
from custom_components.suning_biu.config_flow import SuningConfigFlow
from custom_components.suning_biu.const import (
  CONF_FAMILY_ID,
  CONF_FAMILY_NAME,
  CONF_HAR_PATH,
  CONF_INTERNATIONAL_CODE,
  CONF_PHONE_NUMBER,
  DOMAIN,
)
from custom_components.suning_biu.coordinator import SuningDataUpdateCoordinator


@dataclass(slots=True)
class FakeConfig:
  config_dir: str

  def path(self, *parts: str) -> str:
    return str(Path(self.config_dir, *parts))


@dataclass(slots=True)
class FakeConfigEntry:
  data: dict[str, Any]
  entry_id: str = "entry-1"
  runtime_data: Any = None

  def async_on_unload(self, _callback: Any) -> None:
    return None


@dataclass(slots=True)
class FakeHassForPath:
  config: FakeConfig


class FakeConfigEntriesManager:
  def __init__(self) -> None:
    self.forwarded: list[tuple[Any, tuple[Any, ...]]] = []

  async def async_forward_entry_setups(self, entry: Any, platforms: tuple[Any, ...]) -> None:
    self.forwarded.append((entry, platforms))

  async def async_unload_platforms(self, entry: Any, platforms: tuple[Any, ...]) -> bool:
    self.forwarded.append((entry, platforms))
    return True


def test_resolve_har_path_requires_existing_file_under_config_dir(tmp_path: Path) -> None:
  hass = FakeHassForPath(config=FakeConfig(config_dir=str(tmp_path)))
  har_path = tmp_path / "captures" / "devices.har"
  har_path.parent.mkdir(parents=True)
  har_path.write_text("{}", encoding="utf-8")

  assert resolve_har_path(hass, "captures/devices.har") == har_path.resolve()

  with pytest.raises(ValueError, match="must exist"):
    resolve_har_path(hass, "captures/missing.har")

  outside_path = tmp_path.parent / "outside.har"
  outside_path.write_text("{}", encoding="utf-8")
  with pytest.raises(ValueError, match="inside the Home Assistant config directory"):
    resolve_har_path(hass, str(outside_path))


def test_load_client_lib_wraps_runtime_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(
    "custom_components.suning_biu.client_lib._load_client_lib",
    lambda: (_ for _ in ()).throw(ModuleNotFoundError("boom")),
  )

  with pytest.raises(SuningDependencyError, match="runtime dependency is unavailable"):
    load_client_lib()


@pytest.mark.asyncio
async def test_async_setup_entry_rejects_missing_har_with_config_entry_error(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  hass = HomeAssistant(str(tmp_path))
  hass.config_entries = FakeConfigEntriesManager()
  entry = FakeConfigEntry(
    data={
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
      CONF_HAR_PATH: "captures/missing.har",
      CONF_FAMILY_ID: "37790",
    }
  )

  monkeypatch.setattr(
    "custom_components.suning_biu.load_client_lib",
    lambda: SimpleNamespace(
      SuningSmartHomeClient=object,
      AuthenticationError=RuntimeError,
      SuningError=RuntimeError,
    ),
  )

  with pytest.raises(ConfigEntryError, match="HAR file must exist"):
    await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_coordinator_raises_config_entry_auth_failed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
  class AuthenticationError(Exception):
    pass

  class FakeClient:
    def keep_alive(self) -> None:
      raise AuthenticationError("session expired")

    def list_air_conditioner_statuses(self, family_id: str) -> list[object]:
      raise AssertionError(f"should not fetch devices for {family_id}")

  monkeypatch.setattr(
    "custom_components.suning_biu.coordinator.load_client_lib",
    lambda: SimpleNamespace(
      AuthenticationError=AuthenticationError,
      SuningError=RuntimeError,
    ),
  )

  coordinator = SuningDataUpdateCoordinator(
    hass=HomeAssistant(str(tmp_path)),
    config_entry=FakeConfigEntry(data={}),
    client=FakeClient(),
    family_id="37790",
  )

  with pytest.raises(ConfigEntryAuthFailed, match="session expired"):
    await coordinator._async_update_data()  # noqa: SLF001


@pytest.mark.asyncio
async def test_reauth_sms_code_step_updates_existing_entry(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  class SuningError(Exception):
    pass

  class FakeClient:
    def __init__(self) -> None:
      self.login_calls: list[tuple[str, str, str]] = []
      self.keep_alive_called = False

    def login_with_sms_code(
      self,
      *,
      phone_number: str,
      sms_code: str,
      international_code: str,
    ) -> None:
      self.login_calls.append((phone_number, sms_code, international_code))

    def keep_alive(self) -> None:
      self.keep_alive_called = True

  fake_client = FakeClient()
  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_REAUTH}
  flow._client = fake_client
  flow._phone_number = "13800000000"
  flow._international_code = "0086"

  reauth_entry = FakeConfigEntry(
    data={
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
      CONF_HAR_PATH: "captures/devices.har",
      CONF_FAMILY_ID: "37790",
    }
  )

  monkeypatch.setattr(
    "custom_components.suning_biu.config_flow.load_client_lib",
    lambda: SimpleNamespace(SuningError=SuningError),
  )
  monkeypatch.setattr(flow, "_get_reauth_entry", lambda: reauth_entry)
  monkeypatch.setattr(
    flow,
    "async_update_reload_and_abort",
    lambda entry, **kwargs: {"type": "abort", "reason": "reauth_successful", "entry_id": entry.entry_id},
  )

  result = await flow.async_step_sms_code({"sms_code": "123456"})

  assert result == {"type": "abort", "reason": "reauth_successful", "entry_id": "entry-1"}
  assert fake_client.login_calls == [("13800000000", "123456", "0086")]
  assert fake_client.keep_alive_called is True


@pytest.mark.asyncio
async def test_reconfigure_step_updates_har_path(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  captures_dir = tmp_path / "captures"
  captures_dir.mkdir()
  har_path = captures_dir / "devices.har"
  har_path.write_text("{}", encoding="utf-8")

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_RECONFIGURE}
  reconfigure_entry = FakeConfigEntry(
    data={
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
      CONF_HAR_PATH: "captures/old.har",
      CONF_FAMILY_ID: "37790",
      CONF_FAMILY_NAME: "我的家",
    }
  )

  monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: reconfigure_entry)
  monkeypatch.setattr(
    flow,
    "async_update_reload_and_abort",
    lambda entry, **kwargs: {"type": "abort", "data_updates": kwargs["data_updates"], "entry_id": entry.entry_id},
  )

  result = await flow.async_step_reconfigure({CONF_HAR_PATH: "captures/devices.har"})

  assert result == {
    "type": "abort",
    "data_updates": {CONF_HAR_PATH: "captures/devices.har"},
    "entry_id": "entry-1",
  }


def test_climate_entity_exposes_expected_state() -> None:
  status = SimpleNamespace(
    device_id="ac-1",
    name="卧室空调",
    model="KFR-35GW",
    group_name="卧室",
    available=True,
    current_temperature=26.0,
    target_temperature=24.0,
    family_id="37790",
    group_id="group-1",
    summary="在线",
    device_record_time="2026-03-20T00:00:00Z",
    refresh_time="2026-03-20T00:05:00Z",
    mode_raw="3",
    fan_mode_raw="2",
    online=True,
    ha_climate_preview=SimpleNamespace(hvac_mode="off"),
  )
  coordinator = SimpleNamespace(status_for=lambda _device_id: status)
  entry = FakeConfigEntry(data={}, entry_id="entry-1")

  entity = SuningClimateEntity(
    coordinator=coordinator,
    entry=entry,
    device_id="ac-1",
  )

  assert entity.available is True
  assert entity.hvac_modes == [HVACMode.OFF]
  assert entity.hvac_mode == HVACMode.OFF
  assert entity.current_temperature == 26.0
  assert entity.target_temperature == 24.0
  assert entity.device_info["identifiers"] == {(DOMAIN, "ac-1")}
  assert entity.extra_state_attributes[CONF_FAMILY_ID] == "37790"


@pytest.mark.asyncio
async def test_climate_async_setup_entry_adds_one_entity_per_device_id(tmp_path: Path) -> None:
  captured_entities: list[Any] = []
  coordinator = SimpleNamespace(device_ids=("ac-1", "ac-2"))
  entry = FakeConfigEntry(
    data={},
    runtime_data=SimpleNamespace(coordinator=coordinator),
    entry_id="entry-1",
  )

  await climate_async_setup_entry(
    HomeAssistant(str(tmp_path)),
    entry,
    lambda entities: captured_entities.extend(list(entities)),
  )

  assert [entity._device_id for entity in captured_entities] == ["ac-1", "ac-2"]  # noqa: SLF001


def test_strings_json_includes_reauth_and_reconfigure_steps() -> None:
  strings_path = Path("custom_components/suning_biu/strings.json")
  payload = json.loads(strings_path.read_text(encoding="utf-8"))

  assert "reauth_confirm" in payload["config"]["step"]
  assert "reconfigure" in payload["config"]["step"]
  assert "reauth_successful" in payload["config"]["abort"]
  assert "reconfigure_successful" in payload["config"]["abort"]
