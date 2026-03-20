# Task 003: Resume Error Logging Test

## Description

为回滚后的 `captcha_done` 路径补足日志回归测试，确保这次只回滚协议时序，不回滚已经证明有价值的错误暴露能力。

## Execution Context

**Task Number**: 003 of 004
**Phase**: Refinement
**Prerequisites**: 设计已明确要求保留日志增强

## BDD Scenario

```gherkin
Scenario: IAR 成功后短信恢复失败
  Given flow 已进入 IAR external step
  And 浏览器已成功回传 token + detect + dfpToken
  When 恢复阶段的 send_sms_code 抛出 SuningError
  Then flow 应回到带 cannot_connect 的 user 表单
  And 当前 IAR session 不应被提前丢弃
  And HA 日志应记录恢复失败异常
```

**Spec Source**: `../2026-03-20-ha-iar-regression-rollback-design/bdd-specs.md`

## Files to Modify/Create

- Modify: `/root/workspace/suning/tests/test_home_assistant_component.py`

## Steps

### Step 1: Verify Scenario

- 对照现有恢复失败测试，确认已经覆盖了回到 `user` 表单和保留 session。
- 找出当前缺失的日志断言。

### Step 2: Implement Test (Red)

- 为 `async_step_captcha_done()` 恢复失败路径补 `caplog` 断言：
  - 日志中必须出现 `Failed to resume Suning SMS flow after IAR verification`
- 如保留 unsupported `risk_type` 错误日志，也增加对应 `caplog` 覆盖。
- 使用 test doubles 隔离 client 和 Home Assistant context。

### Step 3: Verify Failure (Red)

- 运行相关 HA component 定向测试。
- 断言失败是因为日志尚未满足新测试，而不是行为断言错误。

## Verification Commands

```bash
env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check \
  uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' \
  python -m pytest tests/test_home_assistant_component.py -q -k "captcha_done_handles_send_sms_error_without_dropping_session or unsupported"
```

## Success Criteria

- 日志断言测试能稳定失败。
- 失败直接指向缺失日志或错误日志级别，而不是其他协议行为。
