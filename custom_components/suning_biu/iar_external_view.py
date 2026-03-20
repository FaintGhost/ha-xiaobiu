from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from secrets import token_urlsafe

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .suning_biu_ha.captcha_bridge import (
  DEFAULT_RISK_CONTEXT_SCRIPT_URLS,
  render_captcha_page,
)

DATA_IAR_CAPTCHA_SESSIONS = f"{DOMAIN}_iar_captcha_sessions"
DATA_IAR_CAPTCHA_VIEW_REGISTERED = f"{DOMAIN}_iar_captcha_view_registered"


@dataclass(slots=True)
class IARCaptchaResult:
  token: str
  detect: str | None = None
  dfp_token: str | None = None


@dataclass(slots=True)
class IARCaptchaSession:
  flow_id: str
  nonce: str
  ticket: str
  script_urls: list[str] = field(
    default_factory=lambda: list(DEFAULT_RISK_CONTEXT_SCRIPT_URLS)
  )
  env: str = "prd"
  result: IARCaptchaResult | None = None
  resume_requested: bool = False

  @property
  def path(self) -> str:
    return f"/api/{DOMAIN}/iar/{self.flow_id}/{self.nonce}"


def _sessions(hass: HomeAssistant) -> dict[str, IARCaptchaSession]:
  return hass.data.setdefault(DATA_IAR_CAPTCHA_SESSIONS, {})


def async_ensure_iar_captcha_view_registered(hass: HomeAssistant) -> None:
  if hass.data.get(DATA_IAR_CAPTCHA_VIEW_REGISTERED):
    return
  hass.http.register_view(SuningIARCaptchaView())
  hass.data[DATA_IAR_CAPTCHA_VIEW_REGISTERED] = True


def async_create_iar_captcha_session(
  hass: HomeAssistant,
  *,
  flow_id: str,
  ticket: str,
  script_urls: list[str] | None = None,
  env: str = "prd",
) -> IARCaptchaSession:
  async_ensure_iar_captcha_view_registered(hass)
  session = IARCaptchaSession(
    flow_id=flow_id,
    nonce=token_urlsafe(18),
    ticket=ticket,
    script_urls=list(script_urls or DEFAULT_RISK_CONTEXT_SCRIPT_URLS),
    env=env,
  )
  _sessions(hass)[flow_id] = session
  return session


def async_get_iar_captcha_session(
  hass: HomeAssistant,
  flow_id: str,
) -> IARCaptchaSession | None:
  return _sessions(hass).get(flow_id)


def async_remove_iar_captcha_session(hass: HomeAssistant, flow_id: str) -> None:
  _sessions(hass).pop(flow_id, None)


def async_pop_iar_captcha_session(
  hass: HomeAssistant,
  flow_id: str,
) -> IARCaptchaSession | None:
  return _sessions(hass).pop(flow_id, None)


class SuningIARCaptchaView(HomeAssistantView):
  # External step opens a plain URL in the browser, so this view cannot rely on
  # Home Assistant's bearer-token request path. The flow_id + nonce pair acts as
  # a one-time capability URL scoped to the current config flow.
  requires_auth = False
  url = f"/api/{DOMAIN}/iar/{{flow_id}}/{{nonce}}"
  name = f"api:{DOMAIN}:iar"

  def _get_session(
    self,
    hass: HomeAssistant,
    flow_id: str,
    nonce: str,
  ) -> IARCaptchaSession | None:
    session = async_get_iar_captcha_session(hass, flow_id)
    if session is None or session.nonce != nonce:
      return None
    return session

  async def get(
    self,
    request: web.Request,
    flow_id: str,
    nonce: str,
  ) -> web.Response:
    hass = request.app[KEY_HASS]
    session = self._get_session(hass, flow_id, nonce)
    if session is None:
      return self.json_message("captcha session not found", HTTPStatus.NOT_FOUND)
    body = render_captcha_page(
      ticket=session.ticket,
      env=session.env,
      script_urls=session.script_urls,
      callback_url=session.path,
    )
    return web.Response(text=body, content_type="text/html")

  async def post(
    self,
    request: web.Request,
    flow_id: str,
    nonce: str,
  ) -> web.Response:
    hass = request.app[KEY_HASS]
    session = self._get_session(hass, flow_id, nonce)
    if session is None:
      return self.json_message("captcha session not found", HTTPStatus.NOT_FOUND)
    try:
      payload = await request.json()
    except ValueError:
      return self.json_message("invalid JSON", HTTPStatus.BAD_REQUEST)
    token = (payload.get("token") or "").strip()
    detect = (payload.get("detect") or "").strip()
    dfp_token = (payload.get("dfpToken") or "").strip()
    if not token:
      return self.json_message("missing token", HTTPStatus.BAD_REQUEST)
    if not detect or not dfp_token:
      return self.json_message("missing risk context", HTTPStatus.BAD_REQUEST)
    if session.resume_requested:
      return self.json({"ok": True, "duplicate": True})
    session.result = IARCaptchaResult(
      token=token,
      detect=detect,
      dfp_token=dfp_token,
    )
    session.resume_requested = True
    hass.async_create_task(hass.config_entries.flow.async_configure(flow_id=flow_id))
    return self.json({"ok": True})
