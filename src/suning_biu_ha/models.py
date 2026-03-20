from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SuningBaseModel(BaseModel):
  model_config = ConfigDict(extra="ignore", validate_assignment=True)


class LoginPageConfig(SuningBaseModel):
  login_pbk: str
  rdsy_key: str
  rdsy_app_code: str
  step_flag: str
  step_two_flag: str
  step_three_flag: str
  rdsy_scene_id: str
  rdsy_scene_id_yghk: str
  channel: str
  check_account_key: str


class AuthState(SuningBaseModel):
  phone_number: str | None = None
  international_code: str = "0086"
  detect: str = "passport_detect_js_is_error"
  dfp_token: str = "passport_dfpToken_js_is_error"
  risk_type: str | None = None
  sms_ticket: str | None = None
  login_ticket: str | None = None
  login_response: dict[str, Any] | None = None
  updated_at: float | None = None


class CaptchaSolution(SuningBaseModel):
  kind: str
  value: str


class SignedRequestTemplate(SuningBaseModel):
  method: str
  url: str
  headers: dict[str, str] = Field(default_factory=dict)
  body: str = ""
  har_path: str | None = None

  def build_headers(self) -> dict[str, str]:
    trace_id = uuid4().hex
    headers: dict[str, str] = {}
    for name, value in self.headers.items():
      lower_name = name.lower()
      if lower_name in {"host", "cookie", "content-length"} or lower_name.startswith(":"):
        continue
      if lower_name in {"sntraceid", "hiro_trace_id"}:
        headers[name] = trace_id
        continue
      headers[name] = value
    return headers


class FamilyInfo(SuningBaseModel):
  family_id: str
  name: str
  raw: dict[str, Any] = Field(default_factory=dict)


class HAClimatePreview(SuningBaseModel):
  entity_domain: str
  translation_key: str
  available: bool
  hvac_mode: str | None = None
  current_temperature: float | None = None
  target_temperature: float | None = None
  fan_mode: str | None = None
  swing_mode: str | None = None
  preset_mode: str | None = None
  supported_features_preview: list[str] = Field(default_factory=list)
  raw_mapping: dict[str, dict[str, Any]] = Field(default_factory=dict)
  notes: list[str] = Field(default_factory=list)


class AirConditionerStatus(SuningBaseModel):
  device_id: str
  name: str
  model: str | None = None
  family_id: str | None = None
  group_id: str | None = None
  group_name: str | None = None
  category_id: str | None = None
  available: bool
  online: bool
  summary: str | None = None
  device_record_time: str | None = None
  refresh_time: str | None = None
  power_on: bool | None = None
  current_temperature: float | None = None
  target_temperature: float | None = None
  outdoor_temperature: float | None = None
  mode_raw: str | None = None
  fan_mode_raw: str | None = None
  swing_horizontal: bool | None = None
  swing_vertical: bool | None = None
  eco_enabled: bool | None = None
  purify_enabled: bool | None = None
  fresh_air_enabled: bool | None = None
  electric_heating_enabled: bool | None = None
  ha_climate_preview: HAClimatePreview | None = None
  raw_status: dict[str, Any] = Field(default_factory=dict)
  raw_device: dict[str, Any] = Field(default_factory=dict)


class SerializedCookie(SuningBaseModel):
  name: str
  value: str
  domain: str
  path: str
  secure: bool = False
  expires: int | float | None = None
  rest: dict[str, Any] = Field(default_factory=dict)


class PersistedSessionState(SuningBaseModel):
  state: AuthState = Field(default_factory=AuthState)
  cookies: list[SerializedCookie] = Field(default_factory=list)


class CaptchaBridgeResult(SuningBaseModel):
  token: str
