# Task 004: Post-Rollback HA Verification

**depends-on**: task-001-eager-ticket-impl, task-002-single-stage-iar-flow-impl, task-003-resume-error-logging-impl

## Description

在真实 HA 环境里执行端到端回归，确认这次回滚确实恢复到了“至少能成功请求短信验证码”的状态，而不是只在单测里回到 eager-ticket 模型。

## Execution Context

**Task Number**: 004 of 004
**Phase**: Testing
**Prerequisites**: 代码实现与自动化验证已全部完成，待部署到真实 HA 环境复测

## BDD Scenario

```gherkin
Scenario: IAR 回滚后恢复真实 HA 登录链路
  Given HA 已部署回滚后的 eager-ticket IAR 版本
  When 用户从添加集成开始完成一次 IAR 验证并提交短信验证码
  Then HA 应至少恢复到短信已发送状态
  And IAR 之后不应立即出现 sendCode.do 00201
  And 后续 flow 不应再次回到 user 或卡在 already_in_progress
```

**Spec Source**: `../2026-03-20-ha-iar-regression-rollback-design/bdd-specs.md`

## Files to Modify/Create

- No repository file changes required by default
- If verification uncovers deviations, record them in execution notes before new code changes begin

## Steps

### Step 1: Deploy Verification Build

- 将回滚后的 `custom_components/suning_biu` 部署到真实 HA 配置目录。
- 重启 HA，确认集成加载正常。

### Step 2: Run End-to-End Login Flow

- 从 “添加集成” 开始输入手机号。
- 完成 IAR。
- 观察是否进入 “短信已发送 / 输入验证码” 步骤。

### Step 3: Verify Post-IAR Stability

- 确认 IAR 成功后：
  - 没有立即报 `00201`
  - 没有再次弹出新的 IAR 页面
  - 没有卡在 `already_in_progress`

### Step 4: Verify Post-SMS Flow

- 输入短信验证码。
- 验证能否继续进入家庭选择，而不是再次回到 `user` / `sms_code` 错误页。

## Verification Commands

```bash
env UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/tmp/uv-suning-ha-check \
  uv run --group dev --python 3.14 --with 'homeassistant==2026.3.2' \
  python -m pytest tests/test_home_assistant_component.py -q

env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_client.py tests/test_captcha_bridge.py -q
```

## Success Criteria

- 真实 HA 环境中，IAR 通过后重新恢复到“短信已发送”。
- 不再复现当前这条 `sendCode.do -> 00201` 回归。
- 关闭页面、重复回调、后续输入短信验证码等流程都没有出现新的阻塞。
