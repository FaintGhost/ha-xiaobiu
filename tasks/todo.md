# 苏宁小 biu 智家短信登录接入任务

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
