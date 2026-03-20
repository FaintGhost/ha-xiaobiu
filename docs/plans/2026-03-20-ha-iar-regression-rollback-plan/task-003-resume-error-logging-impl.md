# Task 003: Resume Error Logging Implementation

**depends-on**: task-003-resume-error-logging-test

## Description

在完成 HA IAR 协议回滚后，确保 `config_flow` 中的日志增强仍然保留并满足新的 `caplog` 断言。

## Execution Context

**Task Number**: 003 of 004
**Phase**: Refinement
**Prerequisites**: `task-003-resume-error-logging-test` 已提供稳定红灯测试

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

- Modify: `/root/workspace/suning/custom_components/suning_biu/config_flow.py`

## Steps

### Step 1: Preserve Logging While Rolling Back Behavior

- 确认 `_LOGGER.exception(...)` 仍保留在 `async_step_captcha_done()` 的恢复失败路径中。
- 确认 unsupported `risk_type` 的 `_LOGGER.error(...)` 没有被一并回滚掉。

### Step 2: Verify Green

- 先运行日志相关定向测试。
- 再运行完整 HA component tests，确认回滚 eager-ticket 行为时没有把这两类日志一起删除。

### Step 3: Run Broad Regression Checks

- 运行 runtime tests 和 `compileall`，确保回滚后没有语法问题或桥接页副作用。

## Verification Commands

```bash
env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check \
  uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' \
  python -m pytest tests/test_home_assistant_component.py -q

env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_client.py tests/test_captcha_bridge.py -q

env UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall custom_components/suning_biu src/suning_biu_ha tests
```

## Success Criteria

- 日志断言测试转绿。
- `config_flow` 保留恢复失败日志和 unsupported risk type 日志。
- HA component tests、runtime tests、`compileall` 全绿。
