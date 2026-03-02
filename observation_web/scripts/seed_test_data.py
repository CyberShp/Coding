#!/usr/bin/env python3
"""
Seed test data for observation_web.

Run from the observation_web directory:
    python scripts/seed_test_data.py
"""

import asyncio
import json
import random
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add the observation_web directory to Python path so imports work
script_dir = Path(__file__).parent.resolve()
project_dir = script_dir.parent
sys.path.insert(0, str(project_dir))
os.chdir(project_dir)

from backend.db.database import init_db, create_tables, AsyncSessionLocal
from backend.models.tag import TagModel
from backend.models.array import ArrayModel
from backend.models.alert import AlertModel
from backend.models.task_session import TaskSessionModel
from backend.models.alert_rule import AlertExpectationRuleModel
from backend.core.alert_expectation import init_builtin_rules


# Test data
TAGS = [
    {"name": "生产环境", "color": "#e74c3c", "description": "生产集群阵列"},
    {"name": "测试环境", "color": "#3498db", "description": "测试集群阵列"},
    {"name": "开发环境", "color": "#2ecc71", "description": "开发集群阵列"},
    {"name": "灾备站点", "color": "#9b59b6", "description": "灾备恢复站点"},
    {"name": "性能测试", "color": "#f39c12", "description": "性能压测专用"},
]

ARRAYS = [
    # 生产环境
    {"name": "prod-array-01", "host": "192.168.1.101", "tag_idx": 0},
    {"name": "prod-array-02", "host": "192.168.1.102", "tag_idx": 0},
    {"name": "prod-array-03", "host": "192.168.1.103", "tag_idx": 0},
    # 测试环境
    {"name": "test-array-01", "host": "192.168.2.101", "tag_idx": 1},
    {"name": "test-array-02", "host": "192.168.2.102", "tag_idx": 1},
    {"name": "test-array-03", "host": "192.168.2.103", "tag_idx": 1},
    {"name": "test-array-04", "host": "192.168.2.104", "tag_idx": 1},
    # 开发环境
    {"name": "dev-array-01", "host": "192.168.3.101", "tag_idx": 2},
    {"name": "dev-array-02", "host": "192.168.3.102", "tag_idx": 2},
    # 灾备站点
    {"name": "dr-array-01", "host": "10.0.1.101", "tag_idx": 3},
    {"name": "dr-array-02", "host": "10.0.1.102", "tag_idx": 3},
    # 性能测试
    {"name": "perf-array-01", "host": "172.16.1.101", "tag_idx": 4},
    {"name": "perf-array-02", "host": "172.16.1.102", "tag_idx": 4},
    # 无标签
    {"name": "standalone-01", "host": "192.168.100.1", "tag_idx": None},
]

ALERT_LEVELS = ["info", "warning", "error", "critical"]
OBSERVERS = [
    "cpu_usage", "memory_leak", "disk_io", "disk_space", "load_average",
    "network_errors", "link_status", "port_speed", "controller_state",
    "card_info", "alarm_type", "tcp_connections", "thermal"
]

ALERT_MESSAGES = {
    "cpu_usage": ["CPU 使用率 {v}% 超过阈值 80%", "CPU 使用率恢复正常: {v}%"],
    "memory_leak": ["检测到内存泄漏: 进程 {p} 增长 {v}MB", "内存使用稳定"],
    "disk_io": ["磁盘 {d} IOPS {v} 超过阈值", "磁盘 IO 恢复正常"],
    "disk_space": ["磁盘 {d} 使用率 {v}% 超过警戒线", "磁盘空间充足"],
    "load_average": ["系统负载过高: {v}", "系统负载恢复正常"],
    "network_errors": ["网卡 {i} 错误包数量异常: {v}", "网络状态正常"],
    "link_status": ["端口 {p} 链路状态变化: {s}", "端口链路稳定"],
    "port_speed": ["端口 {p} 速率变化: {v}", "端口速率正常"],
    "controller_state": ["控制器 {c} 状态异常: {s}", "控制器状态正常"],
    "card_info": ["接口卡 {c} 状态变化: {s}", "接口卡状态正常"],
    "alarm_type": ["告警类型: {t}, 代码: {c}", "告警已清除"],
    "tcp_connections": ["TIME_WAIT 连接数 {v} 超过阈值", "TCP 连接正常"],
    "thermal": ["温度过高: {v}°C", "温度恢复正常"],
}


async def seed_data():
    """Seed the database with test data."""
    print("Initializing database...")
    init_db()
    await create_tables()

    # Re-import after init_db creates the session factory
    from backend.db.database import AsyncSessionLocal as SessionLocal

    async with SessionLocal() as db:
        # Create tags
        print("\nCreating tags...")
        tag_ids = []
        for tag_data in TAGS:
            tag = TagModel(
                name=tag_data["name"],
                color=tag_data["color"],
                description=tag_data["description"],
            )
            db.add(tag)
            await db.flush()
            tag_ids.append(tag.id)
            print(f"  + {tag.name} (id={tag.id})")

        # Create arrays
        print("\nCreating arrays...")
        array_ids = []
        for arr_data in ARRAYS:
            tag_id = tag_ids[arr_data["tag_idx"]] if arr_data["tag_idx"] is not None else None
            array = ArrayModel(
                array_id=f"arr-{arr_data['host'].replace('.', '-')}",
                name=arr_data["name"],
                host=arr_data["host"],
                port=22,
                username="root",
                tag_id=tag_id,
            )
            db.add(array)
            await db.flush()
            array_ids.append(array.array_id)
            print(f"  + {array.name} ({array.host}) -> tag_id={tag_id}")

        # Create alerts
        print("\nCreating sample alerts...")
        now = datetime.now()
        alert_count = 0
        for i in range(50):
            array_id = random.choice(array_ids)
            observer = random.choice(OBSERVERS)
            level = random.choice(ALERT_LEVELS)
            messages = ALERT_MESSAGES.get(observer, ["告警消息 {v}"])
            message = random.choice(messages).format(
                v=random.randint(50, 99),
                p=f"process-{random.randint(1, 10)}",
                d=f"/dev/sd{random.choice('abcde')}",
                i=f"eth{random.randint(0, 3)}",
                s=random.choice(["up", "down", "degraded"]),
                c=random.randint(1000, 9999),
                t=random.choice(["ETH_PORT", "DISK_ERROR", "MEM_ALERT"]),
            )
            
            alert = AlertModel(
                array_id=array_id,
                observer_name=observer,
                level=level,
                message=message,
                details=json.dumps({"value": random.randint(1, 100), "threshold": 80}),
                timestamp=now - timedelta(minutes=random.randint(0, 1440)),
            )
            db.add(alert)
            alert_count += 1

        print(f"  + Created {alert_count} alerts")

        # Create task sessions
        print("\nCreating sample task sessions...")
        task_types = ["port_toggle", "controller_poweroff", "fault_injection", "stress_test"]
        for i in range(5):
            selected_arrays = random.sample(array_ids, k=random.randint(1, 3))
            task_type = random.choice(task_types)
            started = now - timedelta(hours=random.randint(1, 48))
            ended = started + timedelta(minutes=random.randint(30, 180)) if random.random() > 0.3 else None
            
            task = TaskSessionModel(
                name=f"测试任务-{i+1}",
                task_type=task_type,
                array_ids=json.dumps(selected_arrays),
                notes=f"自动生成的测试任务 #{i+1}",
                status="completed" if ended else "running",
                started_at=started,
                ended_at=ended,
            )
            db.add(task)
            print(f"  + {task.name} ({task_type}) - {task.status}")

        # Initialize built-in alert rules
        print("\nInitializing built-in alert rules...")
        await init_builtin_rules(db)

        await db.commit()
        print("\n✅ Test data seeded successfully!")
        print(f"   - {len(TAGS)} tags")
        print(f"   - {len(ARRAYS)} arrays")
        print(f"   - {alert_count} alerts")
        print(f"   - 5 task sessions")
        print(f"   - Built-in alert expectation rules")


if __name__ == "__main__":
    asyncio.run(seed_data())
