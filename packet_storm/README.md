# Packet Storm - 存储协议异常报文测试工具

**Packet Storm** 是一款基于 Python 的存储协议异常报文构造与发送工具，用于验证存储设备对异常报文的容错能力和安全防护能力。支持 iSCSI、NVMe-oF/TCP、NAS (NFS/SMB) 协议，可通过 Scapy、Raw Socket 或 DPDK 发送异常报文。

## 核心特性

- **多协议支持**：iSCSI (RFC 7143)、NVMe-oF/TCP、NFS v4.x、SMB 3.1.1
- **丰富的异常类型**：10 种通用异常 + 协议专属异常 + 协议模糊测试
- **多传输后端**：Scapy（便携）、Raw Socket（高性能）、DPDK（线速 10Gbps+）
- **TCP 流追踪**：捕获现有会话的 seq/ack 进行中间人注入
- **双 UI**：CLI（Click + Rich）+ Web UI（FastAPI + Vue 3 + Element Plus）
- **实时监控**：WebSocket 推送统计、ECharts 可视化仪表板
- **批量编排**：JSON 批量测试文件、场景序列执行、结果聚合
- **定时调度**：延迟执行、周期任务、Cron 表达式
- **稳定性测试**：72h+ 长时间运行、内存泄漏检测、定期报告
- **进程守护**：自动崩溃重启、健康检查、PID 文件管理

## 目录结构

```
packet_storm/
├── configs/                  # 配置文件
│   └── default.json          # 默认配置模板
├── packet_storm/             # Python 主包
│   ├── __init__.py
│   ├── __main__.py           # python -m packet_storm 入口
│   ├── core/                 # 核心框架
│   │   ├── config.py         # 配置管理器（加载/合并/验证）
│   │   ├── engine.py         # 发包引擎（编排核心）
│   │   ├── session.py        # 会话生命周期管理
│   │   ├── registry.py       # 插件注册表
│   │   ├── daemon.py         # 进程守护（健康检查/自动重启）
│   │   ├── orchestrator.py   # 批量测试编排器
│   │   ├── scheduler.py      # 定时/周期任务调度器
│   │   └── stability.py      # 稳定性测试框架
│   ├── protocols/            # 协议实现
│   │   ├── base.py           # 协议构建器基类
│   │   ├── fields.py         # L2-L4 头部构建辅助
│   │   └── iscsi/            # iSCSI 协议（MVP）
│   │       ├── constants.py  # RFC 7143 常量定义
│   │       ├── pdu.py        # Scapy 自定义 PDU 层
│   │       ├── builder.py    # iSCSI 报文构建器
│   │       ├── session.py    # iSCSI 会话状态机
│   │       └── anomalies.py  # iSCSI 专属异常
│   ├── anomaly/              # 异常引擎
│   │   ├── base.py           # 异常生成器基类
│   │   ├── registry.py       # 异常注册与工厂
│   │   ├── fuzzer.py         # 协议模糊测试器
│   │   └── generic/          # 10 种通用异常
│   ├── transport/            # 传输后端
│   │   ├── base.py           # 传输接口定义
│   │   ├── scapy_send.py     # Scapy sendp 后端
│   │   ├── raw_socket.py     # AF_PACKET Raw Socket
│   │   ├── reconnect.py      # 自动重连包装器
│   │   └── dpdk/             # DPDK ctypes 绑定
│   ├── capture/              # 流量捕获
│   │   ├── sniffer.py        # 报文嗅探器
│   │   └── flow_tracker.py   # TCP 流追踪器
│   ├── monitor/              # 监控统计
│   │   ├── stats.py          # 线程安全计数器
│   │   ├── display.py        # Rich 终端仪表板
│   │   └── exporter.py       # CSV/JSON 导出
│   ├── cli/                  # 命令行界面
│   │   ├── main.py           # Click CLI 主入口
│   │   └── commands/         # 子命令模块
│   └── web/                  # Web 界面
│       ├── app.py            # FastAPI 应用工厂
│       ├── ws.py             # WebSocket 实时推送
│       └── api/              # REST API 端点
├── web/                      # Vue 3 前端
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.vue           # 全局布局
│       ├── router/           # Vue Router
│       ├── stores/           # Pinia 状态管理
│       └── views/            # 页面组件
├── tests/                    # 单元测试
├── pyproject.toml            # 项目元数据
├── requirements.txt          # pip 依赖
└── README.md
```

## 快速开始

### 环境要求

- **Python**: >= 3.10
- **操作系统**: Linux (推荐 x86_64)
- **权限**: 发送原始报文需要 root/sudo 权限
- **可选**: DPDK 20.11-23.11 LTS（线速发包场景）

### 安装

```bash
# 1. 克隆仓库
git clone <repo-url>
cd packet_storm

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装核心依赖
pip install -e .

# 4. 安装 Web UI 依赖（可选）
pip install -e ".[web]"

# 5. 安装开发依赖（可选）
pip install -e ".[dev]"

# 6. 安装所有依赖
pip install -e ".[all]"
```

### 前端安装（可选）

```bash
cd web
npm install
npm run dev       # 开发模式
npm run build     # 生产构建
```

## 使用指南

### CLI 命令行

```bash
# 查看帮助
packet-storm --help

# 使用默认配置发包
sudo packet-storm run start

# 指定配置文件和协议
sudo packet-storm -c my_config.json run start -p iscsi

# 指定报文类型和数量
sudo packet-storm run start -p iscsi -t login_request -n 1000

# 单步调试模式
sudo packet-storm run step -p iscsi -t scsi_read

# 使用 Raw Socket 后端
sudo packet-storm run start --backend raw_socket

# 查看可用异常类型
packet-storm list anomalies

# 查看协议报文类型
packet-storm list protocols

# 查看/修改配置
packet-storm config show
packet-storm config set network.dst_ip 10.0.0.1
packet-storm config export backup.json

# 实时监控面板
sudo packet-storm monitor dashboard

# 导出统计到 CSV
packet-storm monitor export --format csv -o stats.csv
```

### 批量测试

```bash
# 创建批量测试模板
packet-storm batch create-template batch_test.json

# 验证批量测试文件
packet-storm batch validate batch_test.json

# 执行批量测试
sudo packet-storm batch run batch_test.json --export results.json

# 失败时停止
sudo packet-storm batch run batch_test.json --stop-on-failure
```

批量测试文件格式：

```json
{
    "batch_name": "iSCSI 综合测试",
    "scenarios": [
        {
            "name": "Login Opcode Fuzz",
            "config_overrides": {
                "protocol.type": "iscsi",
                "network.dst_ip": "192.168.1.200"
            },
            "anomalies": [
                {
                    "type": "field_tamper",
                    "enabled": true,
                    "target_layer": "iscsi",
                    "target_field": "opcode",
                    "mode": "random",
                    "count": 100
                }
            ],
            "execution": {
                "repeat": 1,
                "interval_ms": 50
            }
        }
    ]
}
```

### 定时调度

```bash
# 延迟 60 秒执行
sudo packet-storm schedule delayed --delay 60 --name "Delayed Test"

# 每 5 分钟执行一次，最多 10 次
sudo packet-storm schedule periodic --interval 300 --max-runs 10

# Cron 表达式调度（每小时整点执行）
sudo packet-storm schedule cron --expr "0 * * * *" --name "Hourly Test"
```

### 稳定性测试

```bash
# 72 小时稳定性测试
sudo packet-storm stability run --duration 72

# 快速 10 分钟检查
sudo packet-storm stability quick --minutes 10

# 自定义参数
sudo packet-storm stability run \
    --duration 24 \
    --checkpoint-interval 5 \
    --memory-limit 512 \
    --report-dir ./reports
```

### Web UI

```bash
# 启动后端 API 服务器（端口 8080）
packet-storm web start --port 8080

# 前端开发服务器
cd web && npm run dev
```

Web UI 功能：
- **Dashboard**: 实时发包速率、吞吐量图表、异常统计
- **配置管理**: 可视化配置编辑、JSON 预览、导入导出
- **会话控制**: 启动/停止/暂停/恢复/单步
- **异常浏览**: 异常类型列表、分类筛选
- **报文日志**: 发送记录、Hex Dump 查看、导出

### DPDK 高速发包（可选）

```bash
# 检查 DPDK 状态
packet-storm dpdk status

# 设置 Hugepages
sudo packet-storm dpdk hugepage setup --size 2M --count 1024

# 绑定网卡到 DPDK 驱动
sudo packet-storm dpdk bind --pci 0000:01:00.0 --driver vfio-pci

# 使用 DPDK 后端发包
sudo packet-storm run start --backend dpdk
```

## 配置详解

配置文件为 JSON 格式，支持默认配置 + 用户配置的层叠合并。

```json
{
    "global": {
        "log_level": "INFO",
        "log_file": "logs/packet_storm.log"
    },
    "network": {
        "interface": "eth0",
        "src_mac": "auto",
        "dst_mac": "ff:ff:ff:ff:ff:ff",
        "src_ip": "192.168.1.100",
        "dst_ip": "192.168.1.200"
    },
    "transport": {
        "backend": "scapy",
        "rate_limit": {
            "enabled": false,
            "mode": "pps",
            "value": 100000
        }
    },
    "protocol": {
        "type": "iscsi",
        "iscsi": {
            "target_port": 3260,
            "initiator_name": "iqn.2024-01.com.packetstorm:initiator",
            "target_name": "iqn.2024-01.com.storage:target"
        }
    },
    "anomalies": [
        {
            "type": "field_tamper",
            "enabled": true,
            "target_layer": "iscsi",
            "target_field": "opcode",
            "mode": "random",
            "count": 100
        }
    ],
    "execution": {
        "repeat": 1,
        "interval_ms": 100,
        "duration_seconds": 0
    }
}
```

## 异常类型参考

### 通用异常（适用于所有协议）

| 异常类型 | 说明 | 关键参数 |
|---------|------|---------|
| `field_tamper` | 篡改报文字段 | `target_layer`, `target_field`, `mode`(random/zero/max/bitflip) |
| `truncation` | 截断报文 | `mode`(fixed/random/protocol_min/half) |
| `padding` | 添加填充数据 | `mode`(random/zeros/pattern/overflow) |
| `checksum` | 校验和错误 | `target`(ip/tcp/udp/all) |
| `replay` | 重放报文 | `mode`(exact/delayed/modified/burst) |
| `malformed` | 畸形报文 | `mode`(reserved_bits/invalid_version/header_length) |
| `fragmentation` | IP 分片攻击 | `mode`(tiny/overlapping/incomplete/excessive) |
| `sequence` | TCP 序列号操控 | `mode`(out_of_order/dup_ack/window/seq_wrap) |
| `flood` | 泛洪攻击 | `mode`(syn/rst/fin/udp/source_randomize) |
| `fuzzer` | 协议模糊测试 | `strategy`(mutation/field_walk/structure/generation) |

### iSCSI 专属异常

| 异常方法 | 说明 |
|---------|------|
| `invalid_opcode` | 非法操作码 |
| `invalid_itt` | 非法 Initiator Task Tag |
| `data_length_mismatch` | 数据段长度不匹配 |
| `login_key_tamper` | 篡改登录协商参数 |
| `sequence_manipulation` | CmdSN/ExpStatSN 操控 |
| `invalid_login_stage` | 无效登录阶段 |
| `version_mismatch` | 版本号不匹配 |
| `cdb_overflow` | CDB 溢出攻击 |
| `zero_length_pdu` | 零长度 PDU |

### 支持的 iSCSI PDU 类型

| PDU 类型 | CLI 标识 | 说明 |
|---------|---------|------|
| Login Request | `login_request` | 登录请求（支持 Security/Operational 阶段） |
| SCSI Command | `scsi_command` | 通用 SCSI 命令 |
| SCSI Read | `scsi_read` | READ(10) 命令 |
| SCSI Write | `scsi_write` | WRITE(10) 命令（支持 Immediate Data） |
| Data-Out | `data_out` | 写数据 PDU |
| NOP-Out | `nop_out` | 心跳/Keepalive |
| Logout | `logout_request` | 登出请求 |
| Task Management | `task_management` | 任务管理（Abort/Reset/Clear） |
| Text Request | `text_request` | 文本请求（SendTargets 等） |

## 架构设计

```
┌──────────────────────────────────────────────────────────┐
│                    用户界面层                              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│   │  CLI (Click) │  │  Web (Fast   │  │  WebSocket   │  │
│   │  + Rich      │  │  API + Vue)  │  │  (实时推送)   │  │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
├──────────┴─────────────────┴─────────────────┴──────────┤
│                    核心引擎层                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│   │  Engine  │  │ Orchestr │  │ Scheduler│              │
│   │  (编排)   │  │  (批量)   │  │  (调度)  │              │
│   └────┬─────┘  └─────┬────┘  └─────┬────┘              │
│        │              │              │                    │
│   ┌────┴────┐  ┌──────┴────┐  ┌─────┴─────┐            │
│   │ Session │  │ Config    │  │ Stability │            │
│   │ (会话)   │  │ Manager  │  │ Runner    │            │
│   └─────────┘  └───────────┘  └───────────┘            │
├──────────────────────────────────────────────────────────┤
│                    协议构建层                              │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐          │
│   │  iSCSI    │  │  NVMe-oF  │  │  NAS      │          │
│   │  Builder  │  │  (计划中)  │  │  (计划中)  │          │
│   └─────┬─────┘  └───────────┘  └───────────┘          │
│         │                                                │
│   ┌─────┴─────────────────────────────────┐              │
│   │  Scapy 自定义层 (BHS/PDU/Fields)       │              │
│   └───────────────────────────────────────┘              │
├──────────────────────────────────────────────────────────┤
│                    异常引擎层                              │
│   ┌────────────────┐  ┌────────────────┐                │
│   │  通用异常 (10)  │  │  协议专属异常    │                │
│   │  field_tamper   │  │  iSCSI (12)    │                │
│   │  truncation     │  │  NVMe-oF (TBD) │                │
│   │  padding ...    │  │  NAS (TBD)     │                │
│   └────────────────┘  └────────────────┘                │
│   ┌────────────────────────────────────────┐            │
│   │  Protocol Fuzzer (mutation/walk/gen)    │            │
│   └────────────────────────────────────────┘            │
├──────────────────────────────────────────────────────────┤
│                    传输层                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│   │  Scapy   │  │  Raw     │  │  DPDK    │              │
│   │  sendp   │  │  Socket  │  │  ctypes  │              │
│   └──────────┘  └──────────┘  └──────────┘              │
│   ┌────────────────────────────────────────┐            │
│   │  ReconnectingTransport (自动重连包装)   │            │
│   └────────────────────────────────────────┘            │
├──────────────────────────────────────────────────────────┤
│                    监控层                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│   │  Stats   │  │  Rich    │  │  CSV/    │              │
│   │ Collector│  │ Dashboard│  │  JSON    │              │
│   └──────────┘  └──────────┘  └──────────┘              │
└──────────────────────────────────────────────────────────┘
```

## 插件扩展

### 添加新协议

1. 在 `protocols/` 下创建协议目录
2. 实现 `BaseProtocolBuilder` 子类
3. 创建 Scapy 自定义层
4. 在 `__init__.py` 中注册到 `protocol_registry`

```python
from packet_storm.protocols.base import BaseProtocolBuilder
from packet_storm.core.registry import protocol_registry

class MyProtocolBuilder(BaseProtocolBuilder):
    PROTOCOL_NAME = "myprotocol"

    def build_packet(self, packet_type=None, **kwargs):
        ...

    def list_packet_types(self):
        return ["type_a", "type_b"]

    def list_fields(self, packet_type=None):
        return {"field1": "Description"}

# 注册
protocol_registry.register("myprotocol", MyProtocolBuilder)
```

### 添加新异常类型

1. 继承 `BaseAnomaly`
2. 使用 `@register_anomaly` 装饰器注册

```python
from packet_storm.anomaly.base import BaseAnomaly
from packet_storm.anomaly.registry import register_anomaly

@register_anomaly("my_anomaly")
class MyAnomaly(BaseAnomaly):
    NAME = "my_anomaly"
    DESCRIPTION = "Custom anomaly description"
    CATEGORY = "generic"

    def apply(self, packet):
        pkt = self._copy_packet(packet)
        # ... 修改报文 ...
        return pkt
```

### 添加新传输后端

1. 继承 `TransportBackend`
2. 注册到 `transport_registry`

```python
from packet_storm.transport.base import TransportBackend
from packet_storm.core.registry import transport_registry

class MyTransport(TransportBackend):
    def open(self, network_config):
        ...
    def send(self, packet_bytes):
        ...
    def send_batch(self, packets):
        ...
    def close(self):
        ...

transport_registry.register("mytransport", MyTransport)
```

## Web API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/status` | 系统状态 |
| GET | `/api/config` | 获取当前配置 |
| POST | `/api/config` | 更新配置 |
| POST | `/api/config/import` | 导入配置文件 |
| GET | `/api/config/export` | 导出配置文件 |
| GET | `/api/session/status` | 会话状态 |
| POST | `/api/session/start` | 启动发包 |
| POST | `/api/session/stop` | 停止发包 |
| POST | `/api/session/pause` | 暂停发包 |
| POST | `/api/session/resume` | 恢复发包 |
| POST | `/api/session/step` | 单步发包 |
| GET | `/api/anomaly/list` | 异常类型列表 |
| GET | `/api/anomaly/categories` | 异常分类 |
| GET | `/api/monitor/stats` | 实时统计 |
| POST | `/api/monitor/reset` | 重置统计 |
| GET | `/api/monitor/export/csv` | 导出 CSV |
| POST | `/api/batch/run` | 启动批量测试 |
| POST | `/api/batch/stop` | 停止批量测试 |
| GET | `/api/batch/status` | 批量测试状态 |
| GET | `/api/scheduler/tasks` | 列出调度任务 |
| POST | `/api/scheduler/tasks/{id}/cancel` | 取消任务 |
| GET | `/api/dpdk/status` | DPDK 状态 |
| POST | `/api/dpdk/bind` | 绑定网卡 |
| WS | `/ws/stats` | WebSocket 实时统计 |

## 开发

### 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行所有测试
pytest

# 运行特定测试模块
pytest tests/test_core/test_config.py -v

# 运行带覆盖率
pytest --cov=packet_storm
```

### 代码规范

```bash
# 格式检查
ruff check packet_storm/

# 自动修复
ruff check --fix packet_storm/
```

## 实现阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 核心框架 + iSCSI 协议 + 基础异常 + CLI | ✅ 完成 |
| Phase 2 | 完整异常引擎 + 模糊测试 + TCP 流追踪 | ✅ 完成 |
| Phase 3 | DPDK ctypes 集成（EAL/mempool/port/TX-RX） | ✅ 完成 |
| Phase 4 | 监控统计 + Rich 终端面板 + CSV/JSON 导出 | ✅ 完成 |
| Phase 5 | Web UI（FastAPI 后端 + Vue 3 前端 + WebSocket） | ✅ 完成 |
| Phase 6 | NVMe-oF/TCP 协议（自定义 Scapy 层 + 异常） | 📋 计划中 |
| Phase 7 | NAS 协议（NFS v4 ONC-RPC + SMB 3.1.1） | 📋 计划中 |
| Phase 8 | 生产加固（守护进程/批量编排/调度/稳定性测试） | ✅ 完成 |

## 许可证

MIT License
