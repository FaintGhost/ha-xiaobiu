# ha-xiaobiu

苏宁小biu 智能家居 Home Assistant 自定义集成。

## 功能

- 短信验证码登录，无需抓包
- 支持 IAR 滑块验证：集成内置验证页面，完成后自动继续
- 空调设备作为 `climate` 实体接入，离线设备标记为不可用
- 支持"重新配置"切换家庭

## 安装

**一键安装（在 Home Assistant 终端中执行）：**

```bash
wget -q -O - https://raw.githubusercontent.com/FaintGhost/ha-xiaobiu/main/install.sh | bash -
```

安装指定版本：

```bash
wget -q -O - https://raw.githubusercontent.com/FaintGhost/ha-xiaobiu/main/install.sh | ARCHIVE_TAG=v0.1.6 bash -
```

安装完成后重启 Home Assistant，进入 **设置 → 设备与服务 → 添加集成**，搜索 **Xiaobiu**。

**手动安装：**

1. 将 `custom_components/xiaobiu` 复制到 Home Assistant 配置目录的 `custom_components/` 下。
2. 重启 Home Assistant。
3. 进入 **设置 → 设备与服务 → 添加集成**，搜索 **Xiaobiu**。

## 使用

**添加集成：**

1. 输入手机号和国际区号（默认 `0086`）。
2. 如出现滑块验证，在弹出的验证页面完成后流程自动恢复。
3. 输入短信验证码，选择家庭，完成。

**切换家庭：**

在集成条目菜单中选择 **重新配置**。如登录已过期，会先要求重新验证。

## 已知限制

- 仅支持 IAR 类型的滑块验证；其他验证码类型暂不支持。
- 目前仅接入空调设备，其他设备类型尚未支持。

## 协议库

本集成基于 [python-xiaobiu](https://pypi.org/project/python-xiaobiu/) 实现，也可独立使用：

```python
from xiaobiu import SuningSmartHomeClient

client = SuningSmartHomeClient(state_path=".session.json")
client.login_with_sms_code(phone_number="13800000000", sms_code="123456")
print(client.list_families())
```

## 开发

```bash
uv sync --dev
uv run pytest tests/ -q
```
