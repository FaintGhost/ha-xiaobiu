from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .models import CaptchaBridgeResult


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>苏宁验证码验证</title>
  <script src="https://iar-web.suning.com/iar-web/snstatic/SnCaptcha.js"></script>
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
    const captchaSize = computeCaptchaSize();
    const captchaEl = document.getElementById("captcha");
    captchaEl.style.width = captchaSize.width;
    captchaEl.style.minHeight = captchaSize.height;
    SnCaptcha.init({{
      env: "{env}",
      target: "captcha",
      ticket: "{ticket}",
      client: "app",
      width: captchaSize.width,
      height: captchaSize.height,
      callback: async function(token) {{
        try {{
          setStatus("验证成功，正在回传结果...", "");
          const response = await fetch("/callback", {{
            method: "POST",
            headers: {{
              "Content-Type": "application/json"
            }},
            body: JSON.stringify({{ token }})
          }});
          if (!response.ok) {{
            throw new Error("回传失败: " + response.status);
          }}
          setStatus("验证成功，已经回传给本地程序。可以回到终端继续。", "ok");
        }} catch (error) {{
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
  ) -> None:
    self.ticket = ticket
    self.env = env
    self.host = host
    self.port = port
    self._token: str | None = None
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
    if not completed or not self._token:
      raise TimeoutError("等待验证码结果超时")
    return CaptchaBridgeResult(token=self._token)

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
        html = HTML_TEMPLATE.format(env=bridge.env, ticket=bridge.ticket)
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
        if not token:
          self.send_error(HTTPStatus.BAD_REQUEST, "missing token")
          return
        bridge._token = token
        bridge._event.set()
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    return _ThreadedHTTPServer((self.host, self.port), Handler)
