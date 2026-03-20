# 苏宁小 biu 智家短信登录接入任务

## HA IAR Repeat Loop Fix

### Plan

- [x] 对照 CLI 已验证成功的 IAR 链路与 HA external step 链路，找出重复弹验证码的状态差异
- [x] 修正 HA IAR 完成后的重试逻辑，确保正确复用浏览器风控上下文并避免再次触发验证
- [x] 补充最小回归测试，覆盖 HA IAR 成功后不应再次创建新验证会话
- [x] 运行定向验证并回填 tasks / lessons

### Notes

- 当前重复弹 IAR 的更可能根因不是 flow 生命周期，而是验证码页虽然回传了 token，但浏览器侧 `detect` / `dfpToken` 没有稳定采集成功，后端仍继续重试 `sendCode.do`
- 这种情况下客户端会再次拿到 `isIarVerifyCode`，从用户视角就是“明明拼图过了，但又弹出新的验证框”

### Review

- 已更新 `src/suning_biu_ha/captcha_bridge.py` 与 vendored 副本
  - 采集风控上下文由固定等待 `1200ms` 改成最多 `10s` 的轮询等待
  - 只有拿到非空 `detect` 与 `dfpToken` 才允许回传 token
  - 本地桥接与 HA external step 回调现在都会拒绝缺少风险上下文的 POST，避免静默重试
- 已更新 `custom_components/suning_biu/iar_external_view.py`
  - 缺少 `detect` / `dfpToken` 时直接返回 `400 missing risk context`
- 已更新 `custom_components/suning_biu/config_flow.py`
  - `captcha_done` 在消费 session 前会校验风险上下文完整性
  - 若上下文缺失，直接 `captcha_risk_context_missing` abort，而不是继续触发下一轮 IAR
- 已更新翻译与字符串资源
  - 新增 `captcha_risk_context_missing` abort 文案
- 已更新测试
  - `tests/test_captcha_bridge.py` 覆盖本地桥接拒绝缺少风控上下文的回调
  - `tests/test_home_assistant_component.py` 覆盖 HA view 拒绝缺少风控上下文，以及 `captcha_done` 缺上下文时直接 abort

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_captcha_bridge.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest tests/test_home_assistant_component.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests`

### Risks

- 本轮修复把“拿不到浏览器风控上下文”的症状从“静默重复弹框”改成“显式失败并提示重试”；如果未来发现还存在别的服务器侧风控因素，需要再继续补抓包或日志
- `detect` / `dfpToken` 的生成仍依赖苏宁当前前端脚本的全局入口；若 `bd.rst` 或 `_dfp.getToken()` 失效，需要重新适配

## HA IAR Flow Restart Unblock

### Plan

- [x] 复核 HA `already_in_progress` 触发链路，确认旧 user flow 在 IAR external step 关闭后未被释放的根因
- [x] 调整 `config_flow` 的 user 入口，允许新的手工登录尝试接管并终止同手机号的旧 flow
- [x] 同步清理旧 IAR captcha session，避免 flow abort 后残留孤儿 session
- [x] 补充针对“关闭 IAR 页面后重新添加集成”的回归测试并运行验证
- [x] 回填 tasks 文档与 lessons，记录这类 HA external step 中断的处理规则

### Notes

- 关闭 IAR 外部页面或刷新 HA 前端，并不会自动告诉 HA “当前 config flow 已取消”
- HA 的 `async_set_unique_id(...)` 会直接根据仍在 progress 列表里的旧 flow 抛出 `already_in_progress`
- 这意味着只要旧 user flow 没被显式 abort，重新输入同一个手机号时就会一直被挡住

### Review

- 已更新 `custom_components/suning_biu/config_flow.py`
  - `async_step_user(...)` 改为先 `async_set_unique_id(..., raise_on_progress=False)`
  - 随后主动扫描同 `unique_id` 的其它 `SOURCE_USER` flow，并执行接管
  - 接管时会同时 `async_abort(old_flow_id)` 并清掉旧 IAR session
- 已更新 `tests/test_home_assistant_component.py`
  - 新增“旧 IAR flow 关掉后，重新添加同手机号会接管旧 flow”的回归测试

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest tests/test_home_assistant_component.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests`

### Risks

- 浏览器直接关闭这一动作仍然没有服务器回调，因此“旧 flow 被动超时取消”这件事当前仍未自动化；本轮修的是“下一次手工重试时能正确接管旧 flow”
- 如果用户真的在两个前端会话里同时对同一手机号发起手工登录，后发起的 flow 会接管并终止前一个 flow；这是有意选择，用来匹配“重新开始登录”的用户预期

## HA Native IAR External Step

### Plan

- [x] 对照 HA 官方 `external step` 模式，替换当前 config flow 中暴露 `127.0.0.1` 的临时桥接 URL
- [x] 在集成内新增 HA 原生验证码页面与回调视图，允许远端浏览器直接通过 HA 地址完成 IAR
- [x] 让 config flow 在验证码页面完成后自动恢复流程，并继续发送短信
- [x] 补充 Home Assistant 配置流与视图测试，验证远端路径不再依赖 loopback
- [x] 更新 README / tasks 文档，记录新的 HA 测试方式与剩余风险

### Notes

- 原来的 HA IAR 路径直接复用了 CLI `LocalCaptchaBridge.url`，该地址固定绑定 `127.0.0.1`，远端浏览器打开后实际上访问的是“自己设备的 localhost”
- HA 核心 `ConfigFlow.async_external_step(...)` / `async_external_step_done(...)` 支持把配置流挂起到外部页面，再由集成或后台任务恢复流程，适合替代本地桥接端口

### Review

- 已新增 `custom_components/suning_biu/iar_external_view.py`
  - 提供 `/api/suning_biu/iar/{flow_id}/{nonce}` 一次性验证页
  - GET 返回 IAR 拼图页
  - POST 接收 `token` / `detect` / `dfpToken`，随后恢复当前 config flow
- 已更新 `custom_components/suning_biu/config_flow.py`
  - IAR 分支改为 HA 原生 `external step`
  - 验证完成后进入 `captcha_done`，先覆盖风险上下文，再重试 `sendCode.do`
  - IAR 会话缺失时改为 `captcha_session_expired`，不再回退为空表单
- 已更新 `src/suning_biu_ha/captcha_bridge.py` 与 vendored 副本
  - 抽出 `render_captcha_page(...)`
  - 支持自定义回调地址，供 CLI 本地桥接和 HA 内置视图复用同一套前端页
- 已更新文档与版本
  - `README.md` 改成 HA external step 新路径说明
  - `custom_components/suning_biu/manifest.json` 版本提升到 `0.1.5`
- 已更新测试
  - `tests/test_home_assistant_component.py` 覆盖 external step、回调视图、会话过期 abort

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest tests/test_home_assistant_component.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests`

### Risks

- IAR 验证页仍依赖苏宁当前公开的 `SnCaptcha.js`、`mmds` 与 `fp` 风控脚本；如果苏宁替换这套前端接口，需要重新适配
- `requires_auth = False` 的 HA 视图使用 `flow_id + nonce` 作为一次性能力 URL；如果未来要进一步收紧安全模型，需要改成带签名的回调或走 HA 官方 OAuth/redirect callback 方案
- 非 IAR 验证码仍然是手工 token 输入路径，本轮没有把其它验证码类型也改造成 HA 原生页面

## SMS IAR Loop Fix

### Plan

- [x] 核对 `new.har`、成功 HAR 与 live 登录页脚本，确认 IAR 循环的真实根因
- [x] 扩展本地验证码桥接页，让浏览器把 `token`、`detect`、`dfpToken` 一起回传
- [x] 在 CLI 的 IAR 重试路径中覆盖风控上下文，再次发起 `sendCode.do`
- [x] 同步 vendored runtime，补充单测并运行验证
- [x] 回填修复结论、验证结果与剩余风险

### Notes

- `new.har` 里只有 `iar-web/init.json`、`iar-web/validate.json` 和浏览器侧 `dfprs-collect` 请求，没有 `sendCode.do`
- 登录页 live 脚本已确认：
  - `getDetect()` 实际调用 `bd.rst({ scene: "1" })`
  - `getDfpToken()` 实际调用 `_dfp.getToken()`
- 当前 CLI 在 IAR 成功后仍继续使用 `passport_*_js_is_error` 占位值，才是重复要求验证的关键原因

### Review

- 已更新 `src/suning_biu_ha/captcha_bridge.py`
  - 桥接页现在会额外加载登录页所需的 `mmds` / `fp` 风控脚本
  - IAR 完成后会把 `token`、浏览器侧 `detect`、浏览器侧 `dfpToken` 一起回传给本地进程
- 已更新 `src/suning_biu_ha/client.py`
  - `initialize()` 现在会从登录页提取当前可用的风控脚本 URL，避免桥接页硬编码依赖单一版本路径
  - IAR 验证完成后，CLI 会先用浏览器回传的 `detect/dfpToken` 覆盖风险上下文，再重试 `sendCode.do`
  - `login_with_sms_code()` 也会继续复用同一份已更新的风险上下文
- 已更新 `custom_components/suning_biu/config_flow.py`
  - Home Assistant config flow 的 IAR 分支现在会保留桥接页返回的 `detect/dfpToken`
  - 短信重试前会先更新 client 的风险上下文，避免 HA 内重复进入 IAR 循环
- 已更新 `src/suning_biu_ha/models.py`
  - `CaptchaBridgeResult` 现在除 `token` 外，还携带 `detect` 与 `dfp_token`
- 已同步 vendored runtime
  - `custom_components/suning_biu/suning_biu_ha/{client.py,captcha_bridge.py,models.py}` 与 `src/` 保持一致
- 已更新用户文档与版本信息
  - `README.md` 已补齐 codebase 摘要、HA 测试步骤与 IAR 风控修复后的实际行为
  - `custom_components/suning_biu/manifest.json` 版本提升到 `0.1.4`
- 已新增/更新测试
  - `tests/test_captcha_bridge.py` 覆盖桥接页回传 `detect` / `dfpToken`
  - `tests/test_client.py` 覆盖 IAR 成功后风险上下文覆盖逻辑，以及登录页脚本 URL 提取
  - `tests/test_home_assistant_component.py` 覆盖 HA config flow 在 IAR 成功后会更新风险上下文再重试短信发送

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_captcha_bridge.py tests/test_client.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall src/suning_biu_ha custom_components/suning_biu/suning_biu_ha tests`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`
- 本地桥接页冒烟验证
  - 启动 `LocalCaptchaBridge(ticket='ticket-test')`
  - 用 `agent-browser` 打开 `http://127.0.0.1:<port>/`
  - 在页面上下文执行 `await collectRiskContext()`，已拿到非空 `detect` 与 `dfpToken`

### Risks

- 本轮修复依赖网页登录页当前暴露的 `mmds` / `fp` 脚本接口；若苏宁后续替换 `bd.rst` 或 `_dfp.getToken()` 的全局入口，需要重新适配
- 当前还没有对真实手机号做一次完整短信发送成功的无人工自动化验证，最终闭环仍需用户再跑一遍 `uv run main.py login --phone ...` 实测

## Manifest Private Requirement Fix

### Plan

- [x] 对照 Home Assistant 官方文档确认 `manifest.requirements` 与 config flow 加载的约束
- [x] 去掉 private GitHub requirement，改为自带 vendored runtime，确保 custom component 可独立分发
- [x] 补充针对 vendored runtime 与纯 Home Assistant 环境导入的测试/验证
- [x] 回填修复结论与风险

### Notes

- 原 `manifest.json` 通过 `codeload.github.com` 拉取 `suning-biu-ha` tarball，但该 repo 为 private，用户环境无法下载
- Home Assistant 在加载 config flow 前会先处理 integration requirements；requirements 安装失败会直接导致配置向导加载失败

### Review

- 已更新 `custom_components/suning_biu/manifest.json`
  - 删除 private GitHub tarball requirement
  - 改为显式 `requirements: []`
  - 版本提升到 `0.1.2`
- 已新增 vendored runtime
  - 新增 `custom_components/suning_biu/suning_biu_ha/`
  - 将 `src/suning_biu_ha` 的运行时代码一并带入 custom component 内部，避免依赖仓库外部安装步骤
- 已更新 `custom_components/suning_biu/client_lib.py`
  - 改为从 `.suning_biu_ha` 相对导入运行时代码
  - 现在 custom component 可在没有顶层 `suning_biu_ha` 包的 Home Assistant 环境中直接加载
- 已更新文档与测试
  - `README.md` 说明 custom integration 现在自带 vendored runtime
  - `tests/test_home_assistant_component.py` 新增 `load_client_lib()` 使用 vendored runtime 的断言

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-ha-core-only uv run --no-project --python 3.14 --with 'homeassistant==2026.3.2' python - <<'PY' ... load_client_lib() ... import config_flow ... PY`

### Risks

- 当前 vendored runtime 与 `src/suning_biu_ha` 存在双份代码；后续若继续演进登录/设备协议，需要同步维护两处，或进一步抽出统一分发策略
- `requirements` 现在为空，依赖的是 Home Assistant `2026.3.2` 自带的 `requests` / `cryptography` / `pydantic`；若后续目标 HA 版本移除其中任一依赖，需要重新评估 manifest

## Python 3.14 And Full Test Pass

### Plan

- [x] 将仓库的 `uv` / Python 默认版本同步到 `3.14`，并更新锁文件与文档约束
- [x] 修正 Home Assistant 自定义集成的 `strings.json` 与翻译源不一致问题
- [x] 补齐当前 codebase 的测试，优先覆盖自定义集成入口、实体与运行时依赖装载逻辑
- [x] 用 Python `3.14` 跑完整验证，整理 codebase 摘要并提交 commit

### Notes

- 当前项目根目录 `.python-version` 已同步为 `3.14`
- `pyproject.toml` 的 `requires-python` 已同步为 `>=3.14`

### Review

- 已完成 Python 3.14 同步
  - `.python-version` 已更新为 `3.14`
  - `pyproject.toml` 的 `requires-python` 已更新为 `>=3.14`
  - 重新执行 `uv lock --python 3.14` 与 `uv sync --dev --python 3.14`
- 已修正国际化源文件
  - `custom_components/suning_biu/strings.json` 已补齐 `reauth_confirm` / `reconfigure` / `reauth_successful` / `reconfigure_successful`
  - 现在 `strings.json` 与 `translations/*.json` 的 flow 文案保持一致
- 已扩充测试覆盖
  - `tests/test_home_assistant_component.py` 新增对 `load_client_lib()` 导入失败包装、`async_setup_entry()` 的 HAR 路径错误、`async_step_reconfigure()`、`SuningClimateEntity` 状态映射、`climate.async_setup_entry()` 与 `strings.json` 文案完整性的覆盖
  - 当前测试总数提升到 `26`

### Codebase Summary

- `src/suning_biu_ha/`
  - 项目的核心运行时客户端
  - 负责苏宁短信登录、Cookie 持久化、HAR 签名模板复用、设备状态标准化与 CLI
- `custom_components/suning_biu/`
  - Home Assistant 自定义集成适配层
  - 负责 config flow、config entry setup/unload、`DataUpdateCoordinator`、`climate` 实体与翻译资源
- `tests/`
  - 以纯 Python 单测为主
  - 目前覆盖了加密、验证码桥接、登录客户端、Home Assistant 集成入口/flow/coordinator/entity
- `README.md`
  - 仓库级使用说明
  - 包含 CLI 用法、Home Assistant 集成概览与当前已知边界

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -V`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`

## Home Assistant Component Fixes

### Plan

- [x] 对照 Home Assistant 官方文档与当前代码，确认集成初始化、协调器与 `climate` 实体的兼容性问题
- [x] 修复当前自定义集成中的运行期问题，优先处理认证失败传播与实体状态建模
- [x] 补充针对自定义集成的最小测试或冒烟脚本，覆盖修复点
- [x] 在目标 Home Assistant 版本上运行验证，回填结果与剩余风险

### Notes

- 当前仓库已有未提交的 `custom_components/suning_biu` 改动，本轮修复基于现状继续推进，不回滚既有修改
- README 标注目标 Home Assistant 版本为 `2026.3.2`，该版本要求 Python `3.14`

### Review

- 已更新 `custom_components/suning_biu/__init__.py`
  - `resolve_har_path()` 现在强制校验 HAR 文件真实存在
  - 无效 HAR 路径在 entry setup 阶段改为 `ConfigEntryError`，提示用户走 reconfigure 修正
  - setup 时显式传入 `config_entry` 给协调器，并继续保留运行时依赖延迟加载
- 已更新 `custom_components/suning_biu/coordinator.py`
  - 认证失败改为抛出 `ConfigEntryAuthFailed`
  - 协调器显式绑定 `config_entry`，符合 Home Assistant 当前 `DataUpdateCoordinator` 用法
- 已更新 `custom_components/suning_biu/config_flow.py`
  - 新增 `reauth` / `reauth_confirm` 流程，认证失效后可直接重新短信登录
  - 新增 `reconfigure` 流程，允许在 UI 内更新 HAR 文件路径
  - 抽出 client 初始化、家庭选择 schema 与验证码桥接清理逻辑，减少重复分支
- 已更新翻译与测试依赖
  - 补充 `translations/en.json`、`translations/zh-Hans.json` 中的 `reauth_confirm` / `reconfigure` / 成功 abort 文案
  - `pyproject.toml` 与 `uv.lock` 新增 `pytest-asyncio`
- 已新增 `tests/test_home_assistant_component.py`
  - 覆盖 HAR 路径存在性约束
  - 覆盖协调器认证异常到 `ConfigEntryAuthFailed` 的传播
  - 覆盖 `reauth` 分支在短信登录成功后会更新并重载既有 entry
- 已完成验证
  - `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --python 3.14 --with 'homeassistant==2026.3.2' python -m compileall custom_components/suning_biu src/suning_biu_ha tests`
  - `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run --python 3.14 --with 'homeassistant==2026.3.2' python - <<'PY' ... importlib.import_module(...) ... PY`

### Risks

- 当前仍依赖 HAR 中已有的已签名模板，`reauth` 只能恢复登录态，不能解决签名模板本身缺失或过期的问题
- 目前只补了 `reauth` 与 `reconfigure`；若后续要支持账号切换、家庭切换，仍需要额外 flow 设计

## Plan

- [x] 分析 HAR 中与手机验证码登录、SSO 跳转、Cookie 下发相关的关键请求与响应
- [x] 初始化 `uv` Python 项目，补充依赖与基础目录结构
- [x] 实现短信验证码发送、验证码登录、Cookie 持久化与恢复
- [x] 实现最小可用的会话校验与保活请求
- [x] 编写验证脚本或测试，证明登录后能访问智能家居相关接口
- [x] 分析 `clientservices.googleapis.com_2026_03_20_00_33_46.har`，确认 IAR 桥接链路是否存在异常
- [x] 实测 `.suning-session.json` 的跨进程恢复行为，区分“会话失效”和“接口签名缺失”
- [x] 从 HAR 提取可复用的 App 端已签名请求模板，补齐 `families` / `devices` 的 MVP 读取链路
- [x] 补充测试与文档，验证 `check` / `families` / `devices` 的当前可用边界
- [x] 回填实现结果、风险与后续工作

## Notes

- 当前输入包含 `apm.suning.cn_2026_03_19_23_47_23.har` 与 `clientservices.googleapis.com_2026_03_20_00_33_46.har`
- Python 相关操作统一使用 `uv`
- 目标先做可复用的登录客户端，不直接耦合 Home Assistant 平台代码
- 当前优先级是“先把 MVP 功能做出来”，暂不继续打磨验证码桥接页 UI

## Review

- 已实现 `src/suning_biu_ha/crypto.py`
  - 复刻苏宁 `SuAES` 加解密
  - 复刻短信登录所需 RSA 公钥加密
- 已实现 `src/suning_biu_ha/client.py`
  - 运行时抓取登录页并提取公钥与流程常量
  - 支持 `needVerifyCode.do`、`sendCode.do`、`ids/smartLogin/sms`
  - 支持 Cookie 与登录状态持久化
  - 支持 `shcss` / `itapig` 的 SSO 扩散与会话恢复
  - 支持从 HAR 自动提取 App 端已签名模板，并复用到 `families` / `devices`
  - 支持空调设备状态标准化与保守的 Home Assistant `climate` 预览映射
  - 支持会员信息、家庭列表、设备列表查询
- 已实现 CLI
  - `send-sms`
  - `login`
  - `check`
  - `families`
  - `devices`
  - `device-status`
  - `keep-alive`
  - 共享参数 `--state-file` / `--har-file` / `--detect` / `--dfp-token` 既可写在子命令前，也可写在子命令后
- 已实现 IAR 本地桥接页
  - 当风控返回 `isIarVerifyCode` 时，程序会申请 IAR ticket
  - 本地起一个 `http://127.0.0.1:<port>/` 链接供用户打开完成拼图
  - 页面会把 token 自动回传给本地进程，继续后续短信发送流程
- 已完成 HAR 结论
  - `clientservices.googleapis.com_2026_03_20_00_33_46.har` 中 `iar-web/validate.json` 返回 `resp_code=0`
  - 本地 `/callback` 返回 `{"ok": true}`，未发现桥接页吞掉验证码 token 的证据
  - 跨进程实测表明 `check` 可仅靠持久化 Cookie 恢复；`families` 之前失败的根因是 App 端签名头缺失，不是 session 失效
- 已补充验证
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall src`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run main.py check --har-file apm.suning.cn_2026_03_19_23_47_23.har`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run main.py families --har-file apm.suning.cn_2026_03_19_23_47_23.har`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run main.py devices --family-id 37790 --har-file apm.suning.cn_2026_03_19_23_47_23.har`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run main.py device-status --family-id 37790`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run main.py devices --family-id 4770504 --har-file apm.suning.cn_2026_03_19_23_47_23.har`
  - 直接用实现中的 `SuAES` 解密 HAR 内 `needVerifyCode.do` / `sendCode.do` 返回，确认还原出的 `riskType`、`smsTicket`、`loginTicket` 与抓包链路一致

## Risks

- 当前未实现验证码自动求解，仅支持外部传入 `iar` / `slide` / `image` 的验证码 token
- 其中 `iar` 已支持通过本地桥接页自动回传 token，`slide` / `image` 仍未桥接
- `detect` 与 `dfpToken` 默认使用苏宁网页 JS 失败时的回退值，若服务端后续加强风控，可能需要从真实浏览器环境额外采集并传入
- 当前 `families` / `devices` 仍依赖 HAR 中现成的已签名模板，本轮还没有逆向出 `gsSign` / `signinfo` 的通用生成算法
- `devices --family-id` 只对 HAR 里已经出现过签名模板的 `familyId` 生效；若家庭 ID 变化，需要新的 HAR 或进一步逆向签名算法
- 当前 `device-status` 只做保守映射：在线状态、温度、电源、风速/摆风等字段已标准化，但 `mode_raw` 的枚举含义仍未确认，不能安全实现完整 HVAC 模式映射
- 目前先做到登录、保活与设备列表读取，尚未继续实现空调控制指令

## gsSign Reverse Engineering

### Plan

- [x] 从现有 HAR 中提取全部带 `gsSign` 的请求，以及与之相邻的 `opensh getKey` 样本
- [x] 验证 `gsSign` 与路径、请求体、`requestTime`、trace 头、`opensh` 返回值之间的关系，排除明显错误假设
- [x] 若能得到稳定签名方案，则在运行时与 Home Assistant 集成中去掉 HAR 依赖与 `har_path` 配置项
- [x] 补充针对无 HAR 配置流、家庭列表与设备列表签名的测试
- [x] 运行 Python 3.14 / Home Assistant 验证并回填结论、剩余风险

### Notes

- 本轮目标不是继续打磨 HAR UX，而是验证是否可以根除 HAR 依赖
- 根因已经明确：当前家庭/设备列表接口必须带 `gsSign`，而项目目前只能从 HAR 复用现成签名
- 已从官方 Android APK 逆向出 `SmartHomeBaseJsonTask.getSign(...)`
  - canonical string: `url=<path>&requestTime=<ms>&data=<body>`
  - 去掉空格、换行与回车
  - 使用 `HmacSHA256`，secret 为 `ad71cef5-c46a-48f7-a810-61f4be3a207a`
- 现有 HAR 样本来自 iOS 端，请求头与 hash 不应再作为 Android 算法的真值断言；实现与测试已改为以 Android 逆向结果为准

### Review

- 已更新 `src/suning_biu_ha/client.py` 与 `custom_components/suning_biu/suning_biu_ha/client.py`
  - 新增动态 `gsSign` 生成逻辑与 App API 请求头构造
  - `list_families()` / `list_devices()` 改为运行时签名调用 `itapig`
  - App 请求显式带 `Content-Type: application/json`、`snTraceId`、`hiro_trace_id`、`snTraceType`
  - `itapig` 登录跳转时会先尝试重新 bootstrap，再重试请求
  - 不再在未显式传入 `har_path` 时扫描当前目录下的 `*.har`
- 已更新 Home Assistant 集成层
  - `custom_components/suning_biu/config_flow.py` 去掉 `har_path` 输入与 `reconfigure` 流程
  - `custom_components/suning_biu/__init__.py` setup 不再校验或传入 HAR 路径
  - 旧 config entry 即使残留 `har_path` 也会被忽略，不再阻塞加载
- 已更新文案与版本
  - `custom_components/suning_biu/strings.json` 与 `translations/*.json` 去掉 HAR 相关说明
  - `custom_components/suning_biu/manifest.json` 版本提升到 `0.1.3`
  - `README.md` 改为说明 HAR 仅保留为调试 fallback，正常 CLI / HA 流程不再依赖
- 已补充测试
  - `tests/test_client.py` 新增 Android `gsSign` 固定样本断言
  - `tests/test_client.py` 新增动态 family/device 请求头构造覆盖
  - `tests/test_client.py` 新增“未显式配置时不自动扫描 HAR”覆盖
  - `tests/test_home_assistant_component.py` 改为覆盖无 HAR setup、无 HAR user flow、family entry 创建与 strings 约束

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest tests/test_client.py tests/test_home_assistant_component.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`

### Risks

- 目前缺少可复用的 Android 端线上成功抓包样本，`gsSign` 算法来自 APK 逆向，真实可用性主要由单测与请求格式比对保证；若后续苏宁升级 App secret 或 header 约束，需要重新逆向
- `opensh` / `signInfo` 相关链路仍未接入；当前去 HAR 只覆盖 `families` / `devices`

## Pydantic Migration

### Plan

- [x] 使用 `uv add pydantic` 引入 Pydantic v2 依赖并更新锁文件
- [x] 新增统一模型文件，承接登录配置、认证状态、签名模板、空调状态与会话持久化结构
- [x] 替换 `client.py` 中的 `dataclass/asdict`，改为 `model_dump` / `model_validate_json`
- [x] 调整验证码桥接结果与测试，确保调用方不再依赖 `dataclass` 位置参数初始化
- [x] 用 `uv` 运行测试、编译和 CLI 冒烟验证，确认迁移未破坏既有 MVP

### Review

- 已新增 `src/suning_biu_ha/models.py`
  - 引入 `SuningBaseModel`
  - 收口 `LoginPageConfig`、`AuthState`、`CaptchaSolution`、`SignedRequestTemplate`
  - 新增 `HAClimatePreview`、`SerializedCookie`、`PersistedSessionState`、`CaptchaBridgeResult`
- 已更新 `src/suning_biu_ha/client.py`
  - 删除内部 `dataclass` 定义
  - `save_state()` 改为基于 `PersistedSessionState.model_dump(mode="json")`
  - `load_state()` 改为基于 `PersistedSessionState.model_validate_json(...)`
  - `device-status` 输出改为基于 `AirConditionerStatus.model_dump(mode="json")`
  - `ha_climate_preview` 改为嵌套 Pydantic 模型
- 已更新 `src/suning_biu_ha/captcha_bridge.py`
  - 桥接结果改为复用统一的 Pydantic 模型
- 已更新 `src/suning_biu_ha/__init__.py`
  - 导出常用 Pydantic 模型，便于后续 Home Assistant 集成复用
- 已更新 `tests/test_client.py`
  - 适配 Pydantic 初始化方式与嵌套模型断言
- 已完成验证
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall src`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run main.py device-status --family-id 37790`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run main.py keep-alive`

## Android SMS Login Alignment

### Plan

- [x] 对照 HAR 与当前 CLI 登录实现，确认 IAR 循环验证的根因
- [x] 将 `needVerifyCode.do`、`sendCode.do`、`ids/smartLogin/sms` 调整为已验证的 MOBILE/xiaobiu 请求参数
- [x] 补充针对 MOBILE 验证码字段与 POST form 请求的测试
- [x] 运行 Python 3.14 / Home Assistant 全量验证，确认未引入回归

### Notes

- 用户实测 `uv run main.py login --phone ...` 时，IAR 拼图完成后仍然反复要求再次验证
- HAR 已证明当前可用链路不是 PC 网页参数，而是 `PASSPORT_XIAOBIU` + `MOBILE` 的请求形态

### Review

- 已更新 `src/suning_biu_ha/client.py`
  - `prepare_sms_login()` / `send_sms_code()` 改为 `POST application/x-www-form-urlencoded`
  - 国内手机号默认走 `MOBILE` 登录参数
  - 新增 `MOBILE_SMS_LOGIN_*` 常量、`_mobile_sms_login_data()`、`_build_*_payload()` 辅助方法
  - IAR 验证码字段改为真实链路格式：`code=<token>` 且 `uuid=""`
  - `login_with_sms_code()` 改为对齐 HAR 的 `ids/smartLogin/sms` POST 表单参数
- 已同步更新 vendored runtime
  - `custom_components/suning_biu/suning_biu_ha/client.py`
- 已新增客户端回归测试
  - `tests/test_client.py` 新增 MOBILE `needVerifyCode`、`sendCode`、`smartLogin/sms` 的参数断言

### Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_client.py -q`
- `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests`
- `env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' python -m pytest -q`

### Risks

- 当前只能通过 HAR 和单测确认“请求形态”已经对齐；由于实时 IAR 拼图需要人工参与，本轮未能在自动化里完整跑通一次真实短信发送
- `00852` 等非大陆区号目前仍保留旧网页登录参数分支，后续若要全面移动端化，需要单独抓样本确认
