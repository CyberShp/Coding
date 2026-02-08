"""
Mock data generator for demo purposes — includes all new observers
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import random
import json
import math

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db.database import init_db, get_db, create_tables
from backend.models.alert import AlertModel
from backend.models.array import ArrayModel
from backend.models.traffic import PortTrafficModel

# Mock arrays
MOCK_ARRAYS = [
    {"array_id": "array-001", "name": "存储阵列-A", "host": "192.168.1.101", "port": 22, "username": "admin"},
    {"array_id": "array-002", "name": "存储阵列-B", "host": "192.168.1.102", "port": 22, "username": "admin"},
    {"array_id": "array-003", "name": "测试阵列-C", "host": "192.168.1.103", "port": 22, "username": "admin"},
]

# 端口列表（模拟阵列上的网络端口）
MOCK_PORTS = ["eth0", "eth1", "eth2", "eth3", "bond0", "bond1"]

# Mock alerts with realistic details — all observer types
ALERT_TEMPLATES = [
    # ===== alarm_type: type 1, send alarm =====
    {
        "observer_name": "alarm_type",
        "level": "error",
        "message": "新上报 1 条告警, 当前活跃 3 个 | send alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
        "details": {
            "log_path": "/var/log/alarm/alarm_event.log",
            "new_send_alarms": [{
                "alarm_type": 1, "alarm_name": "disk_fault", "alarm_id": "0xA001",
                "timestamp": "2026-02-05T10:30:00", "is_send": True,
                "line": "2026-02-05 10:30:00 send alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
            }],
            "new_resume_alarms": [],
            "active_alarms": [
                {"alarm_name": "disk_fault", "alarm_id": "0xA001"},
                {"alarm_name": "power_fail", "alarm_id": "0xB002"},
                {"alarm_name": "fan_error", "alarm_id": "0xC003"},
            ],
        },
    },
    # alarm_type: type 1, resume alarm
    {
        "observer_name": "alarm_type",
        "level": "warning",
        "message": "恢复 1 条告警 | resume alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
        "details": {
            "log_path": "/var/log/alarm/alarm_event.log",
            "new_send_alarms": [],
            "new_resume_alarms": [{
                "alarm_type": 1, "alarm_name": "disk_fault", "alarm_id": "0xA001",
                "timestamp": "2026-02-05T11:00:00", "is_resume": True, "recovered": True,
                "line": "2026-02-05 11:00:00 resume alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
            }],
            "active_alarms": [{"alarm_name": "power_fail", "alarm_id": "0xB002"}],
        },
    },
    # alarm_type: type 0, history report
    {
        "observer_name": "alarm_type",
        "level": "info",
        "message": "历史告警上报 | send alarm: alarm type(0) alarm name(link_down_history) alarm id(0xD004)",
        "details": {
            "log_path": "/var/log/alarm/alarm_history.log",
            "new_send_alarms": [{
                "alarm_type": 0, "alarm_name": "link_down_history", "alarm_id": "0xD004",
                "is_history_report": True, "timestamp": "2026-02-05T09:15:00",
                "line": "2026-02-05 09:15:00 send alarm: alarm type(0) alarm name(link_down_history) alarm id(0xD004)",
            }],
            "new_resume_alarms": [],
            "active_alarms": [],
        },
    },
    # ===== error_code (端口级) =====
    {
        "observer_name": "error_code",
        "level": "warning",
        "message": "误码: eth1.rx_crc_errors +15; eth2.fcs_errors +3",
        "details": {"port_counters": {"eth1": {"rx_crc_errors": 15}, "eth2": {"fcs_errors": 3}}, "by_category": {"error_code": 2}},
    },
    # ===== link_status (端口级) =====
    {
        "observer_name": "link_status",
        "level": "warning",
        "message": "检测到链路状态变化: eth2 link DOWN",
        "details": {"changes": [{"port": "eth2", "change": "eth2 link DOWN"}], "current_states": {"eth2": {"carrier": "0", "operstate": "down"}}},
    },
    # ===== port_fec (端口级) =====
    {
        "observer_name": "port_fec",
        "level": "warning",
        "message": "FEC 模式变化: eth0: RS-FEC -> Off; eth3: BaseR-FEC -> Off",
        "details": {
            "changes": [
                {"port": "eth0", "old_fec": "RS-FEC", "new_fec": "Off"},
                {"port": "eth3", "old_fec": "BaseR-FEC", "new_fec": "Off"},
            ],
            "current": {"eth0": "Off", "eth1": "RS-FEC", "eth2": "RS-FEC", "eth3": "Off"},
        },
    },
    # ===== port_speed (端口级) =====
    {
        "observer_name": "port_speed",
        "level": "warning",
        "message": "端口速率变化: eth1: 100000Mb/s -> 25000Mb/s",
        "details": {
            "changes": [{"port": "eth1", "old_speed": "100000Mb/s", "new_speed": "25000Mb/s"}],
            "current": {"eth0": "100000Mb/s", "eth1": "25000Mb/s", "eth2": "100000Mb/s"},
        },
    },
    # ===== card_recovery (卡件级) =====
    {
        "observer_name": "card_recovery",
        "level": "error",
        "message": "卡修复统计: 总计 5 次，本次新增 2 次。最近2次: [2026-02-05 14:30:00 slot=dev(0:3b.0)], [2026-02-05 14:35:00 slot=top(0:5e.0)]",
        "details": {
            "total_count": 5, "new_count": 2,
            "recent_events": [
                {"timestamp": "2026-02-05 14:30:00", "slot": "dev(0:3b.0)", "line": "recover chiperr dev(0:3b.0)"},
                {"timestamp": "2026-02-05 14:35:00", "slot": "top(0:5e.0)", "line": "recover chiperr top(0:5e.0)"},
            ],
            "log_path": "/OSM/log/cur_debug/messages",
        },
    },
    # ===== pcie_bandwidth (卡件级) =====
    {
        "observer_name": "pcie_bandwidth",
        "level": "warning",
        "message": "PCIe 带宽降级: 0000:5e:00.0 宽度降级: 能力 x16 / 当前 x8 (Ethernet controller: Mellanox ConnectX-6); 0000:5e:00.0 速率降级: 能力 16GT/s / 当前 8GT/s",
        "details": {
            "downgrades": [
                "0000:5e:00.0 宽度降级: 能力 x16 / 当前 x8 (Ethernet controller: Mellanox ConnectX-6)",
                "0000:5e:00.0 速率降级: 能力 16GT/s / 当前 8GT/s (Ethernet controller: Mellanox ConnectX-6)",
            ],
            "current": {
                "0000:3b:00.0": {"width": "x4", "speed": "16GT/s", "cap_width": "x4", "cap_speed": "16GT/s", "desc": "NVMe SSD"},
                "0000:5e:00.0": {"width": "x8", "speed": "8GT/s", "cap_width": "x16", "cap_speed": "16GT/s", "desc": "Ethernet controller: Mellanox ConnectX-6"},
            },
        },
    },
    # ===== card_info (卡件级) =====
    {
        "observer_name": "card_info",
        "level": "error",
        "message": "卡件 No002 RunningState 异常: STOPPED (预期: RUNNING); 卡件 No002 HealthState 异常: DEGRADED (预期: NORMAL); 卡件 No003 Model 异常: (空) (预期: 非空)",
        "details": {
            "alerts": [
                {"card": "No002", "field": "RunningState", "value": "STOPPED", "expect": "RUNNING", "level": "error"},
                {"card": "No002", "field": "HealthState", "value": "DEGRADED", "expect": "NORMAL", "level": "error"},
                {"card": "No003", "field": "Model", "value": "(空)", "expect": "非空", "level": "warning"},
            ],
            "cards": {
                "No001": {"RunningState": "RUNNING", "HealthState": "NORMAL", "Model": "HBA-X200"},
                "No002": {"RunningState": "STOPPED", "HealthState": "DEGRADED", "Model": "HBA-X200"},
                "No003": {"RunningState": "RUNNING", "HealthState": "NORMAL", "Model": ""},
            },
            "total_cards": 3,
        },
    },
    # ===== memory_leak (系统级) =====
    {
        "observer_name": "memory_leak",
        "level": "warning",
        "message": "内存使用率超过阈值: 当前 82%, 阈值 75%",
        "details": {"current_percent": 82, "threshold": 75},
    },
    # ===== cpu_usage (系统级) =====
    {
        "observer_name": "cpu_usage",
        "level": "error",
        "message": "CPU 使用率超过阈值: 当前 95%, 阈值 80%",
        "details": {"current_percent": 95, "threshold": 80},
    },
    {
        "observer_name": "cpu_usage",
        "level": "info",
        "message": "CPU 使用率正常: 当前 25%",
        "details": {"current_percent": 25, "threshold": 80},
    },
    # ===== New observers =====
    # controller_state
    {
        "observer_name": "controller_state",
        "level": "error",
        "message": "控制器状态变化: 控制器 A: Online → Offline",
        "details": {"changes": [{"id": "A", "old_state": "Online", "new_state": "Offline"}], "all_states": {"A": "Offline", "B": "Online"}},
    },
    {
        "observer_name": "controller_state",
        "level": "info",
        "message": "控制器状态正常 (2 个控制器)",
        "details": {"all_states": {"A": "Online", "B": "Online"}},
    },
    # disk_state
    {
        "observer_name": "disk_state",
        "level": "error",
        "message": "磁盘状态变化: 磁盘 CTE0.5: Online → Offline",
        "details": {"changes": [{"id": "CTE0.5", "old_state": "Online", "new_state": "Offline"}]},
    },
    {
        "observer_name": "disk_state",
        "level": "warning",
        "message": "磁盘状态变化: 磁盘 CTE0.8: Online → Rebuilding",
        "details": {"changes": [{"id": "CTE0.8", "old_state": "Online", "new_state": "Rebuilding"}]},
    },
    # process_crash
    {
        "observer_name": "process_crash",
        "level": "critical",
        "message": "检测到 2 个进程崩溃事件: storage_svc[12345]: segfault; io_mgr[23456]: core_dump",
        "details": {
            "crashes": [
                {"type": "segfault", "process": "storage_svc[12345]", "line": "storage_svc[12345]: segfault at 0x0000", "source": "/var/log/messages"},
                {"type": "core_dump", "process": "io_mgr[23456]", "line": "io_mgr[23456]: core dumped", "source": "/var/log/messages"},
            ],
            "log_path": "/var/log/messages",
        },
    },
    # io_timeout
    {
        "observer_name": "io_timeout",
        "level": "error",
        "message": "检测到 3 个 IO 异常事件: io_timeout; scsi_error; buffer_io_error",
        "details": {
            "events": [
                {"type": "io_timeout", "summary": "io_timeout: sd 0:0:0:0 io timeout cmd", "line": "sd 0:0:0:0 io timeout cmd 0x28"},
                {"type": "scsi_error", "summary": "scsi_error: sd 0:0:0:0 SCSI error", "line": "sd 0:0:0:0 SCSI error: return code = 0x08"},
                {"type": "buffer_io_error", "summary": "buffer_io_error: Buffer I/O error on dev sda1", "line": "Buffer I/O error on dev sda1, sector 12345"},
            ],
            "log_path": "/var/log/messages",
        },
    },
]


def _generate_traffic_data(array_id: str, ports: list, minutes: int = 120) -> list:
    """
    Generate realistic-looking traffic data for the last N minutes.
    Simulates varying bandwidth with some natural patterns.
    """
    records = []
    now = datetime.now()
    interval_sec = 30  # one sample every 30s

    for port in ports:
        # Base traffic rate (random per port)
        base_tx = random.uniform(1e8, 5e9)  # 100Mbps ~ 5Gbps
        base_rx = random.uniform(1e8, 3e9)

        prev_tx_bytes = random.randint(10**12, 10**13)
        prev_rx_bytes = random.randint(10**12, 10**13)

        for i in range(minutes * 2):  # 2 samples per minute (every 30s)
            ts = now - timedelta(seconds=(minutes * 60) - (i * interval_sec))

            # Add some sinusoidal variation + noise
            phase = i / (minutes * 2) * math.pi * 4
            tx_rate = base_tx * (1 + 0.3 * math.sin(phase) + random.uniform(-0.1, 0.1))
            rx_rate = base_rx * (1 + 0.2 * math.sin(phase + 1) + random.uniform(-0.1, 0.1))

            tx_rate = max(0, tx_rate)
            rx_rate = max(0, rx_rate)

            tx_bytes_delta = int(tx_rate / 8 * interval_sec)
            rx_bytes_delta = int(rx_rate / 8 * interval_sec)
            prev_tx_bytes += tx_bytes_delta
            prev_rx_bytes += rx_bytes_delta

            records.append(PortTrafficModel(
                array_id=array_id,
                port_name=port,
                timestamp=ts,
                tx_bytes=prev_tx_bytes,
                rx_bytes=prev_rx_bytes,
                tx_rate_bps=round(tx_rate, 2),
                rx_rate_bps=round(rx_rate, 2),
            ))

    return records


async def create_mock_data():
    """Create mock data in database"""
    init_db()
    await create_tables()

    async for session in get_db():
        # Check if data already exists
        from sqlalchemy import select
        result = await session.execute(select(ArrayModel))
        if result.scalars().first():
            print("Mock data already exists, clearing and re-creating...")
            from sqlalchemy import delete
            await session.execute(delete(AlertModel))
            await session.execute(delete(PortTrafficModel))
            await session.execute(delete(ArrayModel))
            await session.commit()

        # Create arrays
        for arr_data in MOCK_ARRAYS:
            arr = ArrayModel(**arr_data)
            session.add(arr)
        await session.commit()
        print(f"Created {len(MOCK_ARRAYS)} mock arrays")

        # Create alerts — 50 alerts spread over 24 hours
        now = datetime.now()
        alert_count = 0
        for i in range(50):
            template = random.choice(ALERT_TEMPLATES)
            arr_id = random.choice(MOCK_ARRAYS)["array_id"]
            ts = now - timedelta(minutes=random.randint(0, 1440))

            alert = AlertModel(
                array_id=arr_id,
                observer_name=template["observer_name"],
                level=template["level"],
                message=template["message"],
                timestamp=ts,
                details=json.dumps(template["details"])
            )
            session.add(alert)
            alert_count += 1

        await session.commit()
        print(f"Created {alert_count} mock alerts (including all new observer types)")

        # Create traffic data — 2 hours for each array
        traffic_count = 0
        for arr_data in MOCK_ARRAYS:
            ports = random.sample(MOCK_PORTS, k=random.randint(3, 5))
            traffic_records = _generate_traffic_data(arr_data["array_id"], ports, minutes=120)
            session.add_all(traffic_records)
            traffic_count += len(traffic_records)

        await session.commit()
        print(f"Created {traffic_count} mock traffic data points (2 hours, multiple ports)")

        break


if __name__ == "__main__":
    asyncio.run(create_mock_data())
    print("\nMock data created successfully!")
