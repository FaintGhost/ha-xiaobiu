# Task 002: Single-Stage IAR Flow Test

**depends-on**: task-001-eager-ticket-impl

## Description

把 HA external-step 相关测试改回单阶段协议模型：页面 GET 直接带 ticket，成功 POST 直接恢复 flow，不再存在 `prepare` 请求或 `complete before prepare` 分支。

## Execution Context

**Task Number**: 002 of 004
**Phase**: Core Features
**Prerequisites**: eager-ticket 行为已经恢复，session 创建时可直接携带 ticket

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

- Modify: `/root/workspace/suning/tests/test_home_assistant_component.py`
- Modify: `/root/workspace/suning/tests/test_captcha_bridge.py`

## Steps

### Step 1: Verify Scenario

- 找出现有 external-step 相关测试中依赖 deferred-ticket 双阶段协议的部分。
- 明确哪些断言需要被删除、重写或保留。

### Step 2: Implement Test (Red)

- 重写页面渲染与成功回调测试，使其表达：
  - GET 页面直接携带 ticket
  - 页面中不再出现 `prepare` 阶段专用变量或协议
  - 成功 POST 一次性回传 `token + detect + dfpToken`
  - flow 能直接恢复到 `sms_code`
- 保留并复用现有的 regression coverage：
  - 缺少风险上下文时拒绝回调
  - 重复 success callback 只恢复一次
- 删除只对 deferred-ticket 成立的测试，例如 “complete before prepare”。

### Step 3: Verify Failure (Red)

- 运行 `tests/test_home_assistant_component.py` 和 `tests/test_captcha_bridge.py` 的定向用例。
- 断言失败直接对应当前 `prepare` 协议仍然存在。

## Verification Commands

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_captcha_bridge.py -q

env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check \
  uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' \
  python -m pytest tests/test_home_assistant_component.py -q -k "iar_captcha_view or iar_captcha_step_updates_risk_context_before_retry"
```

## Success Criteria

- 测试精确表达 single-stage external-step 协议。
- deferred-ticket 专属断言已被移除或改写。
- 定向测试在当前代码上稳定失败。
