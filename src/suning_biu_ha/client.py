from __future__ import annotations

import argparse
import base64
import html
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.cookies import create_cookie

from .captcha_bridge import LocalCaptchaBridge
from .crypto import SuAESCipher, rsa_encrypt_base64
from .models import (
  AirConditionerStatus,
  AuthState,
  CaptchaSolution,
  FamilyInfo,
  HAClimatePreview,
  LoginPageConfig,
  PersistedSessionState,
  SerializedCookie,
  SignedRequestTemplate,
)

DEFAULT_LOGIN_URL = "https://passport.suning.com/ids/login"
DEFAULT_TARGET_URL = "https://www.suning.com/"
DEFAULT_TIMEOUT = 20.0
DEFAULT_USER_AGENT = (
  "Mozilla/5.0 (X11; Linux x86_64) "
  "AppleWebKit/537.36 (KHTML, like Gecko) "
  "Chrome/134.0.0.0 Safari/537.36"
)
MEMBER_BASE_INFO_URL = "https://shcss.suning.com/shcss-web/api/member/queryMemberBaseInfo.do"
FAMILY_LIST_URL = "https://itapig.suning.com/api/trade/shcss/queryAllFamily"
DEVICE_LIST_URL = "https://itapig.suning.com/api/trade/shcss/all"
OPENSH_GET_KEY_URL = "https://opensh.suning.com/shsys-web/cc/api/v3/getKey"
SUCCESS_RESPONSE_CODES = {"0", "SUCCESS"}
SERVICE_BOOTSTRAP_URLS = {
  "shcss": MEMBER_BASE_INFO_URL,
  "itapig": "http://itapig.suning.com/api/trade/shcss/queryAllFamily",
  "opensh": OPENSH_GET_KEY_URL,
}

DEFAULT_LOGIN_PAGE_CONFIG = LoginPageConfig(
  login_pbk=(
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQComqoAyvbCqO1EGsADwfNTWFQIUbm8"
    "CLdeb9TgjGLcz95mAo204SqTYdSEUxFsOnPfROOTxhkhfjbRxBV4/xjS06Y+kkUdiMG"
    "FtABIxRQHQIh0LrVvEZQs4NrixxcPI+b1bpE0gO/GAFSNWm9ejhZGj7UnqiHphnSJAVQ"
    "Nz2lgowIDAQAB"
  ),
  rdsy_key=(
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDZnlkciI+qxNATzQOOcU8rxtfJxlbj"
    "RKEhoz1WhuAFuCe6ZHEh85UjGiG0FN0oBCKoC4aprTlzNDEr/cU2bzTJELhs9xoU80Um"
    "364GY0zbMr1qnnSouyv0Wb/sgrB/cTDmw8HNiX77mCmX+R4Un/6Xj3BBpm52CHn3RXI9"
    "HeE/xwIDAQAB"
  ),
  rdsy_app_code="9FAD2DDEFE754D604779F7BB8264C80F",
  step_flag="8763EC7BB5D7EEE18EDD1E4BD59A1679",
  step_two_flag="3D58885D2B0CB135703770C03852E8CB",
  step_three_flag="08DD83216388DA0A29B5B3CEE0CC0E6F",
  rdsy_scene_id="PASSPORT",
  rdsy_scene_id_yghk="PASSPORT_YGHK",
  channel="PC",
  check_account_key=(
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCOuozMgVH/glMcCOIDKjXP83zDmgi6"
    "hKvwB9VLQG6RWcxm/lNmB/Uq3LGdKUnm+JBFy1GeHA8oNKLFROF/ebzSqr6kOkuSsAZm"
    "cvsvgaigD7cSzIipdfJpE3bZd9y7X8Mq+uDhNKpvlH9lR+OmTgMFAKq8w6QMYY+ksHjW"
    "INSDIwIDAQAB"
  ),
)


class SuningError(RuntimeError):
  pass


class CaptchaRequiredError(SuningError):
  def __init__(self, risk_type: str, message: str, sms_ticket: str | None = None) -> None:
    super().__init__(message)
    self.risk_type = risk_type
    self.sms_ticket = sms_ticket


class AuthenticationError(SuningError):
  pass


def parse_jsonp_or_json(payload: str) -> dict[str, Any]:
  text = payload.strip()
  if not text:
    raise SuningError("empty response")
  if text[0] == "{":
    return json.loads(text)
  match = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.S)
  if not match:
    raise SuningError(f"unable to parse jsonp payload: {text[:120]!r}")
  return json.loads(match.group(1))


def parse_login_page_config(html: str) -> LoginPageConfig:
  def extract(pattern: str, name: str) -> str:
    match = re.search(pattern, html, re.S)
    if not match:
      raise SuningError(f"missing {name} in login page")
    return match.group(1)

  config = LoginPageConfig(
    login_pbk=extract(r'var\s+loginPBK="([^"]+)"', "loginPBK"),
    rdsy_key=extract(r'var\s+rdsyKey="([^"]+)"', "rdsyKey"),
    rdsy_app_code=extract(r'rdsyAppCode:"([^"]+)"', "rdsyAppCode"),
    step_flag=extract(r'stepFlag:"([^"]+)"', "stepFlag"),
    step_two_flag=extract(r'stepTwoFlag:"([^"]+)"', "stepTwoFlag"),
    step_three_flag=extract(r'stepThreeFlag:"([^"]+)"', "stepThreeFlag"),
    rdsy_scene_id=extract(r'rdsySceneId:"([^"]+)"', "rdsySceneId"),
    rdsy_scene_id_yghk=extract(r'rdsySceneIdYGHK:"([^"]+)"', "rdsySceneIdYGHK"),
    channel=extract(r'channel:"([^"]+)"', "channel"),
    check_account_key=extract(r'checkAccountKey:\s*"([^"]+)"', "checkAccountKey"),
  )
  return config


def _normalize_url(url: str) -> str:
  parts = urlsplit(url)
  return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _canonicalize_request_body(raw_body: str | None, content_type: str | None = None) -> str:
  if not raw_body:
    return ""
  body = raw_body.strip()
  if "json" in (content_type or "").lower():
    try:
      return json.dumps(json.loads(body), separators=(",", ":"), ensure_ascii=False)
    except json.JSONDecodeError:
      return body
  return body


def _decode_har_content(content: dict[str, Any]) -> str:
  text = content.get("text") or ""
  if content.get("encoding") == "base64":
    return base64.b64decode(text).decode("utf-8", "replace")
  return text


def _extract_har_headers(entry: dict[str, Any]) -> dict[str, str]:
  return {
    item["name"]: item["value"]
    for item in entry.get("request", {}).get("headers", [])
    if "name" in item and "value" in item
  }


def _har_response_payload(entry: dict[str, Any]) -> dict[str, Any] | None:
  content = entry.get("response", {}).get("content") or {}
  text = _decode_har_content(content).strip()
  if not text:
    return None
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    return parse_jsonp_or_json(text)


def _har_entry_is_success(entry: dict[str, Any]) -> bool:
  if entry.get("response", {}).get("status") != 200:
    return False
  payload = _har_response_payload(entry)
  if not payload:
    return False
  return str(payload.get("responseCode") or payload.get("code") or "").upper() in SUCCESS_RESPONSE_CODES


def _template_key(method: str, url: str, body: str) -> tuple[str, str, str]:
  return (method.upper(), _normalize_url(url), body)


def _coalesce(*values: Any) -> Any:
  for value in values:
    if value is None:
      continue
    if isinstance(value, str) and not value.strip():
      continue
    return value
  return None


def _parse_bool_flag(value: Any) -> bool | None:
  normalized = str(value).strip().lower()
  if not normalized:
    return None
  if normalized in {"1", "true", "on", "yes"}:
    return True
  if normalized in {"0", "false", "off", "no"}:
    return False
  return None


def _parse_float_value(value: Any) -> float | None:
  if value is None:
    return None
  normalized = str(value).strip()
  if not normalized:
    return None
  try:
    return float(normalized)
  except ValueError:
    return None


def _strip_html_text(value: Any) -> str | None:
  if value is None:
    return None
  text = html.unescape(str(value))
  text = re.sub(r"<[^>]+>", "", text)
  normalized = text.strip()
  return normalized or None


def _infer_swing_mode(horizontal: bool | None, vertical: bool | None) -> str | None:
  if horizontal is True and vertical is True:
    return "both"
  if horizontal is True:
    return "horizontal"
  if vertical is True:
    return "vertical"
  if horizontal is False and vertical is False:
    return "off"
  return None


def _serialize_cookie(cookie: Any) -> SerializedCookie:
  return SerializedCookie(
    name=cookie.name,
    value=cookie.value,
    domain=cookie.domain,
    path=cookie.path,
    secure=cookie.secure,
    expires=cookie.expires,
    rest=getattr(cookie, "_rest", {}) or {},
  )


def _restore_cookie(serialized_cookie: SerializedCookie) -> Any:
  return create_cookie(
    name=serialized_cookie.name,
    value=serialized_cookie.value,
    domain=serialized_cookie.domain,
    path=serialized_cookie.path,
    secure=serialized_cookie.secure,
    expires=serialized_cookie.expires,
    rest=serialized_cookie.rest,
  )


class SuningSmartHomeClient:
  def __init__(
    self,
    *,
    state_path: str | Path | None = None,
    har_path: str | Path | None = None,
    detect: str | None = None,
    dfp_token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = DEFAULT_USER_AGENT,
  ) -> None:
    self.timeout = timeout
    self.state_path = Path(state_path) if state_path else None
    self.har_path = Path(har_path) if har_path else None
    self.session = requests.Session()
    self.session.headers.update(
      {
        "Accept": "*/*",
        "User-Agent": user_agent,
      }
    )
    self.suaes = SuAESCipher()
    self.config = DEFAULT_LOGIN_PAGE_CONFIG
    self.state = AuthState()
    self.signed_templates: dict[tuple[str, str, str], SignedRequestTemplate] = {}
    if detect:
      self.state.detect = detect
    if dfp_token:
      self.state.dfp_token = dfp_token
    if self.state_path and self.state_path.exists():
      self.load_state()
    self.load_signed_templates()

  def update_risk_context(self, *, detect: str | None = None, dfp_token: str | None = None) -> None:
    if detect:
      self.state.detect = detect
    if dfp_token:
      self.state.dfp_token = dfp_token
    self._touch_state()

  def initialize(self) -> LoginPageConfig:
    response = self.session.get(
      DEFAULT_LOGIN_URL,
      timeout=self.timeout,
    )
    response.raise_for_status()
    try:
      self.config = parse_login_page_config(response.text)
    except SuningError:
      self.config = DEFAULT_LOGIN_PAGE_CONFIG
    self._touch_state()
    return self.config

  def prepare_sms_login(
    self,
    phone_number: str,
    *,
    international_code: str = "0086",
  ) -> dict[str, Any]:
    self.initialize()
    self.state.phone_number = phone_number
    self.state.international_code = international_code
    request_body = {
      "sceneId": self._scene_id(international_code),
      "stepFlag": self.config.step_flag,
      "appCode": self.config.rdsy_app_code,
      "data": {
        "ways": "duanxindl",
        "channel": self.config.channel,
        "orderChannel": self._channel(international_code),
        "dfpToken": self.state.dfp_token,
        "detect": self.state.detect,
        "loginTheme": "defaultTheme",
        "referenceURL": DEFAULT_LOGIN_URL,
        "userName": phone_number,
        "cntctMobileNum": phone_number,
        "mode": "1",
        "subMode": "4",
      },
    }
    payload = {
      "_x_rdsy_block_": self.suaes.encrypt(
        json.dumps(request_body, separators=(",", ":"), ensure_ascii=False)
      ),
      "callback": self._jsonp_callback("needVerifyCode"),
    }
    response = self.session.get(
      "https://rdsy.suning.com/rdsy/needVerifyCode.do",
      params=payload,
      timeout=self.timeout,
      headers={"Referer": DEFAULT_LOGIN_URL},
    )
    response.raise_for_status()
    outer = parse_jsonp_or_json(response.text)
    inner = self._decrypt_rdsy_response(outer)
    if inner.get("status") != "COMPLETE":
      raise SuningError(inner.get("msg") or "failed to prepare sms login")
    self.state.sms_ticket = inner["data"].get("ticket")
    self.state.risk_type = inner["data"].get("riskType")
    self._touch_state()
    return inner

  def send_sms_code(
    self,
    phone_number: str | None = None,
    *,
    international_code: str | None = None,
    captcha: CaptchaSolution | None = None,
  ) -> dict[str, Any]:
    target_phone = phone_number or self.state.phone_number
    if not target_phone:
      raise SuningError("phone number is required")
    area_code = international_code or self.state.international_code
    if not self.state.sms_ticket or not self.state.risk_type:
      self.prepare_sms_login(target_phone, international_code=area_code)
    if self.state.risk_type and self.state.risk_type != "isNullVerifyCode" and not captcha:
      raise CaptchaRequiredError(
        self.state.risk_type,
        "captcha token is required before sending sms code",
        self.state.sms_ticket,
      )
    params: dict[str, Any] = {
      "sceneId": self._scene_id(area_code),
      "stepFlag": self.config.step_two_flag,
      "appCode": self.config.rdsy_app_code,
      "riskType": self.state.risk_type or "",
      "phoneNum": rsa_encrypt_base64(target_phone, self.config.rdsy_key),
      "internationalCode": area_code,
      "callback": self._jsonp_callback("sendCode"),
      "ticket": self.state.sms_ticket or "",
      "code": "",
      "uuid": "",
      "data": {
        "ways": "duanxindl",
        "channel": self.config.channel,
        "orderChannel": self._channel(area_code),
        "dfpToken": self.state.dfp_token,
        "detect": self.state.detect,
        "loginTheme": "defaultTheme",
        "userName": target_phone,
        "cntctMobileNum": target_phone,
        "checkAliasName": "0",
        "referenceURL": DEFAULT_LOGIN_URL,
      },
    }
    if captcha:
      params.update(self._captcha_fields(captcha))
    payload = {
      "_x_rdsy_block_": self.suaes.encrypt(
        json.dumps(params, separators=(",", ":"), ensure_ascii=False)
      ),
      "callback": params["callback"],
    }
    response = self.session.get(
      "https://rdsy.suning.com/rdsy/sendCode.do",
      params=payload,
      timeout=self.timeout,
      headers={"Referer": DEFAULT_LOGIN_URL},
    )
    response.raise_for_status()
    outer = parse_jsonp_or_json(response.text)
    inner = self._decrypt_rdsy_response(outer)
    if inner.get("status") == "COMPLETE":
      self.state.login_ticket = inner["data"].get("ticket")
      self._touch_state()
      return inner
    if inner.get("code") == "R0004":
      data = inner.get("data") or {}
      self.state.sms_ticket = data.get("ticket") or self.state.sms_ticket
      self.state.risk_type = data.get("riskType") or self.state.risk_type
      self._touch_state()
      raise CaptchaRequiredError(
        self.state.risk_type or "unknown",
        inner.get("msg") or "captcha is required again",
        self.state.sms_ticket,
      )
    raise SuningError(inner.get("msg") or "failed to send sms code")

  def request_iar_verify_code_ticket(self, phone_number: str) -> str:
    response = self.session.post(
      "https://passport.suning.com/ids/iarVerifyCodeTicket",
      data={
        "deviceId": "",
        "dfpToken": self.state.dfp_token,
        "username": phone_number,
      },
      timeout=self.timeout,
      headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": DEFAULT_LOGIN_URL,
      },
    )
    response.raise_for_status()
    data = response.json()
    if str(data.get("result")).lower() != "true" or not data.get("ticket"):
      raise SuningError("申请 IAR 验证 ticket 失败")
    return data["ticket"]

  def login_with_sms_code(
    self,
    *,
    phone_number: str | None = None,
    sms_code: str,
    international_code: str | None = None,
  ) -> dict[str, Any]:
    target_phone = phone_number or self.state.phone_number
    if not target_phone:
      raise SuningError("phone number is required")
    area_code = international_code or self.state.international_code
    if not self.state.login_ticket:
      raise SuningError("login ticket is missing, send sms code first")
    params = {
      "callback": self._jsonp_callback("smsLogin"),
      "ticket": self.state.login_ticket,
      "phoneNumber": rsa_encrypt_base64(target_phone, self.config.check_account_key),
      "internationalCode": area_code,
      "channel": self.config.channel,
      "smsCode": sms_code,
      "rememberMe": "true",
      "type": "1",
      "sceneId": self._scene_id(area_code),
      "targetUrl": DEFAULT_TARGET_URL,
      "service": "",
      "detect": self.state.detect,
      "secondFlag": "100000000010",
      "dfpToken": self.state.dfp_token,
      "terminal": self.config.channel,
      "createChannel": self._channel(area_code),
      "loginChannel": self._channel(area_code),
      "smsCodeVersion": "1.0",
      "jsonViewType": "true",
      "viewType": "json",
      "loginOrRegFlag": "0",
      "version": "2.0",
    }
    response = self.session.get(
      "https://passport.suning.com/ids/smartLogin/sms",
      params=params,
      timeout=self.timeout,
      headers={"Referer": DEFAULT_LOGIN_URL},
    )
    response.raise_for_status()
    data = parse_jsonp_or_json(response.text)
    if data.get("code") == 302 and data.get("location"):
      location = (
        data["location"]
        .replace("callback=smsLogin", "")
        .replace("viewType=json", "")
        .replace("jsonViewType=true", "")
      )
      self.session.get(location, timeout=self.timeout, allow_redirects=True)
    elif not self._is_login_success(data):
      raise AuthenticationError(data.get("msg") or data.get("res_message") or "sms login failed")
    self.state.login_response = data
    self._touch_state()
    self.bootstrap_service("shcss")
    self.bootstrap_service("itapig")
    return data

  def bootstrap_service(self, service_name: str) -> dict[str, Any]:
    if service_name not in SERVICE_BOOTSTRAP_URLS:
      raise SuningError(f"unsupported service bootstrap: {service_name}")
    response = self.session.get(
      SERVICE_BOOTSTRAP_URLS[service_name],
      timeout=self.timeout,
      allow_redirects=True,
    )
    if "/ids/login" in response.url:
      raise AuthenticationError(f"service bootstrap failed for {service_name}")
    self._touch_state()
    return {
      "service": service_name,
      "status_code": response.status_code,
      "final_url": response.url,
      "history": [item.status_code for item in response.history],
    }

  def query_member_base_info(self) -> dict[str, Any]:
    response = self.session.get(
      MEMBER_BASE_INFO_URL,
      timeout=self.timeout,
      allow_redirects=False,
    )
    if self._is_login_redirect(response):
      self.bootstrap_service("shcss")
      response = self.session.get(
        MEMBER_BASE_INFO_URL,
        timeout=self.timeout,
        allow_redirects=False,
      )
    response.raise_for_status()
    data = response.json()
    if data.get("code") != "0":
      raise AuthenticationError(data.get("desc") or "member base info request failed")
    self._touch_state()
    return data

  def list_families(self) -> dict[str, Any]:
    template = self._find_signed_template("POST", FAMILY_LIST_URL, "")
    if not template:
      raise SuningError(
        "缺少 queryAllFamily 的已签名 HAR 模板，当前无法调用 App 端家庭列表接口。"
      )
    response = self._request_with_signed_template(template, body="")
    response.raise_for_status()
    data = response.json()
    if data.get("responseCode") != "0":
      raise AuthenticationError(data.get("responseMsg") or "list families failed")
    self._touch_state()
    return data

  def list_family_infos(self) -> list[FamilyInfo]:
    payload = self.list_families()
    response_data = payload.get("responseData")
    if isinstance(response_data, list):
      raw_families = response_data
    elif isinstance(response_data, dict):
      raw_families = response_data.get("families") or response_data.get("familyList")
    else:
      raw_families = None
    if not isinstance(raw_families, list):
      raise SuningError("家庭列表返回格式不正确，缺少 families 数组。")

    families: list[FamilyInfo] = []
    for item in raw_families:
      if not isinstance(item, dict):
        raise SuningError("家庭列表项返回格式不正确。")
      family_id = item.get("familyId")
      family_name = item.get("familyName")
      if family_id is None or family_name is None:
        raise SuningError("家庭列表项缺少 familyId 或 familyName。")
      families.append(
        FamilyInfo(
          family_id=str(family_id),
          name=str(family_name),
          raw=item,
        )
      )
    return families

  def list_devices(self, family_id: str | int) -> dict[str, Any]:
    request_body = json.dumps(
      {"familyId": str(family_id)},
      separators=(",", ":"),
      ensure_ascii=False,
    )
    template = self._find_signed_template("POST", DEVICE_LIST_URL, request_body)
    if not template:
      available_family_ids = self.available_device_template_family_ids()
      if available_family_ids:
        raise SuningError(
          "当前 HAR 中没有 familyId="
          f"{family_id} 的设备列表签名模板，可用 familyId: {', '.join(available_family_ids)}"
        )
      raise SuningError(
        "缺少设备列表的已签名 HAR 模板，当前无法调用 App 端设备列表接口。"
      )
    response = self._request_with_signed_template(template, body=request_body)
    response.raise_for_status()
    data = response.json()
    if data.get("responseCode") != "0":
      raise AuthenticationError(data.get("responseMsg") or "list devices failed")
    self._touch_state()
    return data

  def get_device(
    self,
    family_id: str | int,
    *,
    device_id: str | None = None,
  ) -> dict[str, Any]:
    payload = self.list_devices(family_id)
    devices = payload.get("responseData", {}).get("devices") or []
    if not devices:
      raise SuningError(f"familyId={family_id} 下没有设备")

    if device_id:
      for device in devices:
        if str(device.get("id")) == str(device_id):
          return device
      raise SuningError(f"familyId={family_id} 下未找到 deviceId={device_id} 的设备")

    if len(devices) == 1:
      return devices[0]

    climate_candidates = [
      device for device in devices
      if str(device.get("categoryId")) == "0002" or "空调" in str(device.get("name", ""))
    ]
    if len(climate_candidates) == 1:
      return climate_candidates[0]

    device_hints = ", ".join(f"{item.get('id')}:{item.get('name')}" for item in devices)
    raise SuningError(
      f"familyId={family_id} 下有多个设备，请通过 --device-id 指定。可选设备: {device_hints}"
    )

  def get_air_conditioner_status(
    self,
    family_id: str | int,
    *,
    device_id: str | None = None,
  ) -> AirConditionerStatus:
    device = self.get_device(family_id, device_id=device_id)
    return self._normalize_air_conditioner_status(device)

  def list_air_conditioner_statuses(self, family_id: str | int) -> list[AirConditionerStatus]:
    payload = self.list_devices(family_id)
    devices = payload.get("responseData", {}).get("devices")
    if not isinstance(devices, list):
      raise SuningError("设备列表返回格式不正确，缺少 devices 数组。")
    return [
      self._normalize_air_conditioner_status(device)
      for device in devices
      if self._is_air_conditioner_device(device)
    ]

  def _normalize_air_conditioner_status(self, device: dict[str, Any]) -> AirConditionerStatus:
    raw_status = device.get("status") or {}
    online_flag = _coalesce(raw_status.get("onlineStatus"), device.get("online"))
    online = bool(_parse_bool_flag(online_flag))
    summary = _strip_html_text(device.get("p1"))
    power_on = _parse_bool_flag(_coalesce(raw_status.get("SN_POWER"), raw_status.get("C_POWER")))
    current_temperature = _parse_float_value(
      _coalesce(raw_status.get("SN_INDOORTEMP"), raw_status.get("C_INDOORTEMP"))
    )
    target_temperature = _parse_float_value(
      _coalesce(raw_status.get("SN_TEMPERATURE"), raw_status.get("C_TEMPERATURE"))
    )
    outdoor_temperature = _parse_float_value(raw_status.get("C_OUTDOORTEMP"))
    swing_horizontal = _parse_bool_flag(
      _coalesce(raw_status.get("SN_AIRHORIZONTAL"), raw_status.get("C_AIRHORIZONTAL"))
    )
    swing_vertical = _parse_bool_flag(
      _coalesce(raw_status.get("SN_AIRVERTICAL"), raw_status.get("C_AIRVERTICAL"))
    )
    eco_enabled = _parse_bool_flag(_coalesce(raw_status.get("SN_ECO"), raw_status.get("C_ECO")))
    purify_enabled = _parse_bool_flag(raw_status.get("SN_PURIFY"))
    fresh_air_enabled = _parse_bool_flag(raw_status.get("C_FRESHAIR"))
    electric_heating_enabled = _parse_bool_flag(
      _coalesce(raw_status.get("SN_ELECHEATING"), raw_status.get("C_ELECHEATING"))
    )

    status = AirConditionerStatus(
      device_id=str(device.get("id")),
      name=str(device.get("name") or device.get("id") or "unknown-device"),
      model=device.get("model"),
      family_id=str(device.get("fId")) if device.get("fId") is not None else None,
      group_id=str(device.get("gId")) if device.get("gId") is not None else None,
      group_name=device.get("gName"),
      category_id=str(device.get("categoryId")) if device.get("categoryId") is not None else None,
      available=online,
      online=online,
      summary=summary,
      device_record_time=device.get("time"),
      refresh_time=raw_status.get("refreshTime"),
      power_on=power_on,
      current_temperature=current_temperature,
      target_temperature=target_temperature,
      outdoor_temperature=outdoor_temperature,
      mode_raw=_coalesce(raw_status.get("SN_MODE"), raw_status.get("C_MODE")),
      fan_mode_raw=_coalesce(raw_status.get("SN_FANSPEED"), raw_status.get("C_FANSPEED")),
      swing_horizontal=swing_horizontal,
      swing_vertical=swing_vertical,
      eco_enabled=eco_enabled,
      purify_enabled=purify_enabled,
      fresh_air_enabled=fresh_air_enabled,
      electric_heating_enabled=electric_heating_enabled,
      ha_climate_preview=None,
      raw_status=raw_status,
      raw_device=device,
    )
    return status.model_copy(
      update={"ha_climate_preview": self._build_ha_climate_preview(status)}
    )

  def _is_air_conditioner_device(self, device: dict[str, Any]) -> bool:
    return str(device.get("categoryId")) == "0002" or "空调" in str(device.get("name", ""))

  def _build_ha_climate_preview(self, status: AirConditionerStatus) -> HAClimatePreview:
    notes: list[str] = []
    hvac_mode: str | None = None
    if not status.available:
      notes.append("设备当前离线，Home Assistant 中应标记为 unavailable。")
    elif status.power_on is False:
      hvac_mode = "off"

    if status.power_on is True:
      notes.append("设备当前上报为开机，但模式枚举尚未确认，暂不映射标准 HVACMode。")
    elif status.power_on is None:
      notes.append("未能从原始字段中稳定解析电源状态。")

    if status.mode_raw is not None:
      notes.append(f"原始模式值为 {status.mode_raw}，后续需要控制抓包后确认枚举含义。")

    supported_features_preview = [
      feature for feature in [
        "target_temperature" if status.target_temperature is not None else None,
        "current_temperature" if status.current_temperature is not None else None,
        "fan_mode" if status.fan_mode_raw is not None else None,
        "swing_mode"
        if _infer_swing_mode(status.swing_horizontal, status.swing_vertical) is not None
        else None,
        "turn_on_off" if status.power_on is not None else None,
      ]
      if feature is not None
    ]

    return HAClimatePreview(
      entity_domain="climate",
      translation_key="suning_air_conditioner",
      available=status.available,
      hvac_mode=hvac_mode,
      current_temperature=status.current_temperature,
      target_temperature=status.target_temperature,
      fan_mode=status.fan_mode_raw,
      swing_mode=_infer_swing_mode(status.swing_horizontal, status.swing_vertical),
      preset_mode="eco" if status.eco_enabled else None,
      supported_features_preview=supported_features_preview,
      raw_mapping={
        "power": {
          "preferred": "SN_POWER",
          "fallback": "C_POWER",
          "value": status.raw_status.get("SN_POWER") or status.raw_status.get("C_POWER"),
        },
        "mode": {
          "preferred": "SN_MODE",
          "fallback": "C_MODE",
          "value": status.mode_raw,
        },
        "target_temperature": {
          "preferred": "SN_TEMPERATURE",
          "fallback": "C_TEMPERATURE",
          "value": status.raw_status.get("SN_TEMPERATURE") or status.raw_status.get("C_TEMPERATURE"),
        },
        "current_temperature": {
          "preferred": "SN_INDOORTEMP",
          "fallback": "C_INDOORTEMP",
          "value": status.raw_status.get("SN_INDOORTEMP") or status.raw_status.get("C_INDOORTEMP"),
        },
        "fan_mode": {
          "preferred": "SN_FANSPEED",
          "fallback": "C_FANSPEED",
          "value": status.fan_mode_raw,
        },
      },
      notes=notes,
    )

  def keep_alive(self) -> dict[str, Any]:
    member_info = self.query_member_base_info()
    family_info = self.list_families()
    return {
      "member": member_info,
      "families": family_info,
    }

  def save_state(self) -> None:
    if not self.state_path:
      return
    self.state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = PersistedSessionState(
      state=self.state,
      cookies=[_serialize_cookie(cookie) for cookie in self.session.cookies],
    )
    self.state_path.write_text(
      json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
      encoding="utf-8",
    )

  def load_state(self) -> None:
    if not self.state_path or not self.state_path.exists():
      return
    payload = PersistedSessionState.model_validate_json(
      self.state_path.read_text(encoding="utf-8")
    )
    self.state = payload.state
    self.session.cookies.clear()
    for serialized_cookie in payload.cookies:
      self.session.cookies.set_cookie(_restore_cookie(serialized_cookie))

  def load_signed_templates(self) -> None:
    self.signed_templates = {}
    for har_path in self._candidate_har_paths():
      self._load_signed_templates_from_har(har_path)

  def _candidate_har_paths(self) -> list[Path]:
    if self.har_path:
      return [self.har_path]
    return sorted(
      Path.cwd().glob("*.har"),
      key=lambda path: path.stat().st_mtime,
      reverse=True,
    )

  def _load_signed_templates_from_har(self, har_path: Path) -> None:
    if not har_path.exists():
      return
    try:
      payload = json.loads(har_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
      return
    entries = payload.get("log", {}).get("entries", [])
    supported_urls = {
      _normalize_url(FAMILY_LIST_URL),
      _normalize_url(DEVICE_LIST_URL),
      _normalize_url(OPENSH_GET_KEY_URL),
    }
    for entry in entries:
      request = entry.get("request", {})
      method = str(request.get("method", "")).upper()
      url = request.get("url", "")
      normalized_url = _normalize_url(url)
      if normalized_url not in supported_urls or not _har_entry_is_success(entry):
        continue
      headers = _extract_har_headers(entry)
      body = _canonicalize_request_body(
        request.get("postData", {}).get("text"),
        headers.get("Content-Type") or headers.get("content-type"),
      )
      template = SignedRequestTemplate(
        method=method,
        url=normalized_url,
        headers=headers,
        body=body,
        har_path=str(har_path),
      )
      self.signed_templates.setdefault(
        _template_key(method, normalized_url, body),
        template,
      )

  def _find_signed_template(
    self,
    method: str,
    url: str,
    body: str,
  ) -> SignedRequestTemplate | None:
    return self.signed_templates.get(_template_key(method, url, body))

  def _request_with_signed_template(
    self,
    template: SignedRequestTemplate,
    *,
    body: str | None = None,
  ) -> requests.Response:
    payload = template.body if body is None else body
    request_kwargs: dict[str, Any] = {
      "headers": template.build_headers(),
      "timeout": self.timeout,
      "allow_redirects": False,
    }
    if payload:
      request_kwargs["data"] = payload
    response = self.session.request(
      template.method,
      template.url,
      **request_kwargs,
    )
    if self._is_login_redirect(response):
      self.query_member_base_info()
      response = self.session.request(
        template.method,
        template.url,
        **request_kwargs,
      )
    return response

  def available_device_template_family_ids(self) -> list[str]:
    family_ids: set[str] = set()
    for template in self.signed_templates.values():
      if template.method != "POST" or template.url != _normalize_url(DEVICE_LIST_URL):
        continue
      if not template.body:
        continue
      try:
        payload = json.loads(template.body)
      except json.JSONDecodeError:
        continue
      family_id = payload.get("familyId")
      if family_id is not None:
        family_ids.add(str(family_id))
    return sorted(family_ids)

  def _touch_state(self) -> None:
    self.state.updated_at = time.time()
    self.save_state()

  def _decrypt_rdsy_response(self, outer_payload: dict[str, Any]) -> dict[str, Any]:
    encrypted = outer_payload.get("_x_rdsy_resp_")
    if not encrypted:
      raise SuningError("missing _x_rdsy_resp_ in rdsy response")
    return json.loads(self.suaes.decrypt(encrypted))

  def _captcha_fields(self, captcha: CaptchaSolution) -> dict[str, str]:
    mapping = {
      "iar": {
        "uuid": "iarVerifyCode",
        "iarVerifyCode": captcha.value,
        "code": captcha.value,
      },
      "slide": {
        "uuid": "sillerVerifyCode",
        "sillerCode": captcha.value,
        "code": captcha.value,
      },
      "image": {
        "uuid": "19da7909-9b5d-4aee-99ee-28016002eaac",
        "imgCode": captcha.value,
        "code": captcha.value,
      },
    }
    if captcha.kind not in mapping:
      raise SuningError(f"unsupported captcha kind: {captcha.kind}")
    return mapping[captcha.kind]

  def _scene_id(self, international_code: str) -> str:
    if international_code == "00852":
      return self.config.rdsy_scene_id_yghk
    return self.config.rdsy_scene_id

  def _channel(self, international_code: str) -> str:
    if international_code == "00852":
      return "208000104024"
    return "208000103001"

  def _jsonp_callback(self, prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"

  def _is_login_success(self, payload: dict[str, Any]) -> bool:
    return bool(
      payload.get("success")
      or (
        payload.get("res_message") == "SUCCESS"
        and str(payload.get("res_code")) == "0"
      )
    )

  def _is_login_redirect(self, response: requests.Response) -> bool:
    return response.status_code in {301, 302, 303, 307, 308} and "passport.suning.com/ids/login" in (
      response.headers.get("Location", "")
    )


def _build_parser() -> argparse.ArgumentParser:
  def add_shared_arguments(target: argparse.ArgumentParser) -> None:
    target.add_argument("--state-file", default=".suning-session.json")
    target.add_argument("--har-file")
    target.add_argument("--detect")
    target.add_argument("--dfp-token")

  parser = argparse.ArgumentParser(prog="suning-biu-ha")
  add_shared_arguments(parser)
  subparsers = parser.add_subparsers(dest="command", required=True)

  send_sms = subparsers.add_parser("send-sms")
  add_shared_arguments(send_sms)
  send_sms.add_argument("--phone", required=True)
  send_sms.add_argument("--international-code", default="0086")
  send_sms.add_argument("--captcha-kind", choices=["iar", "slide", "image"])
  send_sms.add_argument("--captcha-value")

  login = subparsers.add_parser("login")
  add_shared_arguments(login)
  login.add_argument("--phone", required=True)
  login.add_argument("--sms-code")
  login.add_argument("--international-code", default="0086")
  login.add_argument("--captcha-kind", choices=["iar", "slide", "image"])
  login.add_argument("--captcha-value")

  check = subparsers.add_parser("check")
  add_shared_arguments(check)
  families = subparsers.add_parser("families")
  add_shared_arguments(families)

  devices = subparsers.add_parser("devices")
  add_shared_arguments(devices)
  devices.add_argument("--family-id", required=True)

  device_status = subparsers.add_parser("device-status")
  add_shared_arguments(device_status)
  device_status.add_argument("--family-id", required=True)
  device_status.add_argument("--device-id")
  device_status.add_argument("--raw", action="store_true")

  keep_alive = subparsers.add_parser("keep-alive")
  add_shared_arguments(keep_alive)
  return parser


def _client_from_args(args: argparse.Namespace) -> SuningSmartHomeClient:
  return SuningSmartHomeClient(
    state_path=args.state_file,
    har_path=args.har_file,
    detect=args.detect,
    dfp_token=args.dfp_token,
  )


def _print_payload(payload: Any) -> None:
  print(json.dumps(payload, ensure_ascii=False, indent=2))


def _air_conditioner_status_payload(
  status: AirConditionerStatus,
  *,
  include_raw: bool = False,
) -> dict[str, Any]:
  payload = status.model_dump(mode="json")
  if not include_raw:
    payload.pop("raw_status", None)
    payload.pop("raw_device", None)
  return payload


def _build_captcha_from_args(args: argparse.Namespace) -> CaptchaSolution | None:
  captcha_kind = getattr(args, "captcha_kind", None)
  captcha_value = getattr(args, "captcha_value", None)
  if captcha_kind or captcha_value:
    if not captcha_kind or not captcha_value:
      raise SuningError("captcha-kind 和 captcha-value 必须一起提供")
    return CaptchaSolution(kind=captcha_kind, value=captcha_value)
  return None


def _prompt_nonempty(prompt: str) -> str:
  while True:
    value = input(prompt).strip()
    if value:
      return value
    print("输入不能为空，请重新输入。")


def _captcha_kind_from_risk_type(risk_type: str | None) -> str | None:
  mapping = {
    "isIarVerifyCode": "iar",
    "isSlideVerifyCode": "slide",
    "isImgVerifyCode": "image",
  }
  if not risk_type:
    return None
  return mapping.get(risk_type)


def _send_sms_with_optional_prompt(
  client: SuningSmartHomeClient,
  *,
  phone_number: str,
  international_code: str,
  captcha: CaptchaSolution | None = None,
) -> dict[str, Any]:
  active_captcha = captcha
  while True:
    try:
      return client.send_sms_code(
        phone_number,
        international_code=international_code,
        captcha=active_captcha,
      )
    except CaptchaRequiredError as error:
      captcha_kind = _captcha_kind_from_risk_type(error.risk_type)
      if not captcha_kind:
        print(
          f"发送短信前需要验证码 token，但未识别的 riskType={error.risk_type}。"
        )
        captcha_kind = _prompt_nonempty("请输入验证码类型 (iar/slide/image): ")
        if captcha_kind not in {"iar", "slide", "image"}:
          print("验证码类型只能是 iar、slide 或 image。")
          active_captcha = None
          continue
      else:
        print(
          f"发送短信前需要验证码 token，当前风控类型是 {error.risk_type}，将按 {captcha_kind} 处理。"
        )
      if captcha_kind == "iar":
        captcha_value = _obtain_iar_captcha_token(
          client,
          phone_number=phone_number,
        )
      else:
        captcha_value = _prompt_nonempty("请输入验证码 token: ")
      active_captcha = CaptchaSolution(kind=captcha_kind, value=captcha_value)


def _obtain_iar_captcha_token(
  client: SuningSmartHomeClient,
  *,
  phone_number: str,
) -> str:
  iar_ticket = client.request_iar_verify_code_ticket(phone_number)
  bridge = LocalCaptchaBridge(ticket=iar_ticket)
  bridge.start()
  try:
    print("请在浏览器打开以下链接完成苏宁拼图验证：")
    print(bridge.url)
    print("验证完成后，终端会自动继续。")
    result = bridge.wait_for_token(timeout=300.0)
    print("已收到 IAR 验证结果，继续请求短信。")
    return result.token
  finally:
    bridge.close()


def _interactive_login(
  client: SuningSmartHomeClient,
  *,
  phone_number: str,
  international_code: str,
  sms_code: str | None,
  captcha: CaptchaSolution | None,
) -> dict[str, Any]:
  if sms_code:
    return client.login_with_sms_code(
      phone_number=phone_number,
      sms_code=sms_code,
      international_code=international_code,
    )

  sms_result = _send_sms_with_optional_prompt(
    client,
    phone_number=phone_number,
    international_code=international_code,
    captcha=captcha,
  )
  print("短信验证码已请求发送。")
  _print_payload(
    {
      "status": "sms_sent",
      "riskType": client.state.risk_type,
      "smsTicket": client.state.sms_ticket,
      "loginTicket": client.state.login_ticket,
      "response": sms_result,
    }
  )
  sms_code_input = _prompt_nonempty("请输入收到的短信验证码: ")
  return client.login_with_sms_code(
    phone_number=phone_number,
    sms_code=sms_code_input,
    international_code=international_code,
  )


def main(argv: list[str] | None = None) -> int:
  parser = _build_parser()
  args = parser.parse_args(argv)
  client = _client_from_args(args)
  try:
    if args.command == "send-sms":
      captcha = _build_captcha_from_args(args)
      payload = client.send_sms_code(
        args.phone,
        international_code=args.international_code,
        captcha=captcha,
      )
      _print_payload(
        {
          "status": "sms_sent",
          "riskType": client.state.risk_type,
          "smsTicket": client.state.sms_ticket,
          "loginTicket": client.state.login_ticket,
          "response": payload,
        }
      )
      return 0
    if args.command == "login":
      captcha = _build_captcha_from_args(args)
      payload = _interactive_login(
        client,
        phone_number=args.phone,
        sms_code=args.sms_code,
        international_code=args.international_code,
        captcha=captcha,
      )
      check_result = client.query_member_base_info()
      _print_payload(
        {
          "status": "logged_in",
          "response": payload,
          "member": check_result,
        }
      )
      return 0
    if args.command == "check":
      _print_payload(client.query_member_base_info())
      return 0
    if args.command == "families":
      _print_payload(client.list_families())
      return 0
    if args.command == "devices":
      _print_payload(client.list_devices(args.family_id))
      return 0
    if args.command == "device-status":
      _print_payload(
        _air_conditioner_status_payload(
          client.get_air_conditioner_status(
            args.family_id,
            device_id=args.device_id,
          ),
          include_raw=args.raw,
        )
      )
      return 0
    if args.command == "keep-alive":
      _print_payload(client.keep_alive())
      return 0
  except CaptchaRequiredError as error:
    _print_payload(
      {
        "status": "captcha_required",
        "riskType": error.risk_type,
        "smsTicket": error.sms_ticket,
        "message": str(error),
      }
    )
    return 2
  except SuningError as error:
    _print_payload(
      {
        "status": "error",
        "message": str(error),
      }
    )
    return 1
  return 0
