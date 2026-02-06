"""
Mock data generator for demo purposes
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import random
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db.database import init_db, get_db, create_tables
from backend.models.alert import AlertModel
from backend.models.array import ArrayModel

# Mock arrays
MOCK_ARRAYS = [
    {"array_id": "array-001", "name": "存储阵列-A", "host": "192.168.1.101", "port": 22, "username": "admin"},
    {"array_id": "array-002", "name": "存储阵列-B", "host": "192.168.1.102", "port": 22, "username": "admin"},
    {"array_id": "array-003", "name": "测试阵列-C", "host": "192.168.1.103", "port": 22, "username": "admin"},
]

# Mock alerts with realistic details
ALERT_TEMPLATES = [
    # alarm_type: type 1, send alarm (active alarm)
    {
        "observer_name": "alarm_type",
        "level": "error",
        "message": "新上报 1 条告警, 当前活跃 3 个 | send alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
        "details": {
            "log_path": "/var/log/alarm/alarm_event.log",
            "new_send_alarms": [
                {
                    "alarm_type": 1,
                    "alarm_name": "disk_fault",
                    "alarm_id": "0xA001",
                    "timestamp": "2026-02-05T10:30:00",
                    "is_send": True,
                    "line": "2026-02-05 10:30:00 send alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
                }
            ],
            "new_resume_alarms": [],
            "active_alarms": [
                {"alarm_name": "disk_fault", "alarm_id": "0xA001"},
                {"alarm_name": "power_fail", "alarm_id": "0xB002"},
                {"alarm_name": "fan_error", "alarm_id": "0xC003"},
            ],
        },
    },
    # alarm_type: type 1, resume alarm (recovery)
    {
        "observer_name": "alarm_type",
        "level": "warning",
        "message": "恢复 1 条告警 | resume alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
        "details": {
            "log_path": "/var/log/alarm/alarm_event.log",
            "new_send_alarms": [],
            "new_resume_alarms": [
                {
                    "alarm_type": 1,
                    "alarm_name": "disk_fault",
                    "alarm_id": "0xA001",
                    "timestamp": "2026-02-05T11:00:00",
                    "is_resume": True,
                    "recovered": True,
                    "line": "2026-02-05 11:00:00 resume alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)",
                }
            ],
            "active_alarms": [
                {"alarm_name": "power_fail", "alarm_id": "0xB002"},
                {"alarm_name": "fan_error", "alarm_id": "0xC003"},
            ],
        },
    },
    # alarm_type: type 0, history report (no recovery)
    {
        "observer_name": "alarm_type",
        "level": "info",
        "message": "历史告警上报 | send alarm: alarm type(0) alarm name(link_down_history) alarm id(0xD004)",
        "details": {
            "log_path": "/var/log/alarm/alarm_history.log",
            "new_send_alarms": [
                {
                    "alarm_type": 0,
                    "alarm_name": "link_down_history",
                    "alarm_id": "0xD004",
                    "is_history_report": True,
                    "timestamp": "2026-02-05T09:15:00",
                    "line": "2026-02-05 09:15:00 send alarm: alarm type(0) alarm name(link_down_history) alarm id(0xD004)",
                }
            ],
            "new_resume_alarms": [],
            "active_alarms": [],
        },
    },
    # alarm_type: type 1, multiple events
    {
        "observer_name": "alarm_type",
        "level": "error",
        "message": "新上报 2 条告警, 恢复 1 条, 当前活跃 4 个",
        "details": {
            "log_path": "/var/log/alarm/alarm_event.log",
            "new_send_alarms": [
                {
                    "alarm_type": 1,
                    "alarm_name": "temperature_high",
                    "alarm_id": "0xE005",
                    "timestamp": "2026-02-05T14:00:00",
                    "line": "2026-02-05 14:00:00 send alarm: alarm type(1) alarm name(temperature_high) alarm id(0xE005)",
                },
                {
                    "alarm_type": 1,
                    "alarm_name": "voltage_abnormal",
                    "alarm_id": "0xF006",
                    "timestamp": "2026-02-05T14:01:00",
                    "line": "2026-02-05 14:01:00 send alarm: alarm type(1) alarm name(voltage_abnormal) alarm id(0xF006)",
                },
            ],
            "new_resume_alarms": [
                {
                    "alarm_type": 1,
                    "alarm_name": "fan_error",
                    "alarm_id": "0xC003",
                    "timestamp": "2026-02-05T14:02:00",
                    "recovered": True,
                    "line": "2026-02-05 14:02:00 resume alarm: alarm type(1) alarm name(fan_error) alarm id(0xC003)",
                }
            ],
            "active_alarms": [
                {"alarm_name": "power_fail", "alarm_id": "0xB002"},
                {"alarm_name": "temperature_high", "alarm_id": "0xE005"},
                {"alarm_name": "voltage_abnormal", "alarm_id": "0xF006"},
                {"alarm_name": "disk_fault", "alarm_id": "0xA001"},
            ],
        },
    },
    # error_code
    {
        "observer_name": "error_code",
        "level": "error",
        "message": "检测到误码率异常: slot 5, 当前值 1.2e-5, 超过阈值 1.0e-6",
        "details": {"log_path": "/var/log/error_code.log", "slot": 5, "value": 1.2e-5, "threshold": 1.0e-6},
    },
    # link_status
    {
        "observer_name": "link_status",
        "level": "warning",
        "message": "链路状态变化: port 3 状态从 UP 变为 DOWN",
        "details": {"log_path": "/var/log/link_status.log", "port": 3, "old_state": "UP", "new_state": "DOWN"},
    },
    # memory_leak
    {
        "observer_name": "memory_leak",
        "level": "warning",
        "message": "内存使用率超过阈值: 当前 78%, 阈值 75%",
        "details": {"current_percent": 78, "threshold": 75},
    },
    # cpu_usage
    {
        "observer_name": "cpu_usage",
        "level": "info",
        "message": "CPU 使用率正常: 当前 25%",
        "details": {"current_percent": 25, "threshold": 80},
    },
    # card_recovery
    {
        "observer_name": "card_recovery",
        "level": "info",
        "message": "卡片自动修复完成: slot 2",
        "details": {"log_path": "/var/log/card_recovery.log", "slot": 2},
    },
    # cpu_usage high
    {
        "observer_name": "cpu_usage",
        "level": "error",
        "message": "CPU 使用率超过阈值: 当前 95%, 阈值 80%",
        "details": {"current_percent": 95, "threshold": 80},
    },
]


async def create_mock_data():
    """Create mock data in database"""
    init_db()
    await create_tables()
    
    async for session in get_db():
        # Check if data already exists
        from sqlalchemy import select
        result = await session.execute(select(ArrayModel))
        if result.scalars().first():
            print("Mock data already exists, skipping...")
            return
        
        # Create arrays
        for arr_data in MOCK_ARRAYS:
            arr = ArrayModel(**arr_data)
            session.add(arr)
        
        await session.commit()
        print(f"Created {len(MOCK_ARRAYS)} mock arrays")
        
        # Create alerts
        now = datetime.now()
        alert_count = 0
        for i in range(30):
            template = random.choice(ALERT_TEMPLATES)
            arr_id = random.choice(MOCK_ARRAYS)["array_id"]
            ts = now - timedelta(minutes=random.randint(0, 1440))  # Last 24 hours
            
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
        print(f"Created {alert_count} mock alerts")
        
        break


if __name__ == "__main__":
    asyncio.run(create_mock_data())
    print("Mock data created successfully!")
