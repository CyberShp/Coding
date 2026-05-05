#!/usr/bin/env python3
"""
完整种子脚本：从零创建 tags、arrays、alerts、card_inventory 等测试数据。

用法:
    cd observation_web
    python3 scripts/seed_full.py
    python3 scripts/seed_full.py --alerts 50   # 自定义告警数量
"""

import argparse
import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Observer names and levels
OBSERVERS = [
    ("link_status", "error"),
    ("error_code", "warning"),
    ("port_fec", "warning"),
    ("port_speed", "warning"),
    ("card_recovery", "warning"),
    ("card_info", "error"),
    ("memory_leak", "warning"),
    ("process_crash", "error"),
    ("alarm_type", "warning"),
    ("cpu_usage", "info"),
]
MESSAGES = [
    "端口 eth0 link DOWN; speed: 100G → 0",
    "PCIe 误码: correctable +5",
    "FEC 模式变化: eth1 RS → OFF",
    "卡修复统计: 总计 3 次，本次新增 1 次",
    "卡件 card0 HealthState 异常: Fault",
    "内存疑似泄漏: 连续 5 次采集持续增长",
    "进程 app_data 崩溃: segfault",
    "[Alarm] 故障告警: AlarmId:0x1001 objType:ETH_PORT",
    "CPU0 利用率告警: 当前 92%",
]


async def seed(db: AsyncSession):
    """Insert all seed data."""
    # 1. Tags (L1 小组 + L2 类型)
    result = await db.execute(text("SELECT COUNT(*) FROM tags"))
    if result.scalar() == 0:
        await db.execute(text("""
            INSERT INTO tags (name, color, description, parent_id, level) VALUES
            ('存储一组', '#409eff', 'A 组存储阵列', NULL, 1),
            ('存储二组', '#67c23a', 'B 组存储阵列', NULL, 1),
            ('全闪存', '#e6a23c', '全闪存阵列', 1, 2),
            ('混闪阵列', '#f56c6c', '混闪阵列', 1, 2),
            ('归档阵列', '#909399', '归档阵列', 2, 2)
        """))
        await db.commit()
        print("  ✓ 已插入 5 个标签 (2 个 L1 小组 + 3 个 L2 类型)")
    else:
        print("  - 标签已存在，跳过")

    # 2. Arrays
    result = await db.execute(text("SELECT COUNT(*) FROM arrays"))
    if result.scalar() == 0:
        tag_ids = [r[0] for r in (await db.execute(text("SELECT id FROM tags WHERE level=2"))).fetchall()]
        for i, (name, host) in enumerate([
            ("阵列-A01", "192.168.1.101"),
            ("阵列-A02", "192.168.1.102"),
            ("阵列-B01", "192.168.1.201"),
        ]):
            tag_id = tag_ids[i % len(tag_ids)] if tag_ids else None
            aid = f"array_{uuid.uuid4().hex[:8]}"
            await db.execute(
                text("""
                    INSERT INTO arrays (array_id, name, host, port, username, tag_id)
                    VALUES (:aid, :name, :host, 22, 'root', :tag_id)
                """),
                {"aid": aid, "name": name, "host": host, "tag_id": tag_id},
            )
        await db.commit()
        print("  ✓ 已插入 3 个阵列")
    else:
        print("  - 阵列已存在，跳过")

    # 3. Alerts
    array_ids = [r[0] for r in (await db.execute(text("SELECT array_id FROM arrays"))).fetchall()]
    if not array_ids:
        print("  ⚠ 无阵列，跳过告警")
    else:
        result = await db.execute(text("SELECT COUNT(*) FROM alerts"))
        existing = result.scalar()
        count = max(0, 60 - existing)  # 目标约 60 条，补足差额
        if count > 0:
            now = datetime.now()
            for i in range(count):
                arr = random.choice(array_ids)
                obs, lvl = random.choice(OBSERVERS)
                msg = random.choice(MESSAGES)
                ts = (now - timedelta(hours=random.uniform(0, 72))).isoformat()
                await db.execute(
                    text("""
                        INSERT INTO alerts (array_id, observer_name, level, message, details, timestamp, is_expected)
                        VALUES (:arr, :obs, :lvl, :msg, :details, :ts, 0)
                    """),
                    {
                        "arr": arr,
                        "obs": obs,
                        "lvl": lvl,
                        "msg": msg,
                        "details": json.dumps({"seed": True, "idx": i}),
                        "ts": ts,
                    },
                )
            await db.commit()
            print(f"  ✓ 已插入 {count} 条告警（共约 {existing + count} 条）")
        else:
            print(f"  - 告警已足够 ({existing} 条)，跳过")

    # 4. Card inventory
    result = await db.execute(text("SELECT COUNT(*) FROM card_inventory"))
    if result.scalar() == 0:
        cards = [
            ("FC 8G 双口卡", "FC卡", "QLogic 2560", "8G 双口 FC HBA"),
            ("25G 以太网卡", "以太网卡", "Mellanox ConnectX-5", "25GbE 双口"),
            ("RAID 9361-8i", "RAID卡", "LSI 9361-8i", "8 口 SAS RAID"),
            ("NVMe 扩展卡", "扩展卡", "Broadcom 9500", "NVMe-oF 扩展"),
        ]
        for name, dtype, model, desc in cards:
            await db.execute(
                text("""
                    INSERT INTO card_inventory (name, device_type, model, description)
                    VALUES (:name, :dtype, :model, :desc)
                """),
                {"name": name, "dtype": dtype, "model": model, "desc": desc},
            )
        await db.commit()
        print("  ✓ 已插入 4 条卡件目录")
    else:
        print("  - 卡件目录已存在，跳过")

    # 5. Monitor templates (optional)
    result = await db.execute(text("SELECT COUNT(*) FROM monitor_templates"))
    if result.scalar() == 0:
        await db.execute(text("""
            INSERT INTO monitor_templates (name, description, category, command, command_type,
                match_type, match_expression, match_condition, alert_level, alert_message_template,
                interval, timeout, cooldown, is_enabled, is_builtin, created_by)
            VALUES
            ('检查 CPU 负载', 'cat /proc/loadavg', 'system', 'cat /proc/loadavg', 'shell',
                'regex', '([0-9.]+)', 'gt', 'warning', 'CPU 负载 {value}', 60, 30, 300, 1, 0, 'seed'),
            ('检查磁盘空间', 'df -h', 'system', 'df -h / | tail -1', 'shell',
                'regex', '([0-9]+)%', 'gt', 'error', '根分区 {value}%', 300, 30, 600, 1, 0, 'seed')
        """))
        await db.commit()
        print("  ✓ 已插入 2 条监控模板")
    else:
        print("  - 监控模板已存在，跳过")


def main():
    parser = argparse.ArgumentParser(description="完整种子数据")
    parser.add_argument("--alerts", type=int, default=60, help="目标告警数量（补足到该数）")
    args = parser.parse_args()

    async def _run():
        from backend.db.database import init_db, create_tables

        init_db()
        await create_tables()

        from backend.db import database
        async with database.AsyncSessionLocal() as session:
            await seed(session)

    print("═══ 种子数据 ═══")
    asyncio.run(_run())
    print("\n完成! 刷新前端查看效果。")


if __name__ == "__main__":
    main()
