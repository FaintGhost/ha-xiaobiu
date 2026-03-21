from __future__ import annotations

import json
from urllib.parse import unquote_plus

from xiaobiu import SuningSmartHomeClient, parse_jsonp_or_json
from xiaobiu.client import (
  CaptchaRequiredError,
  CaptchaSolution,
  DEVICE_LIST_URL,
  FAMILY_LIST_URL,
  MOBILE_SMS_LOGIN_APP_CODE,
  MOBILE_SMS_LOGIN_CHANNEL,
  MOBILE_SMS_LOGIN_ORDER_CHANNEL,
  MOBILE_SMS_LOGIN_REMEMBER_ME_TYPE,
  MOBILE_SMS_LOGIN_SCENE_ID,
  SignedRequestTemplate,
  SmsRateLimitedError,
  _air_conditioner_status_payload,
  _build_gs_sign,
  _build_parser,
  _captcha_kind_from_risk_type,
  _send_sms_with_optional_prompt,
  extract_risk_context_script_urls,
  main as client_main,
  parse_login_page_config,
)
from xiaobiu.crypto import SuAESCipher
from xiaobiu.models import CaptchaBridgeResult

SAMPLE_LOGIN_PAGE = """
<script>
var loginPBK="LOGIN_PBK";
var rdsyKey="RDSY_KEY";
var ssojbossConstant = {
  rdsyAppCode:"APP_CODE",
  stepFlag:"STEP_ONE",
  stepTwoFlag:"STEP_TWO",
  rdsySceneId:"PASSPORT",
  rdsySceneIdYGHK:"PASSPORT_YGHK",
  stepThreeFlag:"STEP_THREE",
  channel:"PC",
  checkAccountKey: "CHECK_ACCOUNT_KEY"
};
</script>
"""


def test_parse_login_page_config() -> None:
  config = parse_login_page_config(SAMPLE_LOGIN_PAGE)
  assert config.rdsy_app_code == "APP_CODE"
  assert config.step_two_flag == "STEP_TWO"
  assert config.check_account_key == "CHECK_ACCOUNT_KEY"


def test_extract_risk_context_script_urls() -> None:
  html_text = """
  <script src="https://mmds.suning.com/mmds/mmds.js?appCode=qEmt9X4YmoV2Vye8"></script>
  <script src="https://oss.suning.com/mmds/mmds/js/hash/mmds.bundle.js"></script>
  <script src="https://dfp.suning.com/dfprs-collect/dist/fp.js?appCode=qEmt9X4YmoV2Vye8"></script>
  """

  assert extract_risk_context_script_urls(html_text) == [
    "https://mmds.suning.com/mmds/mmds.js?appCode=qEmt9X4YmoV2Vye8",
    "https://oss.suning.com/mmds/mmds/js/hash/mmds.bundle.js",
    "https://dfp.suning.com/dfprs-collect/dist/fp.js?appCode=qEmt9X4YmoV2Vye8",
  ]


def test_parse_jsonp_or_json_supports_both_formats() -> None:
  assert parse_jsonp_or_json('{"code":"0"}') == {"code": "0"}
  assert parse_jsonp_or_json('smsLogin({"code":"0"})') == {"code": "0"}


def test_state_file_roundtrip(tmp_path) -> None:
  state_path = tmp_path / "session.json"
  client = SuningSmartHomeClient(state_path=state_path)
  client.state.phone_number = "13800000000"
  client.state.sms_ticket = "SMS_TICKET"
  client.session.cookies.set("authId", "cookie-value", domain=".suning.com", path="/")
  client.save_state()

  reloaded = SuningSmartHomeClient(state_path=state_path)
  assert reloaded.state.phone_number == "13800000000"
  assert reloaded.state.sms_ticket == "SMS_TICKET"
  assert reloaded.session.cookies.get("authId", domain=".suning.com", path="/") == "cookie-value"


def test_captcha_field_mapping() -> None:
  client = SuningSmartHomeClient()
  fields = client._captcha_fields(CaptchaSolution(kind="iar", value="token"))  # noqa: SLF001
  assert fields["uuid"] == "iarVerifyCode"
  assert fields["code"] == "token"


def test_mobile_captcha_field_mapping() -> None:
  client = SuningSmartHomeClient()
  fields = client._mobile_captcha_fields(CaptchaSolution(kind="iar", value="token"))  # noqa: SLF001
  assert fields["uuid"] == ""
  assert fields["code"] == "token"
  assert "iarVerifyCode" not in fields


def test_send_sms_with_iar_updates_risk_context(monkeypatch) -> None:
  client = SuningSmartHomeClient()
  client.state.detect = "passport_detect_js_is_error"
  client.state.dfp_token = "passport_dfpToken_js_is_error"
  attempts: list[tuple[str, str, str | None]] = []

  def fake_send_sms_code(phone_number: str, *, international_code: str | None = None, captcha=None):
    attempts.append((client.state.detect, client.state.dfp_token, captcha.value if captcha else None))
    if len(attempts) == 1:
      raise CaptchaRequiredError("isIarVerifyCode", "need captcha")
    return {"status": "COMPLETE", "phone": phone_number, "internationalCode": international_code}

  monkeypatch.setattr(client, "send_sms_code", fake_send_sms_code)
  monkeypatch.setattr(
    "suning_biu_ha.client._obtain_iar_captcha_result",
    lambda *_args, **_kwargs: CaptchaBridgeResult(
      token="iar-token",
      detect="browser-detect",
      dfp_token="browser-dfp",
    ),
  )

  result = _send_sms_with_optional_prompt(
    client,
    phone_number="13800000000",
    international_code="0086",
  )

  assert result["status"] == "COMPLETE"
  assert attempts == [
    ("passport_detect_js_is_error", "passport_dfpToken_js_is_error", None),
    ("browser-detect", "browser-dfp", "iar-token"),
  ]


def test_login_cli_allows_interactive_sms_code() -> None:
  parser = _build_parser()
  args = parser.parse_args(["login", "--phone", "13800000000"])
  assert args.command == "login"
  assert args.phone == "13800000000"
  assert args.sms_code is None


def test_cli_allows_shared_options_after_subcommand() -> None:
  parser = _build_parser()
  args = parser.parse_args(["families", "--har-file", "sample.har"])
  assert args.command == "families"
  assert args.har_file == "sample.har"


def test_cli_supports_device_status_command() -> None:
  parser = _build_parser()
  args = parser.parse_args(["device-status", "--family-id", "37790", "--device-id", "abc", "--raw"])
  assert args.command == "device-status"
  assert args.family_id == "37790"
  assert args.device_id == "abc"
  assert args.raw is True


def test_risk_type_to_captcha_kind_mapping() -> None:
  assert _captcha_kind_from_risk_type("isIarVerifyCode") == "iar"
  assert _captcha_kind_from_risk_type("isSlideVerifyCode") == "slide"
  assert _captcha_kind_from_risk_type("isImgVerifyCode") == "image"
  assert _captcha_kind_from_risk_type("unknown") is None


def test_signed_request_template_refreshes_trace_headers() -> None:
  template = SignedRequestTemplate(
    method="POST",
    url=FAMILY_LIST_URL,
    headers={
      "snTraceId": "old-trace",
      "hiro_trace_id": "old-trace",
      "requestTime": "1773960376923",
      "gsSign": "family-sign",
    },
  )

  headers = template.build_headers()

  assert headers["requestTime"] == "1773960376923"
  assert headers["gsSign"] == "family-sign"
  assert headers["snTraceId"] != "old-trace"
  assert headers["hiro_trace_id"] == headers["snTraceId"]


def test_build_gs_sign_matches_reverse_engineered_android_samples() -> None:
  assert _build_gs_sign("/api/trade/shcss/queryAllFamily", "1773960376923", "") == (
    "77942dbc20f6f23c0db611c070c186d0a7132c4d713f34c8e2e5b4aa34aa42f2"
  )
  assert _build_gs_sign(
    "/api/trade/shcss/all",
    "1773960378601",
    '{\n  "familyId" : "37790"\n}',
  ) == "1d6a60bf746cef243d0c3d7c595d172fc71013e707171ffd77fd7f4f87611967"


def test_client_does_not_auto_scan_har_files_without_explicit_path(tmp_path, monkeypatch) -> None:
  har_path = tmp_path / "signed.har"
  har_path.write_text("{}", encoding="utf-8")
  monkeypatch.chdir(tmp_path)

  client = SuningSmartHomeClient()

  assert client.signed_templates == {}


def test_client_loads_signed_templates_from_har(tmp_path) -> None:
  har_path = tmp_path / "signed.har"
  har_payload = {
    "log": {
      "entries": [
        {
          "request": {
            "method": "POST",
            "url": FAMILY_LIST_URL,
            "headers": [
              {"name": "TerminalVersion", "value": "SmartHome/6.4.5"},
              {"name": "hiro_trace_id", "value": "trace-family"},
              {"name": "snTraceId", "value": "trace-family"},
              {"name": "gsSign", "value": "family-sign"},
              {"name": "requestTime", "value": "1773960376923"},
              {"name": "terminalType", "value": "SHCSS_IOS"},
              {"name": "snTraceType", "value": "SDK"},
              {"name": "User-Agent", "value": "SmartHome/6.4.5"},
              {"name": "Content-Type", "value": "application/json"},
            ],
          },
          "response": {
            "status": 200,
            "content": {
              "text": json.dumps({"responseCode": "0", "responseMsg": "SUCCESS"}),
            },
          },
        },
        {
          "request": {
            "method": "POST",
            "url": DEVICE_LIST_URL,
            "headers": [
              {"name": "TerminalVersion", "value": "SmartHome/6.4.5"},
              {"name": "hiro_trace_id", "value": "trace-device"},
              {"name": "snTraceId", "value": "trace-device"},
              {"name": "gsSign", "value": "device-sign"},
              {"name": "requestTime", "value": "1773960378601"},
              {"name": "terminalType", "value": "SHCSS_IOS"},
              {"name": "snTraceType", "value": "SDK"},
              {"name": "User-Agent", "value": "SmartHome/6.4.5"},
              {"name": "Content-Type", "value": "application/json"},
            ],
            "postData": {
              "mimeType": "application/json",
              "text": '{\n  "familyId" : "37790"\n}',
            },
          },
          "response": {
            "status": 200,
            "content": {
              "text": json.dumps({"responseCode": "0", "responseMsg": "SUCCESS"}),
            },
          },
        },
      ]
    }
  }
  har_path.write_text(json.dumps(har_payload), encoding="utf-8")

  client = SuningSmartHomeClient(har_path=har_path)

  family_template = client._find_signed_template("POST", FAMILY_LIST_URL, "")  # noqa: SLF001
  device_template = client._find_signed_template(  # noqa: SLF001
    "POST",
    DEVICE_LIST_URL,
    '{"familyId":"37790"}',
  )

  assert family_template is not None
  assert family_template.headers["gsSign"] == "family-sign"
  assert device_template is not None
  assert device_template.headers["gsSign"] == "device-sign"
  assert client.available_device_template_family_ids() == ["37790"]


def test_list_families_builds_dynamic_signed_request(monkeypatch) -> None:
  client = SuningSmartHomeClient()
  captured: dict[str, object] = {}

  class FakeResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
      return None

    def json(self) -> dict[str, object]:
      return {
        "responseCode": "0",
        "responseData": {
          "families": [{"familyId": "37790", "familyName": "我的家"}],
        },
      }

  def fake_request(method: str, url: str, **kwargs):
    captured["method"] = method
    captured["url"] = url
    captured["kwargs"] = kwargs
    return FakeResponse()

  monkeypatch.setattr(client.session, "request", fake_request)

  payload = client.list_families()

  kwargs = captured["kwargs"]
  headers = kwargs["headers"]
  assert captured["method"] == "POST"
  assert captured["url"] == FAMILY_LIST_URL
  assert kwargs["data"] == ""
  assert headers["Content-Type"] == "application/json"
  assert headers["TerminalVersion"] == client.app_user_agent
  assert headers["User-Agent"] == client.app_user_agent
  assert headers["terminalType"] == client.app_terminal_type
  assert headers["gsSign"] == _build_gs_sign(
    "/api/trade/shcss/queryAllFamily",
    headers["requestTime"],
    kwargs["data"],
  )
  assert payload["responseCode"] == "0"


def test_list_devices_builds_dynamic_signed_request(monkeypatch) -> None:
  client = SuningSmartHomeClient()
  captured: dict[str, object] = {}

  class FakeResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
      return None

    def json(self) -> dict[str, object]:
      return {"responseCode": "0", "responseData": {"devices": []}}

  def fake_request(method: str, url: str, **kwargs):
    captured["method"] = method
    captured["url"] = url
    captured["kwargs"] = kwargs
    return FakeResponse()

  monkeypatch.setattr(client.session, "request", fake_request)

  payload = client.list_devices("37790")

  kwargs = captured["kwargs"]
  headers = kwargs["headers"]
  assert captured["method"] == "POST"
  assert captured["url"] == DEVICE_LIST_URL
  assert kwargs["data"] == '{"familyId":"37790"}'
  assert headers["Content-Type"] == "application/json"
  assert headers["gsSign"] == _build_gs_sign(
    "/api/trade/shcss/all",
    headers["requestTime"],
    kwargs["data"],
  )
  assert payload["responseCode"] == "0"


def test_prepare_sms_login_uses_mobile_post_form(monkeypatch) -> None:
  client = SuningSmartHomeClient()
  cipher = SuAESCipher()
  captured: dict[str, object] = {}

  monkeypatch.setattr(client, "initialize", lambda: client.config)

  expected_inner = {
    "status": "COMPLETE",
    "data": {
      "ticket": "sms-ticket",
      "riskType": "isIarVerifyCode",
    },
  }

  class FakeResponse:
    text = json.dumps(
      {
        "_x_rdsy_resp_": cipher.encrypt(
          json.dumps(expected_inner, separators=(",", ":"), ensure_ascii=False)
        )
      },
      ensure_ascii=False,
    )

    def raise_for_status(self) -> None:
      return None

  def fake_post(url: str, **kwargs):
    captured["url"] = url
    captured["kwargs"] = kwargs
    payload = kwargs["data"]
    block = payload["_x_rdsy_block_"]
    captured["request_json"] = json.loads(cipher.decrypt(unquote_plus(block)))
    return FakeResponse()

  monkeypatch.setattr(client.session, "post", fake_post)

  result = client.prepare_sms_login("13800000000")

  request_json = captured["request_json"]
  kwargs = captured["kwargs"]
  assert captured["url"] == "https://rdsy.suning.com/rdsy/needVerifyCode.do"
  assert kwargs["data"]["callback"] == ""
  assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
  assert request_json["sceneId"] == MOBILE_SMS_LOGIN_SCENE_ID
  assert request_json["appCode"] == MOBILE_SMS_LOGIN_APP_CODE
  assert request_json["data"]["channel"] == MOBILE_SMS_LOGIN_CHANNEL
  assert request_json["data"]["orderChannel"] == MOBILE_SMS_LOGIN_ORDER_CHANNEL
  assert request_json["data"]["subMode"] == "11"
  assert request_json["data"]["loginTheme"] == "zn"
  assert result == expected_inner


def test_send_sms_code_uses_mobile_iar_payload(monkeypatch) -> None:
  client = SuningSmartHomeClient()
  cipher = SuAESCipher()
  client.state.phone_number = "13800000000"
  client.state.sms_ticket = "sms-ticket"
  client.state.risk_type = "isIarVerifyCode"
  captured: dict[str, object] = {}

  expected_inner = {
    "status": "COMPLETE",
    "data": {"ticket": "login-ticket"},
  }

  class FakeResponse:
    text = json.dumps(
      {
        "_x_rdsy_resp_": cipher.encrypt(
          json.dumps(expected_inner, separators=(",", ":"), ensure_ascii=False)
        )
      },
      ensure_ascii=False,
    )

    def raise_for_status(self) -> None:
      return None

  def fake_post(url: str, **kwargs):
    captured["url"] = url
    captured["kwargs"] = kwargs
    payload = kwargs["data"]
    block = payload["_x_rdsy_block_"]
    captured["request_json"] = json.loads(cipher.decrypt(unquote_plus(block)))
    return FakeResponse()

  monkeypatch.setattr(client.session, "post", fake_post)

  result = client.send_sms_code(
    captcha=CaptchaSolution(kind="iar", value="iar-token"),
  )

  request_json = captured["request_json"]
  kwargs = captured["kwargs"]
  assert captured["url"] == "https://rdsy.suning.com/rdsy/sendCode.do"
  assert kwargs["data"]["callback"] == ""
  assert request_json["sceneId"] == MOBILE_SMS_LOGIN_SCENE_ID
  assert request_json["appCode"] == MOBILE_SMS_LOGIN_APP_CODE
  assert request_json["riskType"] == "isIarVerifyCode"
  assert request_json["uuid"] == ""
  assert request_json["code"] == "iar-token"
  assert "iarVerifyCode" not in request_json
  assert result == expected_inner
  assert client.state.login_ticket == "login-ticket"
  assert client.state.risk_type is None


def test_send_sms_code_raises_sms_rate_limited_error(monkeypatch) -> None:
  client = SuningSmartHomeClient()
  cipher = SuAESCipher()
  client.state.phone_number = "13800000000"
  client.state.sms_ticket = "sms-ticket"
  client.state.risk_type = "isIarVerifyCode"

  expected_inner = {
    "status": "FAIL",
    "msg": "验证码发送失败，请稍后重试(00201)",
  }

  class FakeResponse:
    text = json.dumps(
      {
        "_x_rdsy_resp_": cipher.encrypt(
          json.dumps(expected_inner, separators=(",", ":"), ensure_ascii=False)
        )
      },
      ensure_ascii=False,
    )

    def raise_for_status(self) -> None:
      return None

  monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: FakeResponse())

  try:
    client.send_sms_code(
      captcha=CaptchaSolution(kind="iar", value="iar-token"),
    )
  except Exception as error:  # noqa: BLE001
    assert error.__class__.__name__ == "SmsRateLimitedError"
    assert str(error) == "验证码发送失败，请稍后重试(00201)"
  else:
    raise AssertionError("expected sms send to fail with rate limited error")


def test_login_main_reports_sms_rate_limited(monkeypatch, capsys) -> None:
  fake_client = object()

  monkeypatch.setattr("suning_biu_ha.client._client_from_args", lambda _args: fake_client)
  monkeypatch.setattr(
    "suning_biu_ha.client._interactive_login",
    lambda *_args, **_kwargs: (_ for _ in ()).throw(
      SmsRateLimitedError("验证码发送失败，请稍后重试(00201)")
    ),
  )

  exit_code = client_main(["login", "--phone", "13800000000"])

  payload = json.loads(capsys.readouterr().out)
  assert exit_code == 1
  assert payload["status"] == "sms_rate_limited"
  assert payload["errorCode"] == "00201"
  assert payload["message"] == "短信发送过于频繁，请稍后再试。"
  assert payload["detail"] == "验证码发送失败，请稍后重试(00201)"


def test_login_with_sms_code_uses_mobile_post_form(monkeypatch) -> None:
  client = SuningSmartHomeClient()
  client.state.phone_number = "13800000000"
  client.state.international_code = "0086"
  client.state.login_ticket = "login-ticket"
  captured: dict[str, object] = {}

  class FakeResponse:
    text = json.dumps({"res_message": "SUCCESS", "res_code": "0"}, ensure_ascii=False)

    def raise_for_status(self) -> None:
      return None

  def fake_post(url: str, **kwargs):
    captured["url"] = url
    captured["kwargs"] = kwargs
    return FakeResponse()

  monkeypatch.setattr(client.session, "post", fake_post)
  monkeypatch.setattr(client, "bootstrap_service", lambda service_name: {"service": service_name})

  result = client.login_with_sms_code(
    phone_number="13800000000",
    sms_code="123456",
  )

  params = captured["kwargs"]["data"]
  assert captured["url"] == "https://passport.suning.com/ids/smartLogin/sms"
  assert captured["kwargs"]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
  assert params["sceneId"] == MOBILE_SMS_LOGIN_SCENE_ID
  assert params["terminal"] == MOBILE_SMS_LOGIN_CHANNEL
  assert params["loginChannel"] == MOBILE_SMS_LOGIN_ORDER_CHANNEL
  assert params["rememberMeType"] == MOBILE_SMS_LOGIN_REMEMBER_ME_TYPE
  assert params["stepFlag"] == client.config.step_three_flag
  assert "callback" not in params
  assert result["res_code"] == "0"


def test_list_family_infos_parses_expected_payload_shape(monkeypatch) -> None:
  client = SuningSmartHomeClient()

  def fake_list_families() -> dict[str, object]:
    return {
      "responseCode": "0",
      "responseData": {
        "families": [
          {"familyId": "37790", "familyName": "我的家"},
        ]
      },
    }

  monkeypatch.setattr(client, "list_families", fake_list_families)

  families = client.list_family_infos()

  assert len(families) == 1
  assert families[0].family_id == "37790"
  assert families[0].name == "我的家"


def test_list_family_infos_accepts_id_field_from_live_api(monkeypatch) -> None:
  client = SuningSmartHomeClient()

  def fake_list_families() -> dict[str, object]:
    return {
      "responseCode": "0",
      "responseData": [
        {
          "id": 37790,
          "familyName": "139******39的家",
        }
      ],
    }

  monkeypatch.setattr(client, "list_families", fake_list_families)

  families = client.list_family_infos()

  assert len(families) == 1
  assert families[0].family_id == "37790"
  assert families[0].name == "139******39的家"


def test_list_air_conditioner_statuses_filters_non_climate_devices(monkeypatch) -> None:
  client = SuningSmartHomeClient()

  def fake_list_devices(family_id: str | int) -> dict[str, object]:
    assert str(family_id) == "37790"
    return {
      "responseData": {
        "devices": [
          {
            "id": "ac-1",
            "name": "卧室空调",
            "online": "0",
            "categoryId": "0002",
            "status": {"onlineStatus": "0"},
          },
          {
            "id": "light-1",
            "name": "客厅灯",
            "online": "1",
            "categoryId": "0001",
            "status": {"onlineStatus": "1"},
          },
        ]
      }
    }

  monkeypatch.setattr(client, "list_devices", fake_list_devices)

  statuses = client.list_air_conditioner_statuses("37790")

  assert [status.device_id for status in statuses] == ["ac-1"]
  assert statuses[0].ha_climate_preview is not None


def test_normalize_air_conditioner_status_builds_ha_preview() -> None:
  client = SuningSmartHomeClient()
  raw_device = {
    "id": "000165f9b029afa2e5d8",
    "name": "惠而浦空调",
    "model": "0001000200150000",
    "online": "0",
    "gId": "1274540",
    "gName": "卧室",
    "fId": "37790",
    "time": "2024-08-18 10:47:57",
    "p1": "<font color='#999999'>已离线</font>",
    "categoryId": "0002",
    "status": {
      "refreshTime": "20251109204142",
      "onlineStatus": "0",
      "SN_POWER": "1",
      "SN_INDOORTEMP": "29.3",
      "SN_MODE": "3",
      "C_AIRHORIZONTAL": "1",
      "C_AIRVERTICAL": "1",
      "SN_TEMPERATURE": "29.3",
      "SN_FANSPEED": "0",
      "SN_ECO": "0",
      "SN_PURIFY": "0",
      "C_FRESHAIR": "0",
      "SN_ELECHEATING": "0",
    },
  }

  status = client._normalize_air_conditioner_status(raw_device)  # noqa: SLF001

  assert status.device_id == "000165f9b029afa2e5d8"
  assert status.available is False
  assert status.online is False
  assert status.summary == "已离线"
  assert status.power_on is True
  assert status.current_temperature == 29.3
  assert status.target_temperature == 29.3
  assert status.swing_horizontal is True
  assert status.swing_vertical is True
  assert status.ha_climate_preview is not None
  assert status.ha_climate_preview.entity_domain == "climate"
  assert status.ha_climate_preview.available is False
  assert status.ha_climate_preview.swing_mode == "both"
  assert status.ha_climate_preview.hvac_mode is None
  assert "设备当前离线" in " ".join(status.ha_climate_preview.notes)

  compact_payload = _air_conditioner_status_payload(status, include_raw=False)
  assert "raw_device" not in compact_payload
  assert "raw_status" not in compact_payload

  debug_payload = _air_conditioner_status_payload(status, include_raw=True)
  assert "raw_device" in debug_payload
  assert "raw_status" in debug_payload
