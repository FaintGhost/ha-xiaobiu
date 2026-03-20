from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from . import resolve_har_path, session_state_path
from .client_lib import SuningDependencyError, load_client_lib
from .const import (
  CONF_FAMILY_ID,
  CONF_FAMILY_NAME,
  CONF_HAR_PATH,
  CONF_INTERNATIONAL_CODE,
  CONF_PHONE_NUMBER,
  DEFAULT_INTERNATIONAL_CODE,
  DOMAIN,
)

CAPTCHA_POLL_TIMEOUT = 0.1


class SuningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
  VERSION = 1

  def __init__(self) -> None:
    self._phone_number: str | None = None
    self._international_code: str = DEFAULT_INTERNATIONAL_CODE
    self._har_path: str | None = None
    self._client: object | None = None
    self._families: list[Any] = []
    self._captcha_kind: str | None = None
    self._captcha_bridge: object | None = None

  async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
    errors: dict[str, str] = {}

    if user_input is not None:
      self._phone_number = user_input[CONF_PHONE_NUMBER].strip()
      self._international_code = user_input[CONF_INTERNATIONAL_CODE].strip()
      self._har_path = user_input[CONF_HAR_PATH].strip()
      await self.async_set_unique_id(f"{self._international_code}:{self._phone_number}")
      self._abort_if_unique_id_configured()

      client_lib, error_key = self._initialize_client()
      if error_key is None and client_lib is not None:
        try:
          return await self._async_send_sms()
        except client_lib.SuningError:
          errors["base"] = "cannot_connect"
      elif error_key is not None:
        errors["base"] = error_key

    return self.async_show_form(
      step_id="user",
      data_schema=vol.Schema(
        {
          vol.Required(CONF_PHONE_NUMBER): str,
          vol.Required(CONF_INTERNATIONAL_CODE, default=self._international_code): str,
          vol.Required(CONF_HAR_PATH): str,
        }
      ),
      errors=errors,
    )

  async def async_step_reauth(
    self,
    entry_data: Mapping[str, Any],
  ) -> ConfigFlowResult:
    reauth_entry = self._get_reauth_entry()
    self._phone_number = str(entry_data.get(CONF_PHONE_NUMBER, reauth_entry.data[CONF_PHONE_NUMBER]))
    self._international_code = str(
      entry_data.get(
        CONF_INTERNATIONAL_CODE,
        reauth_entry.data[CONF_INTERNATIONAL_CODE],
      )
    )
    self._har_path = str(entry_data.get(CONF_HAR_PATH, reauth_entry.data[CONF_HAR_PATH]))
    return await self.async_step_reauth_confirm()

  async def async_step_reauth_confirm(
    self,
    user_input: dict[str, Any] | None = None,
  ) -> ConfigFlowResult:
    errors: dict[str, str] = {}

    if user_input is not None:
      client_lib, error_key = self._initialize_client()
      if error_key is None and client_lib is not None:
        try:
          return await self._async_send_sms()
        except client_lib.SuningError:
          errors["base"] = "cannot_connect"
      elif error_key is not None:
        errors["base"] = error_key

    return self.async_show_form(
      step_id="reauth_confirm",
      data_schema=vol.Schema({}),
      description_placeholders={"phone_number": self._phone_number or ""},
      errors=errors,
    )

  async def async_step_reconfigure(
    self,
    user_input: dict[str, Any] | None = None,
  ) -> ConfigFlowResult:
    errors: dict[str, str] = {}
    reconfigure_entry = self._get_reconfigure_entry()

    if user_input is not None:
      har_path = user_input[CONF_HAR_PATH].strip()
      try:
        resolve_har_path(self.hass, har_path)
      except ValueError:
        errors["base"] = "har_not_found"
      else:
        return self.async_update_reload_and_abort(
          reconfigure_entry,
          data_updates={CONF_HAR_PATH: har_path},
        )

    return self.async_show_form(
      step_id="reconfigure",
      data_schema=self.add_suggested_values_to_schema(
        vol.Schema({vol.Required(CONF_HAR_PATH): str}),
        {CONF_HAR_PATH: reconfigure_entry.data[CONF_HAR_PATH]},
      ),
      description_placeholders={
        "phone_number": str(reconfigure_entry.data[CONF_PHONE_NUMBER]),
        "family_name": str(reconfigure_entry.data.get(CONF_FAMILY_NAME, "")),
      },
      errors=errors,
    )

  async def async_step_captcha(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
    errors: dict[str, str] = {}
    description_placeholders: dict[str, str] = {}

    if self._captcha_kind == "iar" and self._captcha_bridge is not None:
      description_placeholders["captcha_url"] = self._captcha_bridge.url

    if user_input is not None:
      client_lib = load_client_lib()
      try:
        captcha = await self._async_resolve_captcha(user_input)
        return await self._async_send_sms(captcha)
      except TimeoutError:
        errors["base"] = "captcha_not_ready"
      except client_lib.SuningError:
        errors["base"] = "cannot_connect"

    schema: vol.Schema
    if self._captcha_kind == "iar":
      schema = vol.Schema({})
    else:
      schema = vol.Schema(
        {
          vol.Required("captcha_value"): str,
        }
      )

    return self.async_show_form(
      step_id="captcha",
      data_schema=schema,
      errors=errors,
      description_placeholders=description_placeholders,
    )

  async def async_step_sms_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
    errors: dict[str, str] = {}

    if user_input is not None and self._client is not None and self._phone_number is not None:
      client_lib = load_client_lib()
      try:
        await self.hass.async_add_executor_job(
          partial(
            self._client.login_with_sms_code,
            phone_number=self._phone_number,
            sms_code=user_input["sms_code"].strip(),
            international_code=self._international_code,
          )
        )
      except client_lib.SuningError:
        errors["base"] = "invalid_auth"
      else:
        try:
          if self.source == config_entries.SOURCE_REAUTH:
            await self.hass.async_add_executor_job(self._client.keep_alive)
            return self.async_update_reload_and_abort(self._get_reauth_entry())
          self._families = await self.hass.async_add_executor_job(self._client.list_family_infos)
          return await self.async_step_family()
        except client_lib.SuningError:
          errors["base"] = "cannot_connect"

    return self.async_show_form(
      step_id="sms_code",
      data_schema=vol.Schema({vol.Required("sms_code"): str}),
      errors=errors,
    )

  async def async_step_family(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
    errors: dict[str, str] = {}

    if user_input is not None and self._client is not None and self._phone_number is not None:
      family_id = user_input[CONF_FAMILY_ID]
      client_lib = load_client_lib()
      try:
        statuses = await self.hass.async_add_executor_job(
          self._client.list_air_conditioner_statuses,
          family_id,
        )
      except client_lib.SuningError:
        errors["base"] = "cannot_connect"
      else:
        if not statuses:
          errors["base"] = "no_supported_devices"
        else:
          family = next((item for item in self._families if item.family_id == family_id), None)
          if family is None:
            errors["base"] = "cannot_connect"
            return self.async_show_form(
              step_id="family",
              data_schema=self._family_schema(),
              errors=errors,
            )
          return self.async_create_entry(
            title=self._entry_title(family.name),
            data={
              CONF_PHONE_NUMBER: self._phone_number,
              CONF_INTERNATIONAL_CODE: self._international_code,
              CONF_HAR_PATH: self._har_path,
              CONF_FAMILY_ID: family.family_id,
              CONF_FAMILY_NAME: family.name,
            },
          )

    return self.async_show_form(
      step_id="family",
      data_schema=self._family_schema(),
      errors=errors,
    )

  async def _async_send_sms(
    self,
    captcha: Any | None = None,
  ) -> ConfigFlowResult:
    client_lib = load_client_lib()
    if self._client is None or self._phone_number is None:
      raise client_lib.SuningError("config flow client is not initialized")
    try:
      await self.hass.async_add_executor_job(
        partial(
          self._client.send_sms_code,
          self._phone_number,
          international_code=self._international_code,
          captcha=captcha,
        )
      )
    except client_lib.CaptchaRequiredError as error:
      self._captcha_kind = {
        "isIarVerifyCode": "iar",
        "isSlideVerifyCode": "slide",
        "isImgVerifyCode": "image",
      }.get(error.risk_type)
      if self._captcha_kind == "iar":
        self._close_captcha_bridge()
        ticket = await self.hass.async_add_executor_job(
          self._client.request_iar_verify_code_ticket,
          self._phone_number,
        )
        self._captcha_bridge = client_lib.LocalCaptchaBridge(ticket=ticket)
        self._captcha_bridge.start()
      elif self._captcha_kind is None:
        raise client_lib.SuningError(f"unsupported captcha risk type: {error.risk_type}") from error
      return await self.async_step_captcha()
    return await self.async_step_sms_code()

  async def _async_resolve_captcha(self, user_input: dict[str, Any]) -> Any:
    client_lib = load_client_lib()
    if self._captcha_kind == "iar":
      if self._captcha_bridge is None:
        raise client_lib.SuningError("IAR captcha bridge is not initialized")
      try:
        result = await self.hass.async_add_executor_job(
          self._captcha_bridge.wait_for_token,
          CAPTCHA_POLL_TIMEOUT,
        )
      finally:
        self._close_captcha_bridge()
      return client_lib.CaptchaSolution(kind="iar", value=result.token)

    return client_lib.CaptchaSolution(
      kind=self._captcha_kind or "image",
      value=user_input["captcha_value"].strip(),
    )

  def _initialize_client(self) -> tuple[Any | None, str | None]:
    try:
      client_lib = load_client_lib()
    except SuningDependencyError:
      return None, "dependency_not_ready"

    if self._phone_number is None or self._har_path is None:
      return client_lib, "cannot_connect"

    try:
      resolved_har_path = resolve_har_path(self.hass, self._har_path)
    except ValueError:
      return client_lib, "har_not_found"

    self._client = client_lib.SuningSmartHomeClient(
      state_path=session_state_path(
        self.hass,
        self._international_code,
        self._phone_number,
      ),
      har_path=resolved_har_path,
    )
    return client_lib, None

  def _family_schema(self) -> vol.Schema:
    return vol.Schema(
      {
        vol.Required(CONF_FAMILY_ID): SelectSelector(
          SelectSelectorConfig(
            options=[
              {"value": family.family_id, "label": family.name}
              for family in self._families
            ],
            mode=SelectSelectorMode.DROPDOWN,
          )
        )
      }
    )

  def _entry_title(self, family_name: str) -> str:
    return f"{self._phone_number} - {family_name}"

  def _close_captcha_bridge(self) -> None:
    if self._captcha_bridge is None:
      return
    self._captcha_bridge.close()
    self._captcha_bridge = None
