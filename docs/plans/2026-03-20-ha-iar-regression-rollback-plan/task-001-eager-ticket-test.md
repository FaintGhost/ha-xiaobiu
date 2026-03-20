# Task 001: Eager Ticket Regression Test

## Description

把 HA IAR 进入阶段的测试从 deferred-ticket 断言改回 eager-ticket 断言，先让测试准确表达“进入 external step 时 session 必须已经持有 ticket”的目标行为。

## Execution Context

**Task Number**: 001 of 004
**Phase**: Foundation
**Prerequisites**: 设计文档已确认回滚目标是恢复 eager-ticket 行为

## BDD Scenario

```gherkin
Scenario: 进入 IAR 步骤时立即拿到 ticket
  Given HA config flow 在首次 send_sms_code(..., captcha=None) 时收到 CaptchaRequiredError(isIarVerifyCode)
  When flow 创建 IAR external step
  Then IAR session 应立即保存已申请好的 ticket
  And 浏览器首次打开 external-step 页面时不需要额外 prepare 请求
```

**Spec Source**: `../2026-03-20-ha-iar-regression-rollback-design/bdd-specs.md`

## Files to Modify/Create

- Modify: `/root/workspace/suning/tests/test_home_assistant_component.py`

## Steps

### Step 1: Verify Scenario

- 确认现有 IAR session 创建测试覆盖的是同一条行为链。
- 标记所有仅服务于 deferred-ticket 模型的断言，例如 `session.ticket is None`。

### Step 2: Implement Test (Red)

- 调整或新增 component 测试，使其明确断言：
  - `request_iar_verify_code_ticket()` 在进入 IAR external step 前已被调用
  - session 创建后立即携带 ticket
  - 测试不再依赖 `client` / `phone_number` 注入 session
- 使用 test doubles 隔离 Home Assistant runtime 与 client 行为，不依赖真实网络。

### Step 3: Verify Failure (Red)

- 运行针对该场景的定向 HA component 测试。
- 断言失败原因是 eager-ticket 期望与当前 deferred-ticket 实现不一致，而不是导入错误或环境错误。

## Verification Commands

```bash
env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check \
  uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' \
  python -m pytest tests/test_home_assistant_component.py -q -k "iar_captcha_step_updates_risk_context_before_retry"
```

## Success Criteria

- 测试完整表达 eager-ticket 目标行为。
- 定向测试在当前代码上稳定失败。
- 失败原因直接指向当前 deferred-ticket 实现，而不是环境问题。
