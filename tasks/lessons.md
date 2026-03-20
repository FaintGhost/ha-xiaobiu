# Lessons

- 多阶段认证 CLI 不能强制用户一次性提供后续步骤参数；默认应提供交互式引导流程，例如先发短信，再提示输入验证码，必要时再提示输入验证码 token
- 当服务端已经返回明确的风控类型时，CLI 不能再让用户二次选择类型；应自动按 `riskType` 映射流程，只提示用户补充该类型所需的数据
- 第三方验证码桥接页必须同时验证桌面端和移动端布局；不要把外部组件放在垂直居中且百分比尺寸的容器里，否则容易把关键交互区挤出视口
- 第三方组件兼容性修复如果没有真实页面验证，不能直接替换已可用实现；先保守回退到已验证路径，再做隔离实验
- 移动 App 在 SSL 抓包或 MITM 环境下的登录态稳定性不能默认可靠；登录链路与能力抓包链路要解耦，优先保住可用的 Web 登录，再把 App 抓包用于发现接口与字段
- Home Assistant 自定义集成不能依赖 private GitHub tarball requirement；config flow 创建前 HA 会先安装 requirements，安装失败会直接让配置向导报 500。运行时代码必须随 `custom_components/<domain>` 一起分发，或只依赖公开可安装的 PyPI 包
- Home Assistant 普通用户路径不能依赖 HAR 这类抓包产物；如果配置项需要开发者专用输入，优先继续逆向协议或把该能力降为可选调试入口，不能把它做成主流程前提
- 逆向短信登录/验证码链路时，不能把 PC 网页参数直接套到移动端请求上；像 `needVerifyCode.do` / `sendCode.do` 这类接口，HTTP 方法、`sceneId/appCode/channel` 和验证码字段名只要错一个，就会表现成“验证已完成但服务端持续要求重新验证”
- 当网页登录页已经能在真实浏览器中生成 `detect` / `dfpToken` 时，CLI 不能继续沿用 `passport_*_js_is_error` 这类占位值；验证码桥接页要把浏览器算出来的风控上下文一并回传，再用于后续风控请求
- 运行时登录修复如果同时服务 CLI 和 Home Assistant，不能只修 `src/` 或 CLI 入口；必须同步检查 HA `config_flow` / adapter 是否也保留并传递了同一份状态与上下文
- Home Assistant 配置流里给远端浏览器用的验证码步骤，不能复用 CLI 的 `127.0.0.1` 本地桥接；应优先使用 HA 自己的 `external step` 和集成内路由，让页面始终挂在当前 HA 主机地址下
- Home Assistant `external step` 页面被用户直接关掉时，HA 不会自动结束原 config flow；如果后续允许用户“重新开始”，必须在新的 user flow 入口主动接管并 abort 同 `unique_id` 的旧 flow，否则会长期卡在 `already_in_progress`
- 当 IAR 成功后仍重复弹验证码时，不能默认是 flow 生命周期问题；要先验证浏览器侧 `detect` / `dfpToken` 是否真的采集成功。拿不到完整风控上下文时，必须显式报错并停止重试，不能静默继续发起下一轮 IAR
