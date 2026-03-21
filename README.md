# ha-xiaobiu

苏宁小biu（Xiaobiu）智能家居 Home Assistant 自定义集成。

底层协议库已单独发布为 PyPI 包：[python-xiaobiu](https://pypi.org/project/python-xiaobiu/)。

## 功能

- 通过苏宁短信登录流程完成身份验证，无需 HAR 文件
- 支持 IAR 验证码：HA 集成内置验证页面，浏览器完成滑块后自动恢复流程
- 运行时签名智能家居 API 请求（`gsSign` 算法逆向实现）
- 空调设备作为 `climate` 实体暴露，离线设备标记为不可用
- 支持通过"重新配置"菜单刷新家庭列表并切换家庭

## 仓库结构

```
custom_components/xiaobiu/   # HA 集成代码
tests/                       # HA 集成测试
tasks/                       # 协议逆向过程中的开发记录
```

## 依赖

- Home Assistant `>= 2026.3`
- Python `3.14`
- [`python-xiaobiu`](https://pypi.org/project/python-xiaobiu/) —— 自动通过 HA 的 requirements 机制安装

## 安装

1. 将 `custom_components/xiaobiu` 文件夹复制到 Home Assistant 配置目录的 `custom_components/` 下。
2. 重启 Home Assistant。
3. 进入 **设置 → 设备与服务 → 添加集成**，搜索 **Xiaobiu**。

## 配置流程

1. 输入手机号码和国际区号（默认 `0086`）。
2. 如果苏宁要求 IAR 验证，流程会跳转到 HA 提供的外部验证页面，在浏览器中完成滑块验证后流程自动恢复。
3. 输入收到的短信验证码。
4. 选择要导入的家庭。
5. 集成添加成功，空调设备以 `climate` 实体创建。

## 重新配置

在集成条目菜单中选择 **重新配置** 可刷新家庭列表并切换到其他家庭。  
如果已保存的 Session 已过期，流程会先要求重新短信登录。

## 开发

安装开发依赖：

```bash
uv sync --dev
```

运行测试（非 HA 依赖部分）：

```bash
uv run pytest tests/test_home_assistant_component.py -q
```

## 协议库

底层客户端库已迁移到独立仓库：

- GitHub：[FaintGhost/python-xiaobiu](https://github.com/FaintGhost/python-xiaobiu)
- PyPI：[python-xiaobiu](https://pypi.org/project/python-xiaobiu/)

```python
from xiaobiu import CaptchaRequiredError, SuningSmartHomeClient

client = SuningSmartHomeClient(state_path=".xiaobiu-session.json")

try:
    client.send_sms_code("13800000000")
except CaptchaRequiredError as error:
    print(error.risk_type, error.sms_ticket)

client.login_with_sms_code(phone_number="13800000000", sms_code="123456")
print(client.list_families())
```

## 已知限制

- 仅支持 IAR 类型的验证码自动处理；其他验证码类型暂不支持。
- 目前仅暴露空调（`climate`）实体，其他设备类型尚未接入。
- Session 文件包含 Cookie 和登录状态，属于本地敏感文件，不要提交到版本控制。
