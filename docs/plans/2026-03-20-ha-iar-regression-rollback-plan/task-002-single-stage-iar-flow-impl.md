# Task 002: Single-Stage IAR Flow Implementation

**depends-on**: task-002-single-stage-iar-flow-test

## Description

回滚 `iar_external_view` 与验证码页面 JS 的 `prepare` 协议，让 HA IAR external-step 重新成为单阶段模型，同时保留风险上下文采集、缺上下文拒绝回调、以及重复 success callback 幂等保护。

## Execution Context

**Task Number**: 002 of 004
**Phase**: Core Features
**Prerequisites**: `task-002-single-stage-iar-flow-test` 已提供稳定红灯测试

## BDD Scenario

```gherkin
Scenario: IAR 成功后恢复短信发送
  Given flow 已进入 IAR external step
  And 当前 IAR session 已包含 ticket
  And 浏览器回传 token + detect + dfpToken
  When async_step_captcha_done() 恢复执行
  Then client 应先更新风险上下文
  And 再使用 CaptchaSolution(kind="iar") 重试 send_sms_code
  And 成功时 flow 应进入 sms_code
```

**Spec Source**: `../2026-03-20-ha-iar-regression-rollback-design/bdd-specs.md`

## Files to Modify/Create

- Modify: `/root/workspace/suning/custom_components/suning_biu/iar_external_view.py`
- Modify: `/root/workspace/suning/custom_components/suning_biu/suning_biu_ha/captcha_bridge.py`
- Modify: `/root/workspace/suning/src/suning_biu_ha/captcha_bridge.py`

## Steps

### Step 1: Restore Single-Stage View Contract

- 删除 `prepare` / `complete` 双阶段 POST 协议。
- 让 view 恢复为只接收一次成功回调。

### Step 2: Restore Direct Ticket Initialization

- 让验证码页面恢复为直接使用服务端提供的 ticket 初始化 `SnCaptcha`。
- 删除只服务于 deferred-ticket 的 JS 变量与初始化路径。

### Step 3: Preserve Existing Guardrails

- 保留 `detect/dfpToken` 采集逻辑。
- 保留缺少风险上下文时拒绝回调的行为。
- 保留 `resume_requested` 的幂等保护。

### Step 4: Verify Green

- 先运行定向 external-step 测试。
- 再运行完整 HA component tests 和 runtime bridge tests，确认没有破坏 CLI 桥接页行为。

## Verification Commands

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_captcha_bridge.py -q

env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check \
  uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' \
  python -m pytest tests/test_home_assistant_component.py -q
```

## Success Criteria

- `iar_external_view` 不再包含 `prepare` 阶段状态机。
- 两份 `captcha_bridge.py` 保持同步且恢复 direct-ticket 初始化。
- HA component tests 与 bridge tests 全绿。
