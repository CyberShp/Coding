#!/usr/bin/env python3
"""快速 demo 种子：让前端看起来有内容可展示。"""
import sqlite3, json, random
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).parent.parent / "observation_web.db"
NOW = datetime.now()

def ts(offset_hours=0):
    return (NOW - timedelta(hours=offset_hours)).strftime("%Y-%m-%d %H:%M:%S")

def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # --- 1. 更新阵列：混合 enrollment_status + 其他字段 ---
    arrays = c.execute("SELECT array_id, name FROM arrays").fetchall()
    statuses = ["enrolled", "enrolled", "enrolled", "enrolled", "online", "online"]
    for i, (aid, name) in enumerate(arrays):
        status = statuses[i % len(statuses)]
        c.execute("""
            UPDATE arrays SET
                enrollment_status = ?,
                display_name = ?,
                site = ?,
                env_type = ?,
                owner_team = ?,
                serial = ?,
                last_heartbeat_at = ?
            WHERE array_id = ?
        """, (
            status,
            name,
            ["北京机房", "北京机房", "上海机房", "上海机房", "广州机房", "广州机房"][i],
            ["production", "production", "production", "staging", "production", "staging"][i],
            ["存储一组", "存储一组", "存储二组", "存储二组", "存储一组", "存储二组"][i],
            f"SN2024{100+i:03d}",
            ts(random.uniform(0, 2)),
            aid,
        ))

    # --- 2. observer_snapshots — 每个阵列 × 10 个 observer ---
    OBSERVERS = [
        "link_status", "error_code", "port_fec", "port_speed",
        "card_recovery", "card_info", "memory_leak", "process_crash",
        "alarm_type", "cpu_usage",
    ]
    c.execute("DELETE FROM observer_snapshots")
    for aid, _ in arrays:
        for obs in OBSERVERS:
            success = random.random() > 0.15
            c.execute("""
                INSERT OR REPLACE INTO observer_snapshots
                    (array_id, observer_name, last_run_at, last_success_at,
                     last_failure_reason, avg_duration_ms, is_enabled, updated_at)
                VALUES (?,?,?,?,?,?,1,?)
            """, (
                aid, obs,
                ts(random.uniform(0, 1)),
                ts(random.uniform(1, 24)) if success else ts(48),
                None if success else "SSH timeout",
                random.randint(80, 800),
                ts(0),
            ))

    # --- 3. monitor_templates ---
    c.execute("SELECT COUNT(*) FROM monitor_templates")
    if c.fetchone()[0] == 0:
        templates = [
            ("检查 CPU 负载", "cat /proc/loadavg", "system",
             "CPU 负载超过阈值", "warning", 60),
            ("检查磁盘空间", "df -h / | tail -1", "system",
             "根分区使用率过高 {value}%", "error", 300),
            ("检查内存使用", "free -m | awk 'NR==2'", "system",
             "内存使用率超过 {value}%", "warning", 120),
            ("检查端口状态", "cat /proc/net/dev", "network",
             "端口 {port} 检测到 DOWN 状态", "error", 60),
            ("检查进程存活", "pgrep -c app_data", "process",
             "关键进程 app_data 已停止运行", "critical", 30),
            ("检查卡件健康", "show card all", "hardware",
             "卡件 {card} 健康状态异常", "error", 300),
        ]
        for name, cmd, cat, tmpl, level, interval in templates:
            c.execute("""
                INSERT INTO monitor_templates
                    (name, description, category, command, command_type,
                     match_type, match_expression, match_condition,
                     alert_level, alert_message_template,
                     interval, timeout, cooldown, is_enabled, is_builtin, created_by)
                VALUES (?,?,?,?,'shell','regex','([0-9.]+)','gt',?,?,?,30,?,1,0,'seed')
            """, (name, tmpl, cat, cmd, level, tmpl, interval, interval*2))

    # --- 4. scheduled_tasks ---
    c.execute("SELECT COUNT(*) FROM scheduled_tasks")
    if c.fetchone()[0] == 0:
        for aid, name in arrays[:3]:
            c.execute("""
                INSERT INTO scheduled_tasks
                    (name, description, command, cron_expr, array_ids, enabled,
                     created_at, last_run_at, next_run_at)
                VALUES (?,?,?,?,?,1,?,?,?)
            """, (
                f"定期检查 {name}",
                f"每小时检查 {name} 的关键指标",
                "df -h && free -m && uptime",
                "0 * * * *",
                json.dumps([aid]),
                ts(0),
                ts(random.uniform(1, 5)),
                ts(-1),
            ))

    # --- 5. issues ---
    c.execute("SELECT COUNT(*) FROM issues")
    if c.fetchone()[0] == 0:
        titles = [
            ("Beijing-Storage-01 存储控制器异常", "巡检发现控制器告警频发，需人工确认。"),
            ("Shanghai-Storage-01 端口 FEC 告警", "eth1 FEC 模式异常，端口误码率上升。"),
            ("Guangzhou-Storage-02 CPU 负载偏高", "CPU0 利用率持续 >90%，建议排查负载来源。"),
            ("Beijing-Storage-02 磁盘空间预警", "根分区使用率达 87%，建议扩容或清理。"),
        ]
        for title, content in titles:
            c.execute("""
                INSERT INTO issues (title, content, status, created_by_ip, created_at, updated_at)
                VALUES (?, ?, 'open', '192.168.1.1', ?, ?)
            """, (title, content, ts(random.uniform(2, 48)), ts(0)))

    conn.commit()
    conn.close()
    print("种子完成：")
    print(f"  ✓ 阵列状态更新 ({len(arrays)} 条)")
    print(f"  ✓ observer_snapshots ({len(arrays)*10} 条)")
    print("  ✓ monitor_templates")
    print("  ✓ scheduled_tasks")
    print("  ✓ issues")

if __name__ == "__main__":
    main()
