# 观察点监控系统（Agent）

轻量级、可扩展的全局观察点监控服务，用于 Euler ARM 存储阵列。

> **项目结构**：本目录 (`agent/`) 是 `observation_web` 项目的一部分。通过 Web 界面部署时，本目录会被打包为 `observation_points` 模块上传到阵列。

## 功能特性

1. **误码监测** - 端口误码（rx_crc_errors/fcs_errors/rx_frame_errors/tx_carrier_errors）+ PCIe 链路误码，增量检测
2. **链路状态监测** - link down/up 事件检测，支持白名单
3. **卡修复监测** - 监控 `recover chiperr` 事件，统计总次数及最近3次详情（时间+PCIe槽位）
4. **敏感信息监测** - 日志中的密码、NQN、IQN 等敏感信息检测
5. **AlarmType 监测** - 监控日志中的 `alarm type` 关键字
6. **内存泄漏监测** - 通过 `free -m` 监测内存使用，连续8次（12小时）增长则告警
7. **CPU0 利用率监测** - 连续6次（3分钟）超过90%则告警
8. **命令响应时间监测** - 检测 `lscpu`、`anytest frameallinfo` 等命令执行时间是否超过阈值
9. **sig 信号监测** - 监控非白名单信号（除 sig 15/61 外）
10. **自定义命令** - 支持配置内部命令扩展观察点

## 系统要求

- Python 3.6–3.9（已做兼容，无 3.10+ 语法）
- Euler ARM 操作系统
- 无第三方依赖（仅标准库 + Python 3.6 下可选 `dataclasses`）；配置仅支持 **JSON**（便于离线/ARM，无需 PyYAML）

## 快速开始

### 方式一：通过 Web 界面部署（推荐）

1. 在 Web 平台添加阵列并连接
2. 点击「部署 Agent」按钮
3. 部署完成后，点击「启动 Agent」

### 方式二：手动安装

```bash
# 从 observation_web 项目复制 agent 目录到阵列（需重命名为 observation_points）
scp -r agent admin@阵列IP:/opt/observation_points

# 登录阵列后
# 安装依赖（Python 3.6 需要 dataclasses）
pip3 install -r /opt/observation_points/requirements.txt

# 复制配置文件（仅 JSON）
mkdir -p /etc/observation-points
cp /opt/observation_points/config.json /etc/observation-points/
```

### 运行

```bash
# 直接运行
python3 -m observation_points

# 指定配置文件（仅支持 .json）
python3 -m observation_points -c /etc/observation-points/config.json

# 试运行模式（不实际告警）
python3 -m observation_points --dry-run

# 调试模式
python3 -m observation_points --log-level DEBUG

# 只显示 WARNING 及以上级别告警
python3 -m observation_points --alert-level WARNING

# 只显示 ERROR 级别告警
python3 -m observation_points --alert-level ERROR
```

### systemd 服务

创建 `/etc/systemd/system/observation-points.service`：

```ini
[Unit]
Description=Observation Points Monitor
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m observation_points -c /etc/observation-points/config.json
Restart=always
RestartSec=10
User=root
WorkingDirectory=/opt/observation_points

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
systemctl daemon-reload
systemctl enable observation-points
systemctl start observation-points
```

## 配置说明

配置文件为 **JSON** 格式，主要包含：

### 全局配置

```json
{
  "global": {
    "check_interval": 30,
    "max_memory_mb": 50,
    "subprocess_timeout": 10
  }
}
```

### 告警配置

```json
{
  "reporter": {
    "output": "file",
    "file_path": "/var/log/observation-points/alerts.log",
    "cooldown_seconds": 300
  }
}
```

### 观察点配置

每个观察点可单独配置，完整示例见 `config.json`。

## 观察点详解

### 误码监测 (error_code)

监测端口误码（真正的误码，不包括丢包和聚合值）和 PCIe AER 错误。

- **监测指标**：`rx_crc_errors`、`fcs_errors`、`rx_frame_errors`、`tx_carrier_errors`
- **数据源**：sysfs、ethtool
- **检测方式**：增量检测，仅新增误码超过阈值时告警
- **告警级别**：WARNING

### 链路状态监测 (link_status)

监测网络端口的 carrier/operstate 状态变化。

- **数据源**：sysfs (/sys/class/net/*/carrier)
- **检测方式**：状态变化即告警
- **告警级别**：WARNING

### 卡修复监测 (card_recovery)

监测日志中的 `recover chiperr` 事件。

- **数据源**：`/OSM/log/cur_debug/messages`
- **检测方式**：关键字匹配，统计总次数，记录最近3次详情（时间+PCIe槽位）
- **告警级别**：ERROR

### 敏感信息监测 (sensitive_info)

监测日志中是否打印了敏感信息。

- **数据源**：配置的日志文件
- **检测方式**：正则匹配
- **告警级别**：ERROR

### AlarmType 监测 (alarm_type)

监测日志中的 `alarm type` 关键字（不区分大小写）。

- **数据源**：`/OSM/log/cur_debug/messages`
- **检测方式**：正则匹配 `alarm\s*type`
- **告警级别**：WARNING

### 内存泄漏监测 (memory_leak)

通过 `free -m` 监测内存使用量。

- **数据源**：`free -m` 命令
- **检测方式**：连续8次（默认间隔1.5h，共12h）内存使用量持续增长则告警
- **告警级别**：ERROR
- **特性**：持续告警（sticky），一旦触发则持续上报直到程序退出

### CPU0 利用率监测 (cpu_usage)

监测 CPU0 的利用率。

- **数据源**：`/proc/stat` 或 `top` 命令
- **检测方式**：连续6次（默认间隔30s，共3分钟）超过90%则告警
- **告警级别**：ERROR
- **特性**：持续告警（sticky），一旦触发则持续上报直到程序退出

### 命令响应时间监测 (cmd_response)

检测指定命令的执行时间。

- **默认命令**：`lscpu`、`anytest frameallinfo`
- **检测方式**：执行时间超过阈值（默认1s）则告警
- **告警级别**：ERROR

### sig 信号监测 (sig_monitor)

监测日志中的 sig 信号记录。

- **数据源**：`/OSM/log/cur_debug/messages`
- **白名单**：sig 15、sig 61（不告警）
- **检测方式**：非白名单信号出现即告警
- **告警级别**：ERROR

### 自定义命令 (custom_commands)

支持配置内部命令作为观察点。

```json
{
  "custom_commands": {
    "enabled": true,
    "commands": [
      {
        "name": "check_port_health",
        "command": "/opt/internal/check_port.sh",
        "interval": 30,
        "parse_type": "json",
        "alert_conditions": [
          {
            "field": "status",
            "operator": "!=",
            "value": "OK",
            "level": "error"
          }
        ]
      }
    ]
  }
}
```

## 告警级别

| 观察点 | 默认级别 |
|--------|----------|
| 误码 (error_code) | WARNING |
| 链路状态 (link_status) | WARNING |
| 卡修复 (card_recovery) | ERROR |
| 敏感信息 (sensitive_info) | ERROR |
| AlarmType (alarm_type) | WARNING |
| 内存泄漏 (memory_leak) | ERROR |
| CPU0 利用率 (cpu_usage) | ERROR |
| 命令响应时间 (cmd_response) | ERROR |
| sig 信号 (sig_monitor) | ERROR |

使用 `--alert-level` 参数可以筛选显示的告警级别：
- `INFO`: 显示所有告警
- `WARNING`: 只显示 WARNING 及以上
- `ERROR`: 只显示 ERROR 及以上

## 监控从启动时刻开始

所有日志类监控点（卡修复、敏感信息、AlarmType、sig信号）都从脚本启动时刻开始监控，不会处理历史日志数据。

## 持续告警 (Sticky Alert)

内存泄漏和 CPU 利用率监控使用"持续告警"机制：
- 一旦触发告警条件，会持续上报直到程序退出
- 不受告警冷却时间限制
- 告警消息会标记"（持续）"前缀

## 资源控制

系统设计目标：

- 常驻内存 < 50MB
- CPU 平均占用 < 2%

通过以下方式控制资源：

1. 单进程、无重型框架
2. 可配置的采集周期
3. 滑动窗口使用 `deque(maxlen=N)` 固定内存
4. 子进程必须设置 timeout
5. 告警冷却避免重复告警

## 告警输出

告警输出为 JSON 格式：

```json
{
  "observer_name": "error_code",
  "level": "warning",
  "message": "检测到误码: eth0.rx_crc_errors 新增 5",
  "timestamp": "2024-01-15T10:30:45",
  "details": {...}
}
```

## 扩展开发

### 添加新观察点

1. 在 `observers/` 目录创建新文件
2. 继承 `BaseObserver` 类
3. 实现 `check()` 方法
4. 在 `scheduler.py` 的 `_get_observer_classes()` 中注册
5. 在 `observers/__init__.py` 中导出

```python
from ..core.base import BaseObserver, ObserverResult, AlertLevel

class MyObserver(BaseObserver):
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        # 初始化
    
    def check(self) -> ObserverResult:
        # 执行检查
        return self.create_result(
            has_alert=True,
            alert_level=AlertLevel.WARNING,
            message="检测到问题",
            details={...},
            sticky=False  # 是否持续告警
        )
```

## 协议范围

本系统专注于前端存储协议（主机到阵列）：

- iSCSI
- NAS
- NVMe

不涉及后端盘通信。

## 许可证

内部使用
