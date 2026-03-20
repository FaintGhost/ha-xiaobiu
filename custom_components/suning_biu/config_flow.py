from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from suning_biu_ha import CaptchaRequiredError, CaptchaSolution, FamilyInfo, SuningError, SuningSmartHomeClient
from suning_biu_ha.captcha_bridge import LocalCaptchaBridge

from . import session_state_path
from .const import (
  CONF_FAMILY_ID,
  CONF_FAMILY_NAME,
  CONF_HAR_PATH,
  CONF_INTERNATIONAL_CODE,
  CONF_PHONE_NUMBER,
  DEFAULT_INTERNATIONAL_CODE,
  DOMAIN,
)


class SuningConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
  VERSION = 1

  def __init__(self) -> None:
    self._phone_number: str | None = None
    self._international_code: str = DEFAULT_INTERNATIONAL_CODE
    self._har_path: str | None = None
    self._client: SuningSmartHomeClient | None = None
    self._families: list[FamilyInfo] = []
    self._captcha_kind: str | None = None
    self._captcha_bridge: LocalCaptchaBridge | None = None

  async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    errors: dict[str, str] = {}

    if user_input is not None:
      self._phone_number = user_input[CONF_PHONE_NUMBER].strip()
      self._international_code = user_input[CONF_INTERNATIONAL_CODE].strip()
      self._har_path = user_input[CONF_HAR_PATH].strip()
      await self.async_set_unique_id(f"{self._international_code}:{self._phone_number}")
      self._abort_if_unique_id_configured()

      if not Path(self._har_path).is_file():
        errors["base"] = "har_not_found"
      else:
        self._client = SuningSmartHomeClient(
          state_path=session_state_path(
            self.hass,
            self._international_code,
            self._phone_number,
          ),
          har_path=self._har_path,
        )
        try:
          return await self._async_send_sms()
        except SuningError:
          errors["base"] = "cannot_connect"

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

  async def async_step_captcha(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    errors: dict[str, str] = {}
    description_placeholders: dict[str, str] = {}

    if self._captcha_kind == "iar" and self._captcha_bridge is not None:
      description_placeholders["captcha_url"] = self._captcha_bridge.url

    if user_input is not None:
      try:
        captcha = await self._async_resolve_captcha(user_input)
        return await self._async_send_sms(captcha)
      except TimeoutError:
        errors["base"] = "captcha_not_ready"
      except SuningError:
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

  async def async_step_sms_code(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    errors: dict[str, str] = {}

    if user_input is not None and self._client is not None and self._phone_number is not None:
      try:
        await self.hass.async_add_executor_job(
          partial(
            self._client.login_with_sms_code,
            phone_number=self._phone_number,
            sms_code=user_input["sms_code"].strip(),
            international_code=self._international_code,
          )
        )
        self._families = await self.hass.async_add_executor_job(self._client.list_family_infos)
        return await self.async_step_family()
      except SuningError:
        errors["base"] = "invalid_auth"

    return self.async_show_form(
      step_id="sms_code",
      data_schema=vol.Schema({vol.Required("sms_code"): str}),
      errors=errors,
    )

  async def async_step_family(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    errors: dict[str, str] = {}

    if user_input is not None and self._client is not None and self._phone_number is not None:
      family_id = user_input[CONF_FAMILY_ID]
      try:
        statuses = await self.hass.async_add_executor_job(
          self._client.list_air_conditioner_statuses,
          family_id,
        )
      except SuningError:
        errors["base"] = "cannot_connect"
      else:
        if not statuses:
          errors["base"] = "no_supported_devices"
        else:
          family = next(item for item in self._families if item.family_id == family_id)
          return self.async_create_entry(
            title=f"{self._phone_number} - {family.name}",
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
      data_schema=vol.Schema(
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
      ),
      errors=errors,
    )

  async def _async_send_sms(
    self,
    captcha: CaptchaSolution | None = None,
  ) -> FlowResult:
    if self._client is None or self._phone_number is None:
      raise SuningError("config flow client is not initialized")
    try:
      await self.hass.async_add_executor_job(
        partial(
          self._client.send_sms_code,
          self._phone_number,
          international_code=self._international_code,
          captcha=captcha,
        )
      )
    except CaptchaRequiredError as error:
      self._captcha_kind = {
        "isIarVerifyCode": "iar",
        "isSlideVerifyCode": "slide",
        "isImgVerifyCode": "image",
      }.get(error.risk_type)
      if self._captcha_kind == "iar":
        ticket = await self.hass.async_add_executor_job(
          self._client.request_iar_verify_code_ticket,
          self._phone_number,
        )
        self._captcha_bridge = LocalCaptchaBridge(ticket=ticket)
        self._captcha_bridge.start()
      elif self._captcha_kind is None:
        raise SuningError(f"unsupported captcha risk type: {error.risk_type}") from error
      return await self.async_step_captcha()
    return await self.async_step_sms_code()

  async def _async_resolve_captcha(self, user_input: dict[str, Any]) -> CaptchaSolution:
    if self._captcha_kind == "iar":
      if self._captcha_bridge is None:
        raise SuningError("IAR captcha bridge is not initialized")
      try:
        result = await self.hass.async_add_executor_job(
          self._captcha_bridge.wait_for_token,
          0.1,
        )
      finally:
        self._captcha_bridge.close()
        self._captcha_bridge = None
      return CaptchaSolution(kind="iar", value=result.token)

    return CaptchaSolution(
      kind=self._captcha_kind or "image",
      value=user_input["captcha_value"].strip(),
    )
