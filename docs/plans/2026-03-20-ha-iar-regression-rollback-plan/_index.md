# HA IAR Regression Rollback Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task.

**Goal:** 回滚 `1b72b07` 引入的 HA IAR deferred-ticket 功能改动，只保留日志增强，恢复到用户已验证过的 eager-ticket 路径。

**Architecture:** 保持 `dbd5806` 的 HA IAR 流程结构不变：`config_flow` 在捕获 `isIarVerifyCode` 后立即申请 ticket，`iar_external_view` 只承载单阶段 external-step 页面和成功回调，验证码页面直接使用服务端提供的 ticket 初始化 `SnCaptcha`。同时保留 `config_flow` 中新增的异常日志，让恢复阶段失败不再只暴露成泛化的 `cannot_connect`。

**Tech Stack:** Python 3.14, Home Assistant `2026.3.2`, `pytest`, Home Assistant config flow/external step, vendored runtime bridge page

**Design Support:**
- [BDD Specs](../2026-03-20-ha-iar-regression-rollback-design/bdd-specs.md)
- [Architecture](../2026-03-20-ha-iar-regression-rollback-design/architecture.md)
- [Best Practices](../2026-03-20-ha-iar-regression-rollback-design/best-practices.md)

**Execution Plan:**
- [Task 001: Eager Ticket Regression Test](./task-001-eager-ticket-test.md)
- [Task 001: Eager Ticket Rollback Implementation](./task-001-eager-ticket-impl.md)
- [Task 002: Single-Stage IAR Flow Test](./task-002-single-stage-iar-flow-test.md)
- [Task 002: Single-Stage IAR Flow Implementation](./task-002-single-stage-iar-flow-impl.md)
- [Task 003: Resume Error Logging Test](./task-003-resume-error-logging-test.md)
- [Task 003: Resume Error Logging Implementation](./task-003-resume-error-logging-impl.md)
- [Task 004: Post-Rollback HA Verification](./task-004-post-rollback-ha-verify.md)

---

## Constraints

- 只回滚 `1b72b07` 引入的 deferred-ticket / `prepare` 协议改动，不顺手改其他登录链路。
- 保留 `async_step_captcha_done()` 的 `_LOGGER.exception(...)` 和 unsupported `risk_type` 的 `_LOGGER.error(...)`。
- `custom_components/suning_biu/suning_biu_ha/captcha_bridge.py` 与 `src/suning_biu_ha/captcha_bridge.py` 必须同步修改。
- 删除或重写只对 deferred-ticket 双阶段协议成立的测试断言。
- 自动化验证以 HA component tests 为主，最终以真实 HA 手工回归为准。

## Commit Boundaries

- `Task 001`:
  - 红灯测试提交：eager-ticket 行为断言
  - 绿灯实现提交：`config_flow` 恢复即时申请 ticket
- `Task 002`:
  - 红灯测试提交：single-stage external-step 行为断言
  - 绿灯实现提交：`iar_external_view` 和 bridge page 回滚到单阶段协议
- `Task 003`:
  - 红灯测试提交：日志与错误处理断言
  - 绿灯实现提交：保留日志增强并让回滚后行为重新为绿
- `Task 004`:
  - 不要求新代码提交；用于执行真实 HA 验证和记录结果

## Execution Handoff

Plan complete and saved to `docs/plans/2026-03-20-ha-iar-regression-rollback-plan/`.

Execution options:

1. Orchestrated execution (recommended): use `executing-plans`
2. Direct agent team: use `agent-team-driven-development`
3. Manual serial execution in this session
