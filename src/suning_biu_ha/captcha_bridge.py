from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .models import CaptchaBridgeResult

DEFAULT_RISK_CONTEXT_SCRIPT_URLS = [
  "https://mmds.suning.com/mmds/mmds.js?appCode=qEmt9X4YmoV2Vye8",
  "https://oss.suning.com/mmds/mmds/js/sK1di3Hh1vIKsdA/mmds.XsWjliU4H7uskWk.js",
  "https://dfp.suning.com/dfprs-collect/dist/fp.js?appCode=qEmt9X4YmoV2Vye8",
]

HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>苏宁验证码验证</title>
  <script src="https://iar-web.suning.com/iar-web/snstatic/SnCaptcha.js"></script>
  <script>
    window.__RISK_CONTEXT_SCRIPT_URLS__ = {script_urls_json};
    window.__CAPTCHA_CALLBACK_URL__ = {callback_url_json};
  </script>
  <style>
    * {{
      box-sizing: border-box;
    }}
    html {{
      min-height: 100%;
      background: linear-gradient(180deg, #fff8ee 0%, #fff 100%);
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #222;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      padding: 24px 16px 40px;
      overflow-y: auto;
    }}
    .card {{
      width: min(96vw, 520px);
      background: #fff;
      border: 1px solid #f3d9b8;
      border-radius: 16px;
      box-shadow: 0 18px 48px rgba(197, 112, 26, 0.12);
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 20px;
    }}
    p {{
      margin: 0 0 16px;
      line-height: 1.6;
      color: #555;
    }}
    .captcha-shell {{
      display: flex;
      justify-content: center;
      width: 100%;
      overflow: visible;
    }}
    #captcha {{
      width: 100%;
      min-height: 320px;
      overflow: visible;
    }}
    .status {{
      margin-top: 16px;
      font-size: 14px;
      color: #8a4b00;
      white-space: pre-wrap;
    }}
    .status.ok {{
      color: #0f7b0f;
    }}
    .status.err {{
      color: #b42318;
    }}
    @media (max-width: 640px) {{
      body {{
        padding: 12px 10px 24px;
      }}
      .card {{
        width: 100%;
        padding: 16px;
        border-radius: 12px;
      }}
      #captcha {{
        min-height: 280px;
      }}
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>苏宁拼图验证</h1>
    <p>完成下方验证后，这个页面会自动把结果回传给本地程序。成功后回到终端等待后续提示即可。</p>
    <div class="captcha-shell">
      <div id="captcha"></div>
    </div>
    <div id="status" class="status">正在加载验证码...</div>
  </div>
  <script>
    const statusEl = document.getElementById("status");
    const cardEl = document.querySelector(".card");
    const riskContextScripts = window.__RISK_CONTEXT_SCRIPT_URLS__ || [];
    const callbackUrl = window.__CAPTCHA_CALLBACK_URL__ || "/callback";
    async function loadScript(src) {{
      await new Promise((resolve, reject) => {{
        const script = document.createElement("script");
        script.src = src;
        script.async = false;
        script.onload = resolve;
        script.onerror = function() {{
          reject(new Error("load failed: " + src));
        }};
        document.head.appendChild(script);
      }});
    }}
    async function sleep(ms) {{
      await new Promise((resolve) => window.setTimeout(resolve, ms));
    }}
    function readRiskContextOnce() {{
      let detect = "";
      let dfpToken = "";
      try {{
        if (typeof bd === "object" && typeof bd.rst === "function") {{
          detect = bd.rst({{ scene: "1" }}) || "";
        }}
      }} catch (error) {{
        console.warn("collect detect failed", error);
      }}
      try {{
        if (typeof _dfp === "object" && typeof _dfp.getToken === "function") {{
          dfpToken = _dfp.getToken() || "";
        }}
      }} catch (error) {{
        console.warn("collect dfp token failed", error);
      }}
      return {{ detect, dfpToken }};
    }}
    async function collectRiskContext() {{
      for (const src of riskContextScripts) {{
        await loadScript(src);
      }}
      const deadline = Date.now() + 10000;
      let lastRiskContext = readRiskContextOnce();
      while (Date.now() < deadline) {{
        if (lastRiskContext.detect && lastRiskContext.dfpToken) {{
          return lastRiskContext;
        }}
        await sleep(250);
        lastRiskContext = readRiskContextOnce();
      }}
      throw new Error("未能采集浏览器风控上下文，请刷新页面后重试。");
    }}
    function computeCaptchaSize() {{
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 390;
      const availableWidth = Math.max(300, Math.min(viewportWidth - 56, cardEl.clientWidth - 48, 420));
      const width = Math.round(availableWidth);
      const height = Math.max(300, Math.round(width * 0.88));
      return {{
        width: width + "px",
        height: height + "px"
      }};
    }}
    function setStatus(message, klass) {{
      statusEl.textContent = message;
      statusEl.className = "status" + (klass ? " " + klass : "");
    }}
    let captchaSubmitStarted = false;
    const captchaSize = computeCaptchaSize();
    const captchaEl = document.getElementById("captcha");
    captchaEl.style.width = captchaSize.width;
    captchaEl.style.minHeight = captchaSize.height;
    const riskContextPromise = collectRiskContext();
    SnCaptcha.init({{
      env: "{env}",
      target: "captcha",
      ticket: "{ticket}",
      client: "app",
      width: captchaSize.width,
      height: captchaSize.height,
      callback: async function(token) {{
        if (captchaSubmitStarted) {{
          return;
        }}
        captchaSubmitStarted = true;
        try {{
          setStatus("验证成功，正在回传结果...", "");
          const riskContext = await riskContextPromise;
          if (!riskContext.detect || !riskContext.dfpToken) {{
            throw new Error("浏览器风控上下文不完整，请刷新页面后重试。");
          }}
          const response = await fetch(callbackUrl, {{
            method: "POST",
            headers: {{
              "Content-Type": "application/json"
            }},
            body: JSON.stringify({{
              token,
              detect: riskContext.detect,
              dfpToken: riskContext.dfpToken
            }})
          }});
          if (!response.ok) {{
            throw new Error("回传失败: " + response.status);
          }}
          setStatus("验证成功，已经回传给本地程序。可以回到终端继续。", "ok");
        }} catch (error) {{
          captchaSubmitStarted = false;
          setStatus("验证码已完成，但回传失败，请把浏览器和终端错误一起反馈。\\n" + error, "err");
        }}
      }},
      onready: function() {{
        setStatus("验证码已加载，请按页面提示完成验证。", "");
      }},
      onClose: function() {{
        setStatus("验证码窗口已关闭，如未成功请重新打开终端输出的链接。", "");
      }}
    }});
  </script>
</body>
</html>
"""


def render_captcha_page(
  *,
  ticket: str,
  env: str = "prd",
  script_urls: list[str] | None = None,
  callback_url: str = "/callback",
) -> str:
  return HTML_TEMPLATE.format(
    env=env,
    ticket=ticket,
    script_urls_json=json.dumps(
      script_urls or DEFAULT_RISK_CONTEXT_SCRIPT_URLS,
      ensure_ascii=False,
    ),
    callback_url_json=json.dumps(callback_url, ensure_ascii=False),
  )

class _ThreadedHTTPServer(ThreadingHTTPServer):
  daemon_threads = True


class LocalCaptchaBridge:
  def __init__(
    self,
    *,
    ticket: str,
    env: str = "prd",
    host: str = "127.0.0.1",
    port: int = 0,
    script_urls: list[str] | None = None,
  ) -> None:
    self.ticket = ticket
    self.env = env
    self.host = host
    self.port = port
    self.script_urls = script_urls or DEFAULT_RISK_CONTEXT_SCRIPT_URLS
    self._result: CaptchaBridgeResult | None = None
    self._event = threading.Event()
    self._server = self._create_server()
    self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

  @property
  def url(self) -> str:
    host, port = self._server.server_address[:2]
    return f"http://{host}:{port}/"

  def start(self) -> None:
    self._thread.start()

  def wait_for_token(self, timeout: float = 300.0) -> CaptchaBridgeResult:
    completed = self._event.wait(timeout)
    if not completed or not self._result:
      raise TimeoutError("等待验证码结果超时")
    return self._result

  def close(self) -> None:
    self._server.shutdown()
    self._server.server_close()
    if self._thread.is_alive():
      self._thread.join(timeout=1.0)

  def _create_server(self) -> _ThreadedHTTPServer:
    bridge = self

    class Handler(BaseHTTPRequestHandler):
      def log_message(self, format: str, *args: Any) -> None:
        return

      def do_GET(self) -> None:
        if self.path != "/":
          self.send_error(HTTPStatus.NOT_FOUND)
          return
        html = render_captcha_page(
          env=bridge.env,
          script_urls=bridge.script_urls,
          callback_url="/callback",
          ticket=bridge.ticket,
        )
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

      def do_POST(self) -> None:
        if self.path != "/callback":
          self.send_error(HTTPStatus.NOT_FOUND)
          return
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        payload = json.loads(raw_body.decode("utf-8"))
        token = (payload.get("token") or "").strip()
        detect = (payload.get("detect") or "").strip()
        dfp_token = (payload.get("dfpToken") or "").strip()
        if not token:
          self.send_error(HTTPStatus.BAD_REQUEST, "missing token")
          return
        if not detect or not dfp_token:
          self.send_error(HTTPStatus.BAD_REQUEST, "missing risk context")
          return
        bridge._result = CaptchaBridgeResult(
          token=token,
          detect=detect,
          dfp_token=dfp_token,
        )
        bridge._event.set()
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    return _ThreadedHTTPServer((self.host, self.port), Handler)
