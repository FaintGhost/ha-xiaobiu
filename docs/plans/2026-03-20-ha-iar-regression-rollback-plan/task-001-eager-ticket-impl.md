# Task 001: Eager Ticket Rollback Implementation

**depends-on**: task-001-eager-ticket-test

## Description

回滚 `config_flow` 中进入 IAR external step 的 deferred-ticket 行为，恢复为捕获 `isIarVerifyCode` 后立即申请 `iarVerifyCodeTicket` 并把 ticket 写入 session。

## Execution Context

**Task Number**: 001 of 004
**Phase**: Foundation
**Prerequisites**: `task-001-eager-ticket-test` 已经提供稳定红灯测试

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

- Modify: `/root/workspace/suning/custom_components/suning_biu/config_flow.py`
- Modify: `/root/workspace/suning/custom_components/suning_biu/iar_external_view.py`

## Steps

### Step 1: Restore Eager Ticket Ownership

- 在 `config_flow._async_send_sms()` 中恢复 eager-ticket 申请时机。
- 让 IAR session 在创建时直接持有 `ticket`。

### Step 2: Remove Session Fields That Only Support Deferred Ticketing

- 从 HA IAR session 结构中移除只服务于 `prepare` 阶段的状态字段。
- 保持 existing external-step URL 和 session 生命周期不变。

### Step 3: Verify Green

- 重新运行 `task-001` 的定向测试并验证转绿。
- 再运行一轮 HA component 子集，确认没有引入新的 flow 生命周期回归。

## Verification Commands

```bash
env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check \
  uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' \
  python -m pytest tests/test_home_assistant_component.py -q -k "iar_captcha_step_updates_risk_context_before_retry or iar_captcha_step_aborts_when_session_is_missing"
```

## Success Criteria

- `config_flow` 恢复为 eager-ticket 模型。
- session 创建后立即拥有 ticket。
- `task-001` 红灯测试转绿。
