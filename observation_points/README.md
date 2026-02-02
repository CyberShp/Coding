# 观察点监控系统

轻量级、可扩展的全局观察点监控服务，用于 Euler ARM 存储阵列。

## 功能特性

1. **误码监测** - 端口误码 + PCIe 链路误码，增量检测
2. **链路状态监测** - link down/up 事件检测，支持白名单
3. **卡修复监测** - recovery/probe/remove 事件监控
4. **亚健康监测** - 时延、丢包、乱序激增检测
5. **敏感信息监测** - 日志中的密码、NQN、IQN 等敏感信息检测
6. **性能波动监测** - IOPS、带宽、时延波动率超 10% 告警
7. **自定义命令** - 支持配置内部命令扩展观察点

## 系统要求

- Python 3.9+
- Euler ARM 操作系统
- 依赖：PyYAML

## 快速开始

### 安装

```bash
# 克隆或复制项目到目标目录
cp -r observation_points /opt/observation_points

# 安装依赖
pip3 install -r requirements.txt

# 复制配置文件
mkdir -p /etc/observation-points
cp observation_points/config.yaml /etc/observation-points/
```

### 运行

```bash
# 直接运行
python3 -m observation_points

# 指定配置文件
python3 -m observation_points -c /etc/observation-points/config.yaml

# 试运行模式（不实际告警）
python3 -m observation_points --dry-run

# 调试模式
python3 -m observation_points --log-level DEBUG
```

### systemd 服务

创建 `/etc/systemd/system/observation-points.service`：

```ini
[Unit]
Description=Observation Points Monitor
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m observation_points -c /etc/observation-points/config.yaml
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

配置文件为 YAML 格式，主要包含：

### 全局配置

```yaml
global:
  check_interval: 30        # 默认检查间隔（秒）
  max_memory_mb: 50         # 内存上限
  subprocess_timeout: 10    # 子进程超时
```

### 告警配置

```yaml
reporter:
  output: file              # file, syslog, both, console
  file_path: /var/log/observation-points/alerts.log
  cooldown_seconds: 300     # 相同告警冷却时间
```

### 观察点配置

每个观察点可单独配置：

```yaml
observers:
  error_code:
    enabled: true
    interval: 30
    threshold: 0
    # ...
```

## 观察点详解

### 误码监测 (error_code)

监测端口误码（rx_errors、tx_errors 等）和 PCIe AER 错误。

- 数据源：sysfs、ethtool
- 检测方式：增量检测，仅新增误码超过阈值时告警
- 配置项：
  - `threshold`: 误码增量阈值
  - `ports`: 监控的端口列表
  - `pcie_enabled`: 是否监控 PCIe

### 链路状态监测 (link_status)

监测网络端口的 carrier/operstate 状态变化。

- 数据源：sysfs (/sys/class/net/*/carrier)
- 检测方式：状态变化即告警
- 配置项：
  - `whitelist`: 白名单端口（不告警）
  - `interval`: 建议设置较短（5s）

### 卡修复监测 (card_recovery)

监测日志中的 recovery/probe/remove 事件。

- 数据源：/OSM/log/coffer_log/cur_debug/messages
- 检测方式：关键字匹配 + 排除模式
- 配置项：
  - `log_path`: 日志路径
  - `keywords`: 监控的关键字
  - `exclude_patterns`: 排除模式

### 亚健康监测 (subhealth)

监测时延、丢包、乱序等指标的激增。

- 数据源：sysfs、/proc/net/netstat、内部命令
- 检测方式：滑动窗口 + 激增阈值
- 配置项：
  - `window_size`: 滑动窗口大小
  - `spike_threshold_percent`: 激增阈值（相对均值）

### 敏感信息监测 (sensitive_info)

监测日志中是否打印了敏感信息。

- 数据源：配置的日志文件
- 检测方式：正则匹配
- 配置项：
  - `log_paths`: 日志路径列表
  - `patterns`: 敏感信息正则模式

### 性能波动监测 (performance)

监测 IOPS、带宽、时延的波动率。

- 数据源：sysfs、/proc/diskstats、内部命令
- 检测方式：滑动窗口 + 波动率阈值
- 配置项：
  - `fluctuation_threshold_percent`: 波动阈值（默认 10%）
  - `min_iops_threshold`: 最小 IOPS 阈值
  - `dimensions`: 监测维度（bond/port）

### 自定义命令 (custom_commands)

支持配置内部命令作为观察点。

```yaml
custom_commands:
  enabled: true
  commands:
    - name: check_port_health
      command: /opt/internal/check_port.sh
      interval: 30
      parse_type: json
      alert_conditions:
        - field: status
          operator: '!='
          value: 'OK'
          level: error
```

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
  "message": "检测到误码: eth0.rx_errors 新增 5",
  "timestamp": "2024-01-15T10:30:45",
  "details": {...}
}
```

## 扩展开发

### 添加新观察点

1. 在 `observers/` 目录创建新文件
2. 继承 `BaseObserver` 类
3. 实现 `check()` 方法
4. 在 `scheduler.py` 中注册

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
            details={...}
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
