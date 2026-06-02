from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from homeassistant import config_entries
from homeassistant.components.http import KEY_HASS
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import (
  SWING_HORIZONTAL_OFF,
  SWING_HORIZONTAL_ON,
  SWING_OFF,
  SWING_ON,
  HVACAction,
  HVACMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from custom_components.xiaobiu import async_setup_entry
from custom_components.xiaobiu.client_lib import SuningDependencyError, load_client_lib
from custom_components.xiaobiu.climate import SuningClimateEntity, async_setup_entry as climate_async_setup_entry
from custom_components.xiaobiu.config_flow import SuningConfigFlow
from custom_components.xiaobiu.const import (
  CONF_FAMILY_ID,
  CONF_FAMILY_NAME,
  CONF_INTERNATIONAL_CODE,
  CONF_PHONE_NUMBER,
  DOMAIN,
  PRESET_AUX_HEAT,
  PRESET_ECO,
  PRESET_FRESH_AIR,
  PRESET_NONE,
)
from custom_components.xiaobiu.iar_external_view import (
  IARCaptchaResult,
  SuningIARCaptchaView,
  async_create_iar_captcha_session,
  async_get_iar_captcha_session,
)
from custom_components.xiaobiu.coordinator import SuningDataUpdateCoordinator


@dataclass(slots=True)
class FakeConfigEntry:
  data: dict[str, Any]
  entry_id: str = "entry-1"
  unique_id: str | None = "0086:13800000000"
  title: str = "我的家"
  runtime_data: Any = None
  state: Any = config_entries.ConfigEntryState.SETUP_IN_PROGRESS

  def async_on_unload(self, _callback: Any) -> None:
    return None


class FakeConfigEntriesManager:
  def __init__(self) -> None:
    self.forwarded: list[tuple[Any, tuple[Any, ...]]] = []

  async def async_forward_entry_setups(self, entry: Any, platforms: tuple[Any, ...]) -> None:
    self.forwarded.append((entry, platforms))

  async def async_unload_platforms(self, entry: Any, platforms: tuple[Any, ...]) -> bool:
    self.forwarded.append((entry, platforms))
    return True


class FakeHTTP:
  def __init__(self) -> None:
    self.views: list[Any] = []

  def register_view(self, view: Any) -> None:
    self.views.append(view)


class FakeHass:
  """Minimal HomeAssistant stand-in for entity unit tests.

  CoordinatorEntity reads ``self.hass`` in async setters to schedule
  blocking I/O via ``async_add_executor_job``. Real HA injects this in
  :meth:`async_added_to_hass`; tests bypass that by setting it directly.
  """

  async def async_add_executor_job(self, fn: Any, *args: Any) -> Any:
    return fn(*args)


@dataclass(slots=True)
class FakeCapabilities:
  hvac_modes: tuple[str, ...] = ("off", "cool", "heat", "auto", "dry")
  fan_modes: tuple[str, ...] = ("auto", "low", "medium", "high", "turbo")
  swing_modes: tuple[str, ...] = ("off", "vertical", "horizontal", "both")
  preset_modes: tuple[str, ...] = ("none", "eco", "fresh_air", "aux_heat")
  supports_vertical_swing: bool = True
  supports_horizontal_swing: bool = True
  supports_eco: bool = True
  supports_fresh_air: bool = True
  supports_aux_heat: bool = True
  supports_target_temperature: bool = True
  min_target_temperature: float = 16.0
  max_target_temperature: float = 32.0


def _make_climate_status(
  *,
  device_id: str = "ac-1",
  family_id: str = "37790",
  name: str = "卧室空调",
  model: str = "KFR-35GW",
  group_name: str = "卧室",
  group_id: str = "group-1",
  available: bool = True,
  online: bool = True,
  current_temperature: float | None = 26.0,
  target_temperature: float | None = 24.0,
  power_on: bool | None = True,
  hvac_mode: Any = None,
  hvac_action: Any = None,
  mode_raw: str = "3",
  fan_mode: str = "medium",
  fan_mode_raw: str = "2",
  swing_vertical: bool = False,
  swing_horizontal: bool = False,
  eco_enabled: bool = False,
  fresh_air_enabled: bool = False,
  electric_heating_enabled: bool = False,
) -> SimpleNamespace:
  if hvac_mode is None:
    hvac_mode = SimpleNamespace(value="cool", name="COOL")
  if hvac_action is None:
    hvac_action = SimpleNamespace(value="cooling", name="COOLING")
  return SimpleNamespace(
    device_id=device_id,
    name=name,
    model=model,
    group_name=group_name,
    group_id=group_id,
    family_id=family_id,
    category_id="0002",
    available=available,
    online=online,
    current_temperature=current_temperature,
    target_temperature=target_temperature,
    power_on=power_on,
    hvac_mode=hvac_mode,
    hvac_action=hvac_action,
    mode_raw=mode_raw,
    fan_mode=fan_mode,
    fan_mode_raw=fan_mode_raw,
    swing_vertical=swing_vertical,
    swing_horizontal=swing_horizontal,
    eco_enabled=eco_enabled,
    fresh_air_enabled=fresh_air_enabled,
    electric_heating_enabled=electric_heating_enabled,
    summary="在线",
    device_record_time="2026-03-20T00:00:00Z",
    refresh_time="2026-03-20T00:05:00Z",
    raw_status={},
    raw_device={},
  )


def _make_climate_coordinator(
  *,
  status: Any | None = None,
  capabilities: Any | None = None,
  client: Any = None,
) -> Any:
  status = status if status is not None else _make_climate_status()

  async def _async_request_refresh() -> None:
    return None

  return SimpleNamespace(
    status_for=lambda _device_id: status,
    capabilities_for=lambda _device_id: capabilities,
    client=client or SimpleNamespace(),
    device_ids=("ac-1",),
    async_request_refresh=_async_request_refresh,
  )


def _attach_hass(entity: SuningClimateEntity) -> SuningClimateEntity:
  entity.hass = FakeHass()  # type: ignore[assignment]
  return entity


def test_load_client_lib_wraps_runtime_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(
    "custom_components.xiaobiu.client_lib._load_client_lib",
    lambda: (_ for _ in ()).throw(ModuleNotFoundError("boom")),
  )

  with pytest.raises(SuningDependencyError, match="runtime dependency is unavailable"):
    load_client_lib()


def test_load_client_lib_uses_pypi_package() -> None:
  client_lib = load_client_lib()

  assert client_lib.SuningSmartHomeClient.__module__.startswith("xiaobiu")
  assert client_lib.LocalCaptchaBridge.__module__.startswith("xiaobiu")


@pytest.mark.asyncio
async def test_async_setup_entry_ignores_legacy_har_path_and_initializes_client(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  init_calls: list[dict[str, Any]] = []

  class FakeClient:
    def __init__(self, *, state_path: Path, har_path: str | None = None) -> None:
      init_calls.append({"state_path": state_path, "har_path": har_path})
      self.state = SimpleNamespace(phone_number=None, international_code=None)

    def keep_alive(self) -> None:
      return None

    def list_air_conditioner_statuses(self, family_id: str) -> list[object]:
      assert family_id == "37790"
      return [SimpleNamespace(device_id="ac-1")]

    def get_device_panel_template(self, family_id: str, device_id: str) -> object:
      return None

  hass = HomeAssistant(str(tmp_path))
  hass.config_entries = FakeConfigEntriesManager()
  entry = FakeConfigEntry(
    data={
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
      "har_path": "captures/missing.har",
      CONF_FAMILY_ID: "37790",
    }
  )

  monkeypatch.setattr(
    "custom_components.xiaobiu.load_client_lib",
    lambda: SimpleNamespace(
      SuningSmartHomeClient=FakeClient,
      AuthenticationError=RuntimeError,
      SuningError=RuntimeError,
    ),
  )

  result = await async_setup_entry(hass, entry)

  assert result is True
  assert init_calls[0]["har_path"] is None
  assert init_calls[0]["state_path"] == tmp_path / ".storage" / "xiaobiu_0086_13800000000.json"
  assert entry.runtime_data.client.state.phone_number == "13800000000"
  assert entry.runtime_data.client.state.international_code == "0086"


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
    "custom_components.xiaobiu.coordinator.load_client_lib",
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
async def test_user_step_form_no_longer_contains_har_field(tmp_path: Path) -> None:
  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_USER}

  result = await flow.async_step_user()

  schema = result["data_schema"].schema
  field_names = {field.schema for field in schema}
  assert field_names == {CONF_PHONE_NUMBER, CONF_INTERNATIONAL_CODE}


@pytest.mark.asyncio
async def test_user_step_clears_stale_sms_login_state_before_starting_new_flow(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  class CaptchaRequiredError(Exception):
    def __init__(self, risk_type: str) -> None:
      super().__init__(risk_type)
      self.risk_type = risk_type

  created_clients: list[Any] = []

  class FakeClient:
    def __init__(self, *, state_path: Path, load_state: bool = True) -> None:
      self.state_path = state_path
      self.load_state = load_state
      self.state = SimpleNamespace(
        phone_number="13800000000",
        international_code="0086",
        risk_type="isIarVerifyCode",
        sms_ticket="stale-sms-ticket",
        login_ticket="stale-login-ticket",
      )
      self.session = SimpleNamespace(cookies=["stale-cookie"] if load_state else [])
      self.risk_context_script_urls = []
      self.reset_calls = 0
      created_clients.append(self)

    def reset_sms_login_state(self) -> None:
      self.reset_calls += 1
      self.state.risk_type = None
      self.state.sms_ticket = None
      self.state.login_ticket = None

    def send_sms_code(
      self,
      phone_number: str,
      *,
      international_code: str | None = None,
      captcha: Any | None = None,
    ) -> None:
      assert phone_number == "13800000000"
      assert international_code == "0086"
      assert captcha is None
      assert self.load_state is False
      assert self.session.cookies == []
      assert self.state.risk_type is None
      assert self.state.sms_ticket is None
      assert self.state.login_ticket is None
      raise CaptchaRequiredError("isIarVerifyCode")

    def request_iar_verify_code_ticket(self, _phone_number: str) -> str:
      return "ticket-123"

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.hass.http = FakeHTTP()
  flow.context = {"source": config_entries.SOURCE_USER}
  flow.flow_id = "flow-123"

  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(
      SuningError=RuntimeError,
      CaptchaRequiredError=CaptchaRequiredError,
      CaptchaSolution=lambda **kwargs: SimpleNamespace(**kwargs),
      SuningSmartHomeClient=FakeClient,
    ),
  )
  async def fake_async_set_unique_id(*_args: Any, **_kwargs: Any) -> None:
    return None

  monkeypatch.setattr(flow, "async_set_unique_id", fake_async_set_unique_id)
  monkeypatch.setattr(flow, "_abort_if_unique_id_configured", lambda: None)
  monkeypatch.setattr(flow, "_abort_existing_user_flows", lambda _unique_id: None)

  result = await flow.async_step_user(
    {
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
    }
  )

  assert result["type"] == "external"
  assert result["step_id"] == "captcha"
  assert len(created_clients) == 1
  assert created_clients[0].load_state is False
  assert created_clients[0].reset_calls == 1
  assert created_clients[0].state_path == (
    tmp_path / ".storage" / "xiaobiu_0086_13800000000.json"
  )


@pytest.mark.asyncio
async def test_user_step_restarts_same_phone_flow_and_clears_old_iar_session(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.hass.http = FakeHTTP()
  flow.context = {"source": config_entries.SOURCE_USER}
  flow.flow_id = "flow-new"
  aborted_flow_ids: list[str] = []
  unique_id = "0086:13800000000"
  old_progress = [
    {
      "flow_id": "flow-old",
      "context": {
        "source": config_entries.SOURCE_USER,
        "unique_id": unique_id,
      },
    }
  ]

  def fake_async_progress_by_handler(
    handler: str,
    include_uninitialized: bool = False,
    match_context: dict[str, Any] | None = None,
  ) -> list[dict[str, Any]]:
    assert handler == DOMAIN
    if include_uninitialized and match_context == {
      "source": config_entries.SOURCE_USER,
      "unique_id": unique_id,
    }:
      return old_progress
    return []

  async_create_iar_captcha_session(
    flow.hass,
    flow_id="flow-old",
    ticket="ticket-123",
  )

  flow.hass.config_entries = SimpleNamespace(
    flow=SimpleNamespace(
      async_progress_by_handler=fake_async_progress_by_handler,
      async_abort=lambda flow_id: aborted_flow_ids.append(flow_id),
    )
  )

  async def fake_async_set_unique_id(unique_id: str, raise_on_progress: bool = True) -> None:
    flow.context["unique_id"] = unique_id

  monkeypatch.setattr(flow, "async_set_unique_id", fake_async_set_unique_id)
  monkeypatch.setattr(
    flow,
    "_abort_if_unique_id_configured",
    lambda: None,
  )
  async def _fake_async_initialize_client() -> tuple[Any, str | None]:
    return (SimpleNamespace(), None)

  monkeypatch.setattr(
    flow,
    "_async_initialize_client",
    _fake_async_initialize_client,
  )

  async def fake_async_send_sms(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return {"type": "form", "step_id": "sms_code"}

  monkeypatch.setattr(flow, "_async_send_sms", fake_async_send_sms)

  result = await flow.async_step_user(
    {
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
    }
  )

  assert result == {"type": "form", "step_id": "sms_code"}
  assert flow.context["unique_id"] == unique_id
  assert aborted_flow_ids == ["flow-old"]
  assert async_get_iar_captcha_session(flow.hass, "flow-old") is None


@pytest.mark.asyncio
async def test_family_step_creates_entry_without_har_path(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  class SuningError(Exception):
    pass

  class FakeClient:
    def list_air_conditioner_statuses(self, family_id: str) -> list[object]:
      assert family_id == "37790"
      return [object()]

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_USER}
  flow._client = FakeClient()
  flow._phone_number = "13800000000"
  flow._international_code = "0086"
  flow._families = [SimpleNamespace(family_id="37790", name="我的家")]

  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(SuningError=SuningError),
  )

  result = await flow.async_step_family({CONF_FAMILY_ID: "37790"})

  assert result["type"] == "create_entry"
  assert result["data"] == {
    CONF_PHONE_NUMBER: "13800000000",
    CONF_INTERNATIONAL_CODE: "0086",
    CONF_FAMILY_ID: "37790",
    CONF_FAMILY_NAME: "我的家",
  }


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
      CONF_FAMILY_ID: "37790",
    }
  )

  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
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
async def test_reconfigure_step_loads_family_list_from_saved_session(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  init_calls: list[dict[str, Any]] = []

  class AuthenticationError(Exception):
    pass

  class SuningError(Exception):
    pass

  class FakeClient:
    def __init__(self, *, state_path: Path, load_state: bool = True) -> None:
      init_calls.append({"state_path": state_path, "load_state": load_state})
      self.state = SimpleNamespace(phone_number=None, international_code=None)

    def list_family_infos(self) -> list[object]:
      return [
        SimpleNamespace(family_id="37790", name="我的家"),
        SimpleNamespace(family_id="48880", name="客厅"),
      ]

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_RECONFIGURE, "entry_id": "entry-1"}

  config_entry = FakeConfigEntry(
    data={
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
      CONF_FAMILY_ID: "37790",
      CONF_FAMILY_NAME: "我的家",
    }
  )

  monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: config_entry)
  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(
      AuthenticationError=AuthenticationError,
      SuningError=SuningError,
      SuningSmartHomeClient=FakeClient,
    ),
  )

  result = await flow.async_step_reconfigure({})

  assert result["type"] == "form"
  assert result["step_id"] == "family"
  assert init_calls == [
    {
      "state_path": tmp_path / ".storage" / "xiaobiu_0086_13800000000.json",
      "load_state": True,
    }
  ]


@pytest.mark.asyncio
async def test_reconfigure_step_falls_back_to_sms_when_session_expired(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  class AuthenticationError(Exception):
    pass

  class SuningError(Exception):
    pass

  class FakeClient:
    def __init__(self, *, state_path: Path, load_state: bool = True) -> None:
      self.state = SimpleNamespace(phone_number=None, international_code=None)

    def list_family_infos(self) -> list[object]:
      raise AuthenticationError("session expired")

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_RECONFIGURE, "entry_id": "entry-1"}

  config_entry = FakeConfigEntry(
    data={
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
      CONF_FAMILY_ID: "37790",
      CONF_FAMILY_NAME: "我的家",
    }
  )

  monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: config_entry)
  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(
      AuthenticationError=AuthenticationError,
      SuningError=SuningError,
      SuningSmartHomeClient=FakeClient,
    ),
  )

  result = await flow.async_step_reconfigure({})

  assert result["type"] == "form"
  assert result["step_id"] == "reconfigure_auth"


@pytest.mark.asyncio
async def test_reconfigure_family_step_updates_existing_entry(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  class SuningError(Exception):
    pass

  class FakeClient:
    def list_air_conditioner_statuses(self, family_id: str) -> list[object]:
      assert family_id == "48880"
      return [object()]

  updated_entries: list[dict[str, Any]] = []
  config_entry = FakeConfigEntry(
    data={
      CONF_PHONE_NUMBER: "13800000000",
      CONF_INTERNATIONAL_CODE: "0086",
      CONF_FAMILY_ID: "37790",
      CONF_FAMILY_NAME: "我的家",
    }
  )

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.hass.config_entries = SimpleNamespace(
    async_update_entry=lambda entry, **kwargs: updated_entries.append(
      {"entry": entry, **kwargs}
    )
  )
  flow.context = {"source": config_entries.SOURCE_RECONFIGURE, "entry_id": "entry-1"}
  flow._client = FakeClient()
  flow._phone_number = "13800000000"
  flow._international_code = "0086"
  flow._families = [
    SimpleNamespace(family_id="37790", name="我的家"),
    SimpleNamespace(family_id="48880", name="客厅"),
  ]

  monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: config_entry)
  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(SuningError=SuningError),
  )
  monkeypatch.setattr(
    flow,
    "async_update_reload_and_abort",
    lambda entry, **kwargs: {"type": "abort", "entry": entry, **kwargs},
  )

  result = await flow.async_step_family({CONF_FAMILY_ID: "48880"})

  assert result["type"] == "abort"
  assert result["reason"] == "reconfigure_successful"
  assert result["data_updates"] == {
    CONF_PHONE_NUMBER: "13800000000",
    CONF_INTERNATIONAL_CODE: "0086",
    CONF_FAMILY_ID: "48880",
    CONF_FAMILY_NAME: "客厅",
  }
  assert updated_entries == [
    {
      "entry": config_entry,
      "title": "客厅",
    }
  ]


@pytest.mark.asyncio
async def test_iar_captcha_step_updates_risk_context_before_retry(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  class SuningError(Exception):
    pass

  class CaptchaRequiredError(Exception):
    def __init__(self, risk_type: str) -> None:
      super().__init__(risk_type)
      self.risk_type = risk_type

  class FakeClient:
    def __init__(self) -> None:
      self.risk_context_script_urls = ["https://example.com/fp.js"]
      self.send_sms_calls: list[tuple[str | None, str | None, Any | None]] = []
      self.risk_updates: list[tuple[str | None, str | None]] = []
      self.request_iar_verify_code_ticket_calls = 0

    def send_sms_code(
      self,
      phone_number: str,
      *,
      international_code: str | None = None,
      captcha: Any | None = None,
    ) -> None:
      self.send_sms_calls.append(
        (
          getattr(self, "detect", None),
          getattr(self, "dfp_token", None),
          captcha,
        )
      )
      if captcha is None:
        raise CaptchaRequiredError("isIarVerifyCode")

    def request_iar_verify_code_ticket(self, _phone_number: str) -> str:
      self.request_iar_verify_code_ticket_calls += 1
      return "ticket-123"

    def update_risk_context(self, *, detect: str | None = None, dfp_token: str | None = None) -> None:
      self.detect = detect
      self.dfp_token = dfp_token
      self.risk_updates.append((detect, dfp_token))

  fake_client = FakeClient()
  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.hass.http = FakeHTTP()
  flow.context = {"source": config_entries.SOURCE_USER}
  flow.flow_id = "flow-123"
  flow._client = fake_client
  flow._phone_number = "13800000000"
  flow._international_code = "0086"

  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(
      SuningError=SuningError,
      CaptchaRequiredError=CaptchaRequiredError,
      CaptchaSolution=lambda **kwargs: SimpleNamespace(**kwargs),
    ),
  )
  async def fake_async_step_sms_code(*_args, **_kwargs: Any) -> dict[str, Any]:
    return {"type": "form", "step_id": "sms_code"}

  monkeypatch.setattr(flow, "async_step_sms_code", fake_async_step_sms_code)

  captcha_result = await flow._async_send_sms()  # noqa: SLF001
  assert captcha_result["type"] == "external"
  assert captcha_result["step_id"] == "captcha"
  assert captcha_result["url"].startswith(f"/api/{DOMAIN}/iar/flow-123/")
  session = async_get_iar_captcha_session(flow.hass, "flow-123")
  assert session is not None
  assert session.ticket == "ticket-123"
  assert session.script_urls == ["https://example.com/fp.js"]
  assert fake_client.request_iar_verify_code_ticket_calls == 1
  session.result = IARCaptchaResult(
    token="iar-token",
    detect="browser-detect",
    dfp_token="browser-dfp",
  )

  result = await flow.async_step_captcha()
  assert result["type"] == "external_done"
  assert result["step_id"] == "captcha_done"

  result = await flow.async_step_captcha_done()

  assert result == {"type": "form", "step_id": "sms_code"}
  assert fake_client.risk_updates == [("browser-detect", "browser-dfp")]
  assert len(fake_client.send_sms_calls) == 2
  assert fake_client.send_sms_calls[1][0:2] == ("browser-detect", "browser-dfp")
  assert fake_client.send_sms_calls[1][2].kind == "iar"
  assert fake_client.send_sms_calls[1][2].value == "iar-token"
  assert async_get_iar_captcha_session(flow.hass, "flow-123") is None


@pytest.mark.asyncio
async def test_iar_captcha_step_aborts_when_session_is_missing(tmp_path: Path) -> None:
  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_USER}
  flow.flow_id = "flow-123"
  flow._captcha_kind = "iar"

  result = await flow.async_step_captcha()

  assert result["type"] == "abort"
  assert result["reason"] == "captcha_session_expired"


@pytest.mark.asyncio
async def test_iar_captcha_done_aborts_when_risk_context_is_missing(tmp_path: Path) -> None:
  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.hass.http = FakeHTTP()
  flow.context = {"source": config_entries.SOURCE_USER}
  flow.flow_id = "flow-123"
  flow._captcha_kind = "iar"
  flow._client = SimpleNamespace()
  flow._phone_number = "13800000000"

  session = async_create_iar_captcha_session(
    flow.hass,
    flow_id="flow-123",
    ticket="ticket-123",
  )
  session.result = IARCaptchaResult(token="iar-token")

  result = await flow.async_step_captcha_done()

  assert result["type"] == "abort"
  assert result["reason"] == "captcha_risk_context_missing"
  assert async_get_iar_captcha_session(flow.hass, "flow-123") is None


@pytest.mark.asyncio
async def test_iar_captcha_done_handles_send_sms_error_without_dropping_session(
  monkeypatch: pytest.MonkeyPatch,
  caplog: pytest.LogCaptureFixture,
  tmp_path: Path,
) -> None:
  class SuningError(Exception):
    pass

  class FakeClient:
    def __init__(self) -> None:
      self.risk_updates: list[tuple[str | None, str | None]] = []

    def update_risk_context(self, *, detect: str | None = None, dfp_token: str | None = None) -> None:
      self.risk_updates.append((detect, dfp_token))

    def send_sms_code(
      self,
      phone_number: str,
      *,
      international_code: str | None = None,
      captcha: Any | None = None,
    ) -> None:
      assert phone_number == "13800000000"
      assert international_code == "0086"
      assert captcha is not None
      raise SuningError("send sms failed")

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.hass.http = FakeHTTP()
  flow.context = {"source": config_entries.SOURCE_USER}
  flow.flow_id = "flow-123"
  flow._captcha_kind = "iar"
  flow._client = FakeClient()
  flow._phone_number = "13800000000"
  flow._international_code = "0086"

  session = async_create_iar_captcha_session(
    flow.hass,
    flow_id="flow-123",
    ticket="ticket-123",
  )
  session.result = IARCaptchaResult(
    token="iar-token",
    detect="browser-detect",
    dfp_token="browser-dfp",
  )

  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(
      SuningError=SuningError,
      CaptchaRequiredError=type("CaptchaRequiredError", (Exception,), {}),
      CaptchaSolution=lambda **kwargs: SimpleNamespace(**kwargs),
    ),
  )

  with caplog.at_level(logging.ERROR, logger="custom_components.xiaobiu.config_flow"):
    result = await flow.async_step_captcha_done()

  assert result["type"] == "form"
  assert result["step_id"] == "user"
  assert result["errors"] == {"base": "cannot_connect"}
  assert async_get_iar_captcha_session(flow.hass, "flow-123") is not None
  assert flow._client.risk_updates == [("browser-detect", "browser-dfp")]
  assert "Failed to resume Suning SMS flow after IAR verification for flow flow-123" in caplog.text


@pytest.mark.asyncio
async def test_async_send_sms_logs_unsupported_risk_type(
  monkeypatch: pytest.MonkeyPatch,
  caplog: pytest.LogCaptureFixture,
  tmp_path: Path,
) -> None:
  class SuningError(Exception):
    pass

  class CaptchaRequiredError(Exception):
    def __init__(self, risk_type: str) -> None:
      super().__init__(risk_type)
      self.risk_type = risk_type

  class FakeClient:
    def send_sms_code(
      self,
      phone_number: str,
      *,
      international_code: str | None = None,
      captcha: Any | None = None,
    ) -> None:
      assert phone_number == "13800000000"
      assert international_code == "0086"
      assert captcha is None
      raise CaptchaRequiredError("isUnknownCaptcha")

  flow = SuningConfigFlow()
  flow.hass = HomeAssistant(str(tmp_path))
  flow.context = {"source": config_entries.SOURCE_USER}
  flow.flow_id = "flow-123"
  flow._client = FakeClient()
  flow._phone_number = "13800000000"
  flow._international_code = "0086"

  monkeypatch.setattr(
    "custom_components.xiaobiu.config_flow.load_client_lib",
    lambda: SimpleNamespace(
      SuningError=SuningError,
      CaptchaRequiredError=CaptchaRequiredError,
      CaptchaSolution=lambda **kwargs: SimpleNamespace(**kwargs),
    ),
  )

  with (
    caplog.at_level(logging.ERROR, logger="custom_components.xiaobiu.config_flow"),
    pytest.raises(SuningError, match="unsupported captcha risk type: isUnknownCaptcha"),
  ):
    await flow._async_send_sms()  # noqa: SLF001

  assert "Unsupported captcha risk type from Suning while sending SMS: isUnknownCaptcha" in caplog.text


@pytest.mark.asyncio
async def test_iar_captcha_view_serves_page_and_triggers_flow_resume(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  hass = HomeAssistant(str(tmp_path))
  hass.http = FakeHTTP()
  resumed_flows: list[str] = []
  created_tasks: list[Any] = []

  async def fake_async_configure(*, flow_id: str) -> None:
    resumed_flows.append(flow_id)

  monkeypatch.setattr(
    hass,
    "async_create_task",
    lambda coro, *args, **kwargs: created_tasks.append(coro),
  )
  hass.config_entries = SimpleNamespace(
    flow=SimpleNamespace(async_configure=fake_async_configure)
  )

  session = async_create_iar_captcha_session(
    hass,
    flow_id="flow-123",
    ticket="ticket-123",
    script_urls=["https://example.com/fp.js"],
  )

  class FakeRequest:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
      self.app = {KEY_HASS: hass}
      self._payload = payload or {}

    async def json(self) -> dict[str, Any]:
      return self._payload

  view = SuningIARCaptchaView()
  response = await view.get(FakeRequest(), flow_id="flow-123", nonce=session.nonce)
  body = response.body.decode("utf-8")
  assert response.status == 200
  assert "ticket-123" in body
  assert session.path in body
  assert "https://example.com/fp.js" in body
  assert "window.__CAPTCHA_PREPARE_URL__" not in body
  assert "window.__CAPTCHA_INITIAL_TICKET__" not in body

  post_response = await view.post(
    FakeRequest(
      {
        "token": "iar-token",
        "detect": "browser-detect",
        "dfpToken": "browser-dfp",
      }
    ),
    flow_id="flow-123",
    nonce=session.nonce,
  )
  assert post_response.status == 200
  assert session.result == IARCaptchaResult(
    token="iar-token",
    detect="browser-detect",
    dfp_token="browser-dfp",
  )
  assert len(created_tasks) == 1
  await created_tasks[0]
  assert resumed_flows == ["flow-123"]


@pytest.mark.asyncio
async def test_iar_captcha_view_rejects_missing_risk_context(tmp_path: Path) -> None:
  hass = HomeAssistant(str(tmp_path))
  hass.http = FakeHTTP()
  hass.config_entries = SimpleNamespace(flow=SimpleNamespace(async_configure=lambda **_kwargs: None))

  session = async_create_iar_captcha_session(
    hass,
    flow_id="flow-123",
    ticket="ticket-123",
  )

  class FakeRequest:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
      self.app = {KEY_HASS: hass}
      self._payload = payload or {}

    async def json(self) -> dict[str, Any]:
      return self._payload

  view = SuningIARCaptchaView()
  response = await view.post(
    FakeRequest({"token": "iar-token"}),
    flow_id="flow-123",
    nonce=session.nonce,
  )

  assert response.status == 400
  assert async_get_iar_captcha_session(hass, "flow-123") is not None


@pytest.mark.asyncio
async def test_iar_captcha_view_ignores_duplicate_success_callbacks(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  hass = HomeAssistant(str(tmp_path))
  hass.http = FakeHTTP()
  resumed_flows: list[str] = []
  created_tasks: list[Any] = []

  async def fake_async_configure(*, flow_id: str) -> None:
    resumed_flows.append(flow_id)

  monkeypatch.setattr(
    hass,
    "async_create_task",
    lambda coro, *args, **kwargs: created_tasks.append(coro),
  )
  hass.config_entries = SimpleNamespace(
    flow=SimpleNamespace(async_configure=fake_async_configure)
  )

  session = async_create_iar_captcha_session(
    hass,
    flow_id="flow-123",
    ticket="ticket-123",
  )

  class FakeRequest:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
      self.app = {KEY_HASS: hass}
      self._payload = payload or {}

    async def json(self) -> dict[str, Any]:
      return self._payload

  view = SuningIARCaptchaView()
  payload = {
    "token": "iar-token",
    "detect": "browser-detect",
    "dfpToken": "browser-dfp",
  }
  first_response = await view.post(
    FakeRequest(payload),
    flow_id="flow-123",
    nonce=session.nonce,
  )
  second_response = await view.post(
    FakeRequest(payload),
    flow_id="flow-123",
    nonce=session.nonce,
  )

  assert first_response.status == 200
  assert second_response.status == 200
  assert session.resume_requested is True
  assert len(created_tasks) == 1
  await created_tasks[0]
  assert resumed_flows == ["flow-123"]


def test_climate_entity_exposes_expected_state() -> None:
  status = _make_climate_status(
    hvac_mode=SimpleNamespace(value="cool", name="COOL"),
    hvac_action=SimpleNamespace(value="cooling", name="COOLING"),
  )
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities())
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-1"))

  assert entity.available is True
  assert entity.hvac_mode == HVACMode.COOL
  assert entity.hvac_action == HVACAction.COOLING
  assert HVACMode.COOL in entity.hvac_modes
  assert HVACMode.HEAT in entity.hvac_modes
  assert HVACMode.OFF in entity.hvac_modes
  assert entity.current_temperature == 26.0
  assert entity.target_temperature == 24.0
  assert entity.min_temp == 16.0
  assert entity.max_temp == 32.0
  assert entity.device_info["identifiers"] == {(DOMAIN, "ac-1")}
  assert entity.extra_state_attributes[CONF_FAMILY_ID] == "37790"
  assert entity.extra_state_attributes["hvac_mode"] == "cool"
  assert entity.extra_state_attributes["hvac_action"] == "cooling"
  assert entity.extra_state_attributes["capabilities_loaded"] is True
  assert (entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE) == ClimateEntityFeature.TARGET_TEMPERATURE
  assert (entity.supported_features & ClimateEntityFeature.FAN_MODE) == ClimateEntityFeature.FAN_MODE
  assert (entity.supported_features & ClimateEntityFeature.SWING_MODE) == ClimateEntityFeature.SWING_MODE
  assert (entity.supported_features & ClimateEntityFeature.SWING_HORIZONTAL_MODE) == ClimateEntityFeature.SWING_HORIZONTAL_MODE
  assert (entity.supported_features & ClimateEntityFeature.PRESET_MODE) == ClimateEntityFeature.PRESET_MODE


def test_climate_entity_exposes_dynamic_hvac_modes_from_capabilities() -> None:
  status = _make_climate_status()
  capabilities = FakeCapabilities(hvac_modes=("off", "cool", "dry"))
  coordinator = _make_climate_coordinator(status=status, capabilities=capabilities)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-1"))

  assert entity.hvac_modes == [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY]
  assert entity.fan_modes == ["auto", "low", "medium", "high", "turbo"]
  assert entity.fan_mode == "2"
  assert entity.swing_modes == [SWING_ON, SWING_OFF]
  assert entity.swing_mode == SWING_OFF
  assert entity.swing_horizontal_modes == [SWING_HORIZONTAL_ON, SWING_HORIZONTAL_OFF]
  assert entity.swing_horizontal_mode == SWING_HORIZONTAL_OFF
  assert entity.preset_modes == [PRESET_NONE, PRESET_ECO, PRESET_FRESH_AIR, PRESET_AUX_HEAT]
  assert entity.preset_mode == PRESET_NONE


def test_climate_entity_falls_back_to_off_when_capabilities_missing() -> None:
  status = _make_climate_status(power_on=True)
  coordinator = _make_climate_coordinator(status=status, capabilities=None)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-1"))

  assert entity.hvac_modes == [HVACMode.OFF]
  assert entity.hvac_mode is None
  assert entity.fan_modes is None
  assert entity.swing_modes is None
  assert entity.swing_horizontal_modes is None
  assert entity.preset_modes is None
  assert entity.preset_mode is None
  assert entity.supported_features == ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
  assert entity.extra_state_attributes["capabilities_loaded"] is False


def test_climate_entity_maps_status_hvac_mode_to_hvac_mode_enum() -> None:
  status = _make_climate_status(
    hvac_mode=SimpleNamespace(value="heat", name="HEAT"),
    hvac_action=SimpleNamespace(value="heating", name="HEATING"),
  )
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities())
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-1"))

  assert entity.hvac_mode == HVACMode.HEAT
  assert entity.hvac_action == HVACAction.HEATING


def test_climate_entity_unmapped_hvac_mode_falls_back_to_cool() -> None:
  status = _make_climate_status(
    power_on=True,
    hvac_mode=SimpleNamespace(value="quick", name="QUICK"),
  )
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities())
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-1"))

  assert entity.hvac_mode == HVACMode.COOL


@pytest.mark.asyncio
async def test_climate_turn_on_calls_client_with_family_and_device() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _turn_on(family_id: str, device_id: str) -> dict[str, Any]:
    captured["turn_on"] = (family_id, device_id)
    return {}

  client.turn_on = _turn_on  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_turn_on()

  assert captured["turn_on"] == ("42", "ac-9")


@pytest.mark.asyncio
async def test_climate_turn_off_calls_client_with_family_and_device() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _turn_off(family_id: str, device_id: str) -> dict[str, Any]:
    captured["turn_off"] = (family_id, device_id)
    return {}

  client.turn_off = _turn_off  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_turn_off()

  assert captured["turn_off"] == ("42", "ac-9")


@pytest.mark.asyncio
async def test_climate_set_hvac_mode_maps_cool_to_xiaobiu_cool() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _set_hvac_mode(family_id: str, device_id: str, mode: Any) -> dict[str, Any]:
    captured["set_hvac_mode"] = (family_id, device_id, getattr(mode, "value", mode))
    return {}

  client.set_hvac_mode = _set_hvac_mode  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_hvac_mode(HVACMode.COOL)

  assert captured["set_hvac_mode"][0] == "42"
  assert captured["set_hvac_mode"][1] == "ac-9"
  assert captured["set_hvac_mode"][2] == "cool"


@pytest.mark.asyncio
async def test_climate_set_hvac_mode_off_delegates_to_turn_off() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _turn_off(family_id: str, device_id: str) -> dict[str, Any]:
    captured["turn_off"] = (family_id, device_id)
    return {}

  def _set_hvac_mode(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    captured["set_hvac_mode"] = True
    return {}

  client.turn_off = _turn_off  # type: ignore[attr-defined]
  client.set_hvac_mode = _set_hvac_mode  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_hvac_mode(HVACMode.OFF)

  assert captured["turn_off"] == ("42", "ac-9")
  assert "set_hvac_mode" not in captured


@pytest.mark.asyncio
async def test_climate_set_temperature_calls_client() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _set_temperature(family_id: str, device_id: str, value: float) -> dict[str, Any]:
    captured["set_temperature"] = (family_id, device_id, value)
    return {}

  client.set_temperature = _set_temperature  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_temperature(temperature=23.5)

  assert captured["set_temperature"] == ("42", "ac-9", 23.5)


@pytest.mark.asyncio
async def test_climate_set_fan_mode_maps_to_xiaobiu_fan_speed() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _set_fan_mode(family_id: str, device_id: str, speed: Any) -> dict[str, Any]:
    captured["set_fan_mode"] = (family_id, device_id, getattr(speed, "value", speed))
    return {}

  client.set_fan_mode = _set_fan_mode  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_fan_mode("high")

  assert captured["set_fan_mode"] == ("42", "ac-9", "high")


@pytest.mark.asyncio
async def test_climate_set_swing_mode_sends_vertical_call_only() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _set_vertical(family_id: str, device_id: str, *, on: bool) -> dict[str, Any]:
    captured["set_vertical_swing"] = (family_id, device_id, on)
    return {}

  def _set_horizontal(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    captured["set_horizontal_swing"] = True
    return {}

  client.set_vertical_swing = _set_vertical  # type: ignore[attr-defined]
  client.set_horizontal_swing = _set_horizontal  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_swing_mode(SWING_ON)

  assert captured["set_vertical_swing"] == ("42", "ac-9", True)
  assert "set_horizontal_swing" not in captured


@pytest.mark.asyncio
async def test_climate_set_swing_horizontal_mode_sends_horizontal_call() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _set_horizontal(family_id: str, device_id: str, *, on: bool) -> dict[str, Any]:
    captured["set_horizontal_swing"] = (family_id, device_id, on)
    return {}

  def _set_vertical(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    captured["set_vertical_swing"] = True
    return {}

  client.set_horizontal_swing = _set_horizontal  # type: ignore[attr-defined]
  client.set_vertical_swing = _set_vertical  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_swing_horizontal_mode(SWING_HORIZONTAL_ON)

  assert captured["set_horizontal_swing"] == ("42", "ac-9", True)
  assert "set_vertical_swing" not in captured


@pytest.mark.asyncio
async def test_climate_set_preset_mode_none_disables_all_presets() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _set_eco(family_id: str, device_id: str, *, on: bool) -> dict[str, Any]:
    captured["set_eco"] = (family_id, device_id, on)
    return {}

  def _set_fresh_air(family_id: str, device_id: str, *, on: bool) -> dict[str, Any]:
    captured["set_fresh_air"] = (family_id, device_id, on)
    return {}

  def _set_aux_heat(family_id: str, device_id: str, *, on: bool) -> dict[str, Any]:
    captured["set_aux_heat"] = (family_id, device_id, on)
    return {}

  client.set_eco = _set_eco  # type: ignore[attr-defined]
  client.set_fresh_air = _set_fresh_air  # type: ignore[attr-defined]
  client.set_aux_heat = _set_aux_heat  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_preset_mode(PRESET_NONE)

  assert captured["set_eco"] == ("42", "ac-9", False)
  assert captured["set_fresh_air"] == ("42", "ac-9", False)
  assert captured["set_aux_heat"] == ("42", "ac-9", False)


@pytest.mark.asyncio
async def test_climate_set_preset_mode_eco_enables_only_eco() -> None:
  client = SimpleNamespace()
  captured: dict[str, Any] = {}

  def _set_eco(family_id: str, device_id: str, *, on: bool) -> dict[str, Any]:
    captured["set_eco"] = (family_id, device_id, on)
    return {}

  def _set_fresh_air(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    captured["set_fresh_air"] = True
    return {}

  def _set_aux_heat(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    captured["set_aux_heat"] = True
    return {}

  client.set_eco = _set_eco  # type: ignore[attr-defined]
  client.set_fresh_air = _set_fresh_air  # type: ignore[attr-defined]
  client.set_aux_heat = _set_aux_heat  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_preset_mode(PRESET_ECO)

  assert captured["set_eco"] == ("42", "ac-9", True)
  assert "set_fresh_air" not in captured
  assert "set_aux_heat" not in captured


@pytest.mark.asyncio
async def test_climate_setter_raises_home_assistant_error_on_sms_rate_limited() -> None:
  client_lib = load_client_lib()

  def _set_temperature(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise client_lib.SmsRateLimitedError("短信发送太频繁，请稍后再试")

  client = SimpleNamespace(set_temperature=_set_temperature)
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  with pytest.raises(HomeAssistantError, match="xiaobiu control failed"):
    await entity.async_set_temperature(temperature=24.0)


@pytest.mark.asyncio
async def test_climate_setter_raises_config_entry_auth_failed_on_auth_error() -> None:
  client_lib = load_client_lib()

  def _set_temperature(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise client_lib.AuthenticationError("session expired")

  client = SimpleNamespace(set_temperature=_set_temperature)
  status = _make_climate_status(family_id="42", device_id="ac-9")
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities(), client=client)
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  with pytest.raises(ConfigEntryAuthFailed):
    await entity.async_set_temperature(temperature=24.0)


@pytest.mark.asyncio
async def test_climate_setter_refreshes_coordinator_after_success() -> None:
  client = SimpleNamespace()
  refresh_calls: list[int] = []

  def _set_temperature(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return {}

  client.set_temperature = _set_temperature  # type: ignore[attr-defined]
  status = _make_climate_status(family_id="42", device_id="ac-9")

  async def _async_request_refresh() -> None:
    refresh_calls.append(1)

  coordinator = SimpleNamespace(
    status_for=lambda _device_id: status,
    capabilities_for=lambda _device_id: FakeCapabilities(),
    client=client,
    device_ids=("ac-9",),
    async_request_refresh=_async_request_refresh,
  )
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-9"))

  await entity.async_set_temperature(temperature=24.0)

  assert refresh_calls == [1]


def test_climate_preset_mode_reads_status_flags() -> None:
  status = _make_climate_status(
    eco_enabled=True,
    fresh_air_enabled=False,
    electric_heating_enabled=True,
  )
  coordinator = _make_climate_coordinator(status=status, capabilities=FakeCapabilities())
  entity = _attach_hass(SuningClimateEntity(coordinator=coordinator, entry=FakeConfigEntry(data={}), device_id="ac-1"))

  assert entity.preset_mode == PRESET_AUX_HEAT


def test_strings_json_removes_har_text_and_keeps_reauth() -> None:
  strings_path = Path("custom_components/xiaobiu/strings.json")
  payload = json.loads(strings_path.read_text(encoding="utf-8"))

  assert "har_path" not in payload["config"]["step"]["user"]["data"]
  assert "reconfigure" in payload["config"]["step"]
  assert "reconfigure_auth" in payload["config"]["step"]
  assert "har_not_found" not in payload["config"]["error"]
  assert "{captcha_url}" not in payload["config"]["step"]["captcha"]["description"]
  assert "reauth_confirm" in payload["config"]["step"]
  assert "captcha_risk_context_missing" in payload["config"]["abort"]
  assert "captcha_session_expired" in payload["config"]["abort"]
  assert "reauth_successful" in payload["config"]["abort"]
  assert "reconfigure_successful" in payload["config"]["abort"]
