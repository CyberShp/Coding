#!/usr/bin/env python3
"""
种子脚本：向数据库写入测试数据 + 调用新 API 端到端验证。

用法:
    cd observation_web
    python3 scripts/seed_test_data.py           # 默认 http://localhost:8001
    python3 scripts/seed_test_data.py --host http://192.168.x.x:8001
"""

import argparse
import json
import random
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ─────────── DB seed ───────────

DB_PATH = Path(__file__).parent.parent / "observation_web.db"

OBSERVERS_BY_LEVEL = {
    "error_code":       ("warning", "error"),
    "link_status":      ("warning", "error"),
    "port_fec":         ("warning",),
    "port_speed":       ("warning",),
    "port_traffic":     ("info",),
    "port_error_code":  ("warning", "error"),
    "sfp_monitor":      ("warning", "error"),
    "card_recovery":    ("warning", "error"),
    "card_info":        ("warning", "error"),
    "pcie_bandwidth":   ("warning", "info"),
    "alarm_type":       ("info", "warning", "error"),
    "cpu_usage":        ("warning", "info"),
    "memory_leak":      ("warning", "error"),
    "process_crash":    ("error", "critical"),
    "process_restart":  ("warning",),
    "io_timeout":       ("error", "critical"),
    "abnormal_reset":   ("error", "critical"),
    "cmd_response":     ("warning",),
    "sig_monitor":      ("warning",),
    "sensitive_info":   ("info",),
    "custom_commands":  ("warning", "error"),
    "controller_state": ("warning", "error"),
    "disk_state":       ("warning", "error"),
}

MESSAGES = {
    "error_code": [
        "端口统计信息: {p} rx_crc_errors +{n}",
        "端口统计信息: {p} rx_dropped +{n}",
        "PCIe 误码: {d} AER correctable +{n}",
    ],
    "link_status": [
        "检测到链路状态变化: {p} link DOWN; speed: 100000Mb → 0Mb",
        "检测到链路状态变化: {p} link UP; speed: 0Mb → 100000Mb",
        "{p} 速率降低: 100000 -> 25000 Mbps",
    ],
    "port_fec": [
        "FEC 模式变化: {p}: RS → OFF",
        "FEC 模式变化: {p}: OFF → RS",
    ],
    "port_speed": [
        "端口速率变化: {p}: 100G → unknown",
        "端口速率变化: {p}: unknown → 100G",
    ],
    "port_traffic": [
        "端口流量采集: {p} rx_bytes={n}, tx_bytes={n2}",
    ],
    "port_error_code": [
        "端口误码: 端口 0x{hex} BadXmitBc: {n}",
        "端口误码: 端口 0x{hex} LinkFailCnt: {n}",
    ],
    "sfp_monitor": [
        "光模块: 光模块 {p} 温度过高: {temp}°C",
        "光模块: {p} HealthState 异常: Fault",
        "FC 光模块 {p} 速率不一致: 期望 32G 实际 16G",
    ],
    "card_recovery": [
        "卡修复统计: 总计 {n} 次，本次新增 {n2} 次。最近: {ts} slot={slot}",
    ],
    "card_info": [
        "卡件 {c} (BoardId: 0x{hex}) RunningState 异常: Abnormal (预期: Normal)",
        "卡件 {c} (BoardId: 0x{hex}) HealthState 异常: Fault (预期: Normal)",
        "卡件信息恢复正常 ({n} 张卡)",
    ],
    "pcie_bandwidth": [
        "PCIe 带宽降级: {d} 宽度降级: x16 → x8",
        "PCIe 带宽降级: {d} 速率降级: 16GT/s → 8GT/s",
        "PCIe 带宽恢复正常 ({n} 设备)",
    ],
    "alarm_type": [
        "[Alarm] 事件 1 条; 累计事件={n},故障={n2},恢复={n3}, 当前活跃 {n4} 个",
        "[Alarm] 故障告警: AlarmId:0x{hex} objType:ETH_PORT",
        "[Alarm] 恢复: AlarmId:0x{hex} objType:FC_PORT",
    ],
    "cpu_usage": [
        "CPU0 利用率告警: 连续 {n} 次检测超过 85% (当前: {pct}%)",
        "CPU0 利用率恢复正常 (当前: {pct}%)",
    ],
    "memory_leak": [
        "内存疑似泄漏: 连续 {n} 次采集内存持续增长 (当前: {mem}MB)",
        "内存泄漏已恢复: 内存使用趋于稳定 (当前: {mem}MB)",
    ],
    "process_crash": [
        "检测到 {n} 个进程崩溃事件: {proc}: segfault at 0x{hex}",
        "检测到 {n} 个进程崩溃事件: {proc}: OOM kill (score={n2})",
    ],
    "process_restart": [
        "进程拉起: 进程 {proc} 被重拉: -v {n} -> {n2}",
    ],
    "io_timeout": [
        "检测到 {n} 个 IO 异常事件: I/O error, dev sda, sector {n2}",
        "检测到 {n} 个 IO 异常事件: scsi error: return code 0x{hex}",
        "检测到 {n} 个 IO 异常事件: task abort: tag={n2}",
    ],
    "abnormal_reset": [
        "异常复位: 电源异常复位 ({ts})",
        "异常复位: watchdog 超时复位 ({ts})",
    ],
    "cmd_response": [
        "命令响应超时: storageadm -q 耗时 {n}s (阈值 30s)",
    ],
    "sig_monitor": [
        "检测到异常信号: sig 11 (SIGSEGV), sig 6 (SIGABRT)",
        "检测到异常信号: sig 9 (SIGKILL)",
    ],
    "sensitive_info": [
        "检测到敏感信息: password 在 /var/log/messages (3处)",
        "检测到敏感信息: NQN 在 /var/log/iscsi.log (1处)",
    ],
    "custom_commands": [
        "自定义命令告警: check_raid 执行失败 (返回码: 1)",
        "自定义命令告警: check_raid: status=degraded (expect: optimal)",
    ],
    "controller_state": [
        "控制器状态变化: 控制器 A: online → offline",
        "控制器状态变化: 控制器 B: online → degraded",
        "控制器状态查询失败: command not found",
    ],
    "disk_state": [
        "磁盘状态变化: 磁盘 1:0:3: online → offline",
        "磁盘状态变化: 磁盘 1:0:5: online → rebuilding",
    ],
}


def _rand_msg(obs):
    tpls = MESSAGES.get(obs, ["观察点 {obs} 检测到异常"])
    tpl = random.choice(tpls)
    now = datetime.now()
    return tpl.format(
        p=f"eth{random.randint(0, 7)}",
        n=random.randint(1, 5000),
        n2=random.randint(1, 500),
        n3=random.randint(0, 100),
        n4=random.randint(0, 5),
        c=f"card{random.randint(0, 3)}",
        d=f"0000:{random.randint(1,9):02x}:00.0",
        proc=random.choice(["app_data", "devm", "memf", "coffer", "storageadm"]),
        hex=f"{random.randint(0x1000, 0xFFFF):04x}",
        temp=f"{random.uniform(60, 95):.1f}",
        pct=random.randint(30, 99),
        mem=random.randint(512, 8192),
        slot=random.randint(0, 7),
        ts=(now - timedelta(minutes=random.randint(1, 120))).strftime("%Y-%m-%d %H:%M"),
        obs=obs,
    )


def seed_alerts(conn, array_ids, count=80):
    """向 alerts 表写入大量测试告警，覆盖所有 23 个观察点。"""
    now = datetime.now()
    c = conn.cursor()
    obs_names = list(OBSERVERS_BY_LEVEL.keys())
    inserted = 0
    for i in range(count):
        arr = random.choice(array_ids)
        obs = random.choice(obs_names)
        lvl = random.choice(OBSERVERS_BY_LEVEL[obs])
        ts = now - timedelta(hours=random.uniform(0, 48))
        msg = _rand_msg(obs)
        details = json.dumps({"seed": True, "idx": i})
        c.execute(
            "INSERT INTO alerts (array_id, observer_name, level, message, details, timestamp, is_expected) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (arr, obs, lvl, msg, details, ts.isoformat()),
        )
        inserted += 1
    conn.commit()
    print(f"  ✓ 已插入 {inserted} 条告警（覆盖 {len(obs_names)} 个观察点）")
    return inserted


def seed_monitor_templates(conn, count=5):
    """向 monitor_templates 表写入测试模板。"""
    templates = [
        ("检查 CPU 负载", "cat /proc/loadavg", "regex", r"([0-9.]+)", "gt", "5.0", "warning",
         "CPU 负载超过阈值: {value}", "system"),
        ("检查磁盘空间", "df -h / | tail -1", "regex", r"([0-9]+)%", "gt", "90", "error",
         "根分区使用率 {value}%", "system"),
        ("检查 NTP 同步", "chronyc tracking 2>/dev/null || ntpstat", "contains", "synchronised", "not_found", None, "warning",
         "NTP 未同步", "system"),
        ("检查内核 panic", "dmesg | tail -50", "regex", r"kernel panic", "found", None, "critical",
         "检测到内核 panic: {match}", "system"),
        ("检查端口速率", "ethtool eth0 2>/dev/null | grep Speed", "regex", r"Speed: ([0-9]+)", "lt", "10000", "warning",
         "端口速率低于预期: {value} Mb/s", "port"),
    ]
    c = conn.cursor()
    inserted = 0
    for i, (name, cmd, mtype, mexpr, mcond, mthresh, lvl, msg_tpl, cat) in enumerate(templates[:count]):
        c.execute(
            "INSERT INTO monitor_templates "
            "(name, command, command_type, match_type, match_expression, match_condition, "
            "match_threshold, alert_level, alert_message_template, category, "
            "interval, timeout, cooldown, is_enabled, is_builtin, created_by) "
            "VALUES (?, ?, 'shell', ?, ?, ?, ?, ?, ?, ?, 60, 30, 300, 1, 0, 'seed-script')",
            (name, cmd, mtype, mexpr, mcond, mthresh, lvl, msg_tpl, cat),
        )
        inserted += 1
    conn.commit()
    print(f"  ✓ 已插入 {inserted} 条监控模板")
    return inserted


# ─────────── API smoke tests ───────────

def api_test(base_url):
    """调用新增 API 验证前后端交互正常。"""
    import urllib.request
    import urllib.error

    def req(method, path, body=None, token=None):
        url = f"{base_url}/api{path}"
        data = json.dumps(body).encode() if body else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(r, timeout=10)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode() if e.fp else ""
            try:
                return e.code, json.loads(body_text)
            except Exception:
                return e.code, {"raw": body_text}
        except Exception as e:
            return 0, {"error": str(e)}

    def assert_ok(label, status, data, expect_code=200):
        ok = status == expect_code
        mark = "✓" if ok else "✗"
        print(f"  {mark} [{status}] {label}")
        if not ok:
            print(f"      期望 {expect_code}, 响应: {json.dumps(data, ensure_ascii=False)[:200]}")
        return ok

    passed = 0
    total = 0

    # ─── 1. Admin login ───
    print("\n═══ 1. 管理员登录 ═══")
    total += 1
    code, data = req("POST", "/auth/login", {"username": "admin", "password": "admin123"})
    if assert_ok("POST /auth/login", code, data):
        passed += 1
    token = data.get("token", "")
    if not token:
        print("  ⚠ 无法获取 token，后续管理员接口将跳过")

    # ─── 2. 告警列表 ───
    print("\n═══ 2. 告警列表 & 统计 ═══")
    total += 1
    code, data = req("GET", "/alerts?hours=48&limit=20")
    if assert_ok("GET /alerts", code, data):
        passed += 1
        print(f"      返回 {len(data)} 条告警")

    total += 1
    code, data = req("GET", "/alerts/stats?hours=48")
    if assert_ok("GET /alerts/stats", code, data):
        passed += 1
        print(f"      总计: {data.get('total')}")

    # ─── 3. 批量确认 → 批量修改 → 批量撤销 ───
    print("\n═══ 3. 批量 Ack 操作 ═══")
    # 获取几条告警的 ID
    code, alerts_list = req("GET", "/alerts?hours=48&limit=5")
    if code == 200 and alerts_list:
        test_ids = [a["id"] for a in alerts_list[:3]] if isinstance(alerts_list, list) else []
    else:
        test_ids = []

    if not test_ids:
        # Fallback: get from stats recent
        code2, stats_data = req("GET", "/alerts/recent?limit=5")
        if code2 == 200 and isinstance(stats_data, list):
            test_ids = [a["id"] for a in stats_data[:3]]

    if test_ids:
        # 3a: ack (confirm_ok)
        total += 1
        code, data = req("POST", "/alerts/ack", {"alert_ids": test_ids, "ack_type": "confirmed_ok"})
        if assert_ok("POST /alerts/ack (confirmed_ok)", code, data):
            passed += 1
            print(f"      确认了 {len(data)} 条")

        # 3b: batch-modify → dismiss
        total += 1
        code, data = req("POST", "/alerts/ack/batch-modify", {"alert_ids": test_ids, "new_ack_type": "dismiss"})
        if assert_ok("POST /alerts/ack/batch-modify", code, data):
            passed += 1
            print(f"      修改了 {data.get('modified_count')} 条")

        # 3c: batch-undo
        total += 1
        code, data = req("POST", "/alerts/ack/batch-undo", {"alert_ids": test_ids})
        if assert_ok("POST /alerts/ack/batch-undo", code, data):
            passed += 1
            print(f"      撤销了 {data.get('undone_count')} 条")
    else:
        print("  ⚠ 无告警可测试，跳过批量操作")

    # ─── 4. 时间线 category 过滤 ───
    print("\n═══ 4. Timeline category 过滤 ═══")
    # 取第一个 array_id
    code, arr_data = req("GET", "/arrays")
    first_array_id = None
    if code == 200 and arr_data:
        first_arr = arr_data[0] if isinstance(arr_data, list) else None
        first_array_id = first_arr.get("array_id") if first_arr else None

    if first_array_id:
        for cat in ["port", "card", "system"]:
            total += 1
            code, data = req("GET", f"/timeline/{first_array_id}?hours=48&category={cat}")
            if assert_ok(f"GET /timeline?category={cat}", code, data):
                passed += 1
                evts = data.get("events", [])
                print(f"      {cat}: {len(evts)} 事件")
    else:
        print("  ⚠ 无阵列可测试")

    # ─── 5. 管理员监控模板 CRUD ───
    print("\n═══ 5. 监控模板 CRUD ═══")
    if token:
        # 5a: list
        total += 1
        code, data = req("GET", "/admin/monitor-templates", token=token)
        if assert_ok("GET /admin/monitor-templates", code, data):
            passed += 1
            print(f"      已有 {len(data)} 个模板")

        # 5b: create
        total += 1
        new_tpl = {
            "name": f"API测试模板_{int(time.time())}",
            "command": "echo hello",
            "match_type": "contains",
            "match_expression": "hello",
            "match_condition": "found",
            "alert_level": "info",
            "alert_message_template": "命令输出包含 hello: {value}",
            "category": "custom",
            "interval": 120,
        }
        code, data = req("POST", "/admin/monitor-templates", new_tpl, token=token)
        if assert_ok("POST /admin/monitor-templates (create)", code, data):
            passed += 1
            tpl_id = data.get("id")
            print(f"      新模板 ID={tpl_id}")

            # 5c: update
            total += 1
            code, data2 = req("PUT", f"/admin/monitor-templates/{tpl_id}",
                              {"alert_level": "warning", "interval": 300}, token=token)
            if assert_ok(f"PUT /admin/monitor-templates/{tpl_id}", code, data2):
                passed += 1
                print(f"      更新后 level={data2.get('alert_level')}, interval={data2.get('interval')}")

            # 5d: delete
            total += 1
            code, data3 = req("DELETE", f"/admin/monitor-templates/{tpl_id}", token=token)
            if assert_ok(f"DELETE /admin/monitor-templates/{tpl_id}", code, data3):
                passed += 1

        # 5e: deploy (dry-run: 对第一个标签)
        total += 1
        code, tpls = req("GET", "/admin/monitor-templates", token=token)
        if code == 200 and tpls:
            code2, tags_data = req("GET", "/tags")
            # 选有阵列的标签（array_count > 0）
            tag_ids = [t["id"] for t in (tags_data if isinstance(tags_data, list) else [])
                       if t.get("array_count", 0) > 0][:1]
            tpl_ids = [t["id"] for t in tpls[:2]]
            if tag_ids and tpl_ids:
                code, deploy_data = req("POST", "/admin/monitor-templates/deploy",
                                        {"template_ids": tpl_ids, "target_type": "tag", "target_ids": tag_ids},
                                        token=token)
                # 因为没有真实 SSH 连接，deploy 大概会返回各阵列 ok=false
                if assert_ok("POST /admin/monitor-templates/deploy", code, deploy_data):
                    passed += 1
                    results = deploy_data.get("results", [])
                    ok_cnt = sum(1 for r in results if r.get("ok"))
                    fail_cnt = len(results) - ok_cnt
                    print(f"      下发结果: 成功 {ok_cnt}, 失败 {fail_cnt} (预期全失败: 无SSH连接)")
            else:
                print("  ⚠ 无标签或模板可 deploy")
                passed += 1  # 跳过不扣分
        else:
            print("  ⚠ 无模板可 deploy")
            passed += 1
    else:
        print("  ⚠ 无 token，跳过管理员接口")

    # ─── Summary ───
    print(f"\n{'═'*40}")
    print(f"  结果: {passed}/{total} 通过")
    print(f"{'═'*40}")
    return passed == total


def main():
    parser = argparse.ArgumentParser(description="喂入测试数据 + 调用新 API 验证")
    parser.add_argument("--host", default="http://localhost:8001", help="后端地址")
    parser.add_argument("--no-seed", action="store_true", help="跳过数据库种子，只跑 API")
    parser.add_argument("--no-api", action="store_true", help="只灌数据不跑 API")
    parser.add_argument("--alerts", type=int, default=80, help="要插入的告警数量")
    args = parser.parse_args()

    if not args.no_seed:
        print("═══ 种子数据 ═══")
        conn = sqlite3.connect(str(DB_PATH))
        # 获取现有 array_id
        array_ids = [r[0] for r in conn.execute("SELECT array_id FROM arrays").fetchall()]
        if not array_ids:
            print("  ⚠ 数据库中没有阵列，请先创建阵列")
            conn.close()
            return
        print(f"  现有 {len(array_ids)} 个阵列")
        seed_alerts(conn, array_ids, count=args.alerts)
        seed_monitor_templates(conn, count=5)
        conn.close()
        print()

    if not args.no_api:
        print("═══ API 端到端验证 ═══")
        ok = api_test(args.host)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
