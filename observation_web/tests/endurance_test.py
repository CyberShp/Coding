"""
Endurance Test Suite — 4-hour continuous testing

Simulates human-like interaction patterns at ~0.5s intervals:
1. Frontend button switching (time ranges, ports, pages, filters)
2. Backend API cross-call stress testing
3. Edge cases, invalid inputs, rapid toggling

Reports bugs found, categorized as:
- SMALL_BUG: auto-fixable issues
- FRAMEWORK_BUG: requires architecture changes, marked only
"""

import asyncio
import aiohttp
import time
import json
import random
import traceback
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from collections import defaultdict
from pathlib import Path

# ───── Configuration ─────
BASE_URL = "http://localhost:8001"
TEST_DURATION_HOURS = 4
HUMAN_DELAY_MIN = 0.3  # seconds
HUMAN_DELAY_MAX = 0.7  # seconds
REPORT_INTERVAL = 300  # print progress every 5 min
MAX_CONCURRENT = 3  # max parallel requests (simulate browser tabs)

ARRAY_IDS = ["array-001", "array-002", "array-003"]
PORTS = ["eth0", "eth1", "eth2", "eth3", "bond0", "bond1"]
TIME_RANGES = [5, 10, 30, 60, 120]
ALERT_LEVELS = ["info", "warning", "error", "critical"]
OBSERVERS = [
    "error_code", "link_status", "port_fec", "port_speed",
    "card_recovery", "card_info", "pcie_bandwidth",
    "alarm_type", "memory_leak", "cpu_usage", "cmd_response",
    "controller_state", "disk_state", "process_crash", "io_timeout",
]


@dataclass
class TestResult:
    test_name: str
    scenario: str
    success: bool
    status_code: int = 0
    response_time_ms: float = 0
    error: str = ""
    timestamp: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Bug:
    id: str
    severity: str  # SMALL_BUG or FRAMEWORK_BUG
    category: str
    description: str
    endpoint: str
    repro_steps: str
    occurrences: int = 1
    first_seen: str = ""
    last_seen: str = ""
    fixed: bool = False
    fix_description: str = ""


class EnduranceTestRunner:
    def __init__(self):
        self.results: List[TestResult] = []
        self.bugs: Dict[str, Bug] = {}
        self.stats = defaultdict(lambda: {"total": 0, "pass": 0, "fail": 0,
                                           "avg_ms": 0.0, "max_ms": 0.0, "total_ms": 0.0})
        self.start_time = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.test_task_ids: List[int] = []
        self.snapshot_ids: List[int] = []

    async def request(self, method: str, path: str, scenario: str,
                      test_name: str, **kwargs) -> TestResult:
        """Make HTTP request and record result."""
        url = f"{BASE_URL}{path}"
        t0 = time.monotonic()
        result = TestResult(
            test_name=test_name,
            scenario=scenario,
            success=False,
            timestamp=datetime.now().isoformat(),
        )

        try:
            async with self.session.request(method, url, timeout=aiohttp.ClientTimeout(total=15), **kwargs) as resp:
                result.status_code = resp.status
                body = await resp.text()
                result.response_time_ms = (time.monotonic() - t0) * 1000

                if resp.status < 400:
                    result.success = True
                    try:
                        result.details = {"body_len": len(body)}
                        data = json.loads(body)
                        if isinstance(data, list):
                            result.details["count"] = len(data)
                        elif isinstance(data, dict):
                            result.details["keys"] = list(data.keys())[:8]
                    except json.JSONDecodeError:
                        pass
                else:
                    result.error = body[:300]
                    # Record bug if unexpected error
                    if resp.status == 500:
                        self._record_bug(
                            f"500_{path}",
                            "SMALL_BUG" if "OperationalError" in body else "FRAMEWORK_BUG",
                            "API_500",
                            f"500 Internal Server Error on {method} {path}",
                            path,
                            f"curl -s -X {method} '{url}'",
                            details=body[:500],
                        )
                    elif resp.status == 404 and "Not Found" in body:
                        # Could be valid (resource doesn't exist) or a routing bug
                        pass

        except asyncio.TimeoutError:
            result.response_time_ms = (time.monotonic() - t0) * 1000
            result.error = "TIMEOUT (>15s)"
            self._record_bug(
                f"timeout_{path}",
                "FRAMEWORK_BUG",
                "TIMEOUT",
                f"Request timeout on {method} {path}",
                path,
                f"curl -s -X {method} '{url}' --max-time 15",
            )
        except aiohttp.ClientError as e:
            result.response_time_ms = (time.monotonic() - t0) * 1000
            result.error = f"ConnectionError: {str(e)[:200]}"
            self._record_bug(
                f"conn_{path}",
                "FRAMEWORK_BUG",
                "CONNECTION",
                f"Connection error on {method} {path}: {str(e)[:100]}",
                path,
                f"curl -s -X {method} '{url}'",
            )
        except Exception as e:
            result.response_time_ms = (time.monotonic() - t0) * 1000
            result.error = f"Exception: {str(e)[:200]}"

        self._record_result(result)
        return result

    def _record_result(self, result: TestResult):
        self.results.append(result)
        s = self.stats[result.scenario]
        s["total"] += 1
        if result.success:
            s["pass"] += 1
        else:
            s["fail"] += 1
        s["total_ms"] += result.response_time_ms
        s["avg_ms"] = s["total_ms"] / s["total"]
        if result.response_time_ms > s["max_ms"]:
            s["max_ms"] = result.response_time_ms

    def _record_bug(self, bug_id: str, severity: str, category: str,
                    description: str, endpoint: str, repro_steps: str,
                    details: str = ""):
        now = datetime.now().isoformat()
        if bug_id in self.bugs:
            self.bugs[bug_id].occurrences += 1
            self.bugs[bug_id].last_seen = now
        else:
            self.bugs[bug_id] = Bug(
                id=bug_id,
                severity=severity,
                category=category,
                description=description,
                endpoint=endpoint,
                repro_steps=repro_steps,
                first_seen=now,
                last_seen=now,
            )

    async def human_delay(self):
        """Simulate human interaction delay."""
        await asyncio.sleep(random.uniform(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX))

    # ═══════════════════════════════════════════════════════════
    # Scenario 1: Dashboard Page Simulation
    # ═══════════════════════════════════════════════════════════
    async def scenario_dashboard(self):
        """Simulate: user opens dashboard, views stats, clicks cards."""
        sc = "dashboard"
        # 1. Load alert stats (dashboard cards)
        await self.request("GET", "/api/alerts/stats?hours=24", sc, "load_alert_stats")
        await self.human_delay()

        # 2. Load array statuses (dashboard overview)
        await self.request("GET", "/api/arrays/statuses", sc, "load_array_statuses")
        await self.human_delay()

        # 3. Load recent alerts
        await self.request("GET", "/api/alerts/recent?limit=10", sc, "load_recent_alerts")
        await self.human_delay()

        # 4. Load test tasks (active banner)
        await self.request("GET", "/api/test-tasks", sc, "load_test_tasks")
        await self.human_delay()

        # 5. Rapid refresh (user hits F5 or clicks refresh)
        for _ in range(3):
            await self.request("GET", "/api/alerts/stats?hours=24", sc, "rapid_refresh_stats")
            await asyncio.sleep(0.1)

    # ═══════════════════════════════════════════════════════════
    # Scenario 2: Array List + Detail Page Simulation
    # ═══════════════════════════════════════════════════════════
    async def scenario_array_detail(self):
        """Simulate: user browses array list, clicks into detail, switches tabs."""
        sc = "array_detail"
        # 1. Load array list
        await self.request("GET", "/api/arrays", sc, "load_array_list")
        await self.human_delay()

        # 2. Pick random array, load status
        arr_id = random.choice(ARRAY_IDS)
        await self.request("GET", f"/api/arrays/statuses", sc, "load_statuses")
        await self.human_delay()

        # 3. Load timeline
        hours = random.choice([6, 12, 24, 48])
        await self.request("GET", f"/api/timeline/{arr_id}?hours={hours}", sc,
                           f"timeline_h{hours}")
        await self.human_delay()

        # 4. Load snapshots list
        await self.request("GET", f"/api/snapshots/{arr_id}", sc, "load_snapshots")
        await self.human_delay()

    # ═══════════════════════════════════════════════════════════
    # Scenario 3: Traffic Chart — Rapid Time Range Switching
    # ═══════════════════════════════════════════════════════════
    async def scenario_traffic_switching(self):
        """Simulate: user rapidly switches time ranges and ports on traffic chart.
        This is the exact pattern that triggered the original bug."""
        sc = "traffic_switching"
        arr_id = random.choice(ARRAY_IDS)

        # 1. Load available ports
        r = await self.request("GET", f"/api/traffic/{arr_id}/ports", sc, "load_ports")
        await self.human_delay()

        ports = []
        if r.success and r.details.get("keys"):
            try:
                body = await self._get_json(f"/api/traffic/{arr_id}/ports")
                ports = body.get("ports", [])
            except Exception:
                ports = ["eth0", "bond0"]

        if not ports:
            ports = ["eth0", "bond0"]

        port = random.choice(ports)

        # 2. Rapid time range switching (the core bug scenario)
        sequence = [30, 10, 30, 5, 60, 10, 120, 30, 5, 10, 30, 60, 10, 5]
        for mins in sequence:
            r = await self.request(
                "GET",
                f"/api/traffic/{arr_id}/data?port={port}&minutes={mins}",
                sc,
                f"traffic_{mins}min",
            )
            # Validate response structure
            if r.success:
                try:
                    body_text = r.details.get("keys", [])
                    if "data" not in body_text and "count" not in body_text:
                        self._record_bug(
                            f"traffic_bad_response_{mins}",
                            "SMALL_BUG",
                            "RESPONSE_FORMAT",
                            f"Traffic data response missing 'data' or 'count' key for {mins}min",
                            f"/api/traffic/{arr_id}/data",
                            f"curl -s '{BASE_URL}/api/traffic/{arr_id}/data?port={port}&minutes={mins}'",
                        )
                except Exception:
                    pass
            await asyncio.sleep(random.uniform(0.15, 0.5))  # fast switching

        # 3. Switch port mid-stream
        other_port = random.choice(ports)
        for mins in [30, 10, 5]:
            await self.request(
                "GET",
                f"/api/traffic/{arr_id}/data?port={other_port}&minutes={mins}",
                sc,
                f"traffic_port_switch_{mins}",
            )
            await asyncio.sleep(0.2)

    # ═══════════════════════════════════════════════════════════
    # Scenario 4: Alert Center — Filter / Aggregation Switching
    # ═══════════════════════════════════════════════════════════
    async def scenario_alert_center(self):
        """Simulate: user toggles filters, switches flat/aggregated, paginates."""
        sc = "alert_center"

        # 1. Load flat alerts (default)
        await self.request("GET", "/api/alerts?limit=20&offset=0", sc, "flat_default")
        await self.human_delay()

        # 2. Filter by level
        level = random.choice(ALERT_LEVELS)
        await self.request("GET", f"/api/alerts?level={level}&limit=20", sc,
                           f"filter_level_{level}")
        await self.human_delay()

        # 3. Filter by observer
        obs = random.choice(OBSERVERS)
        await self.request("GET", f"/api/alerts?observer={obs}&limit=20", sc,
                           f"filter_observer_{obs}")
        await self.human_delay()

        # 4. Filter by array
        arr = random.choice(ARRAY_IDS)
        await self.request("GET", f"/api/alerts?array_id={arr}&limit=20", sc,
                           f"filter_array_{arr}")
        await self.human_delay()

        # 5. Switch to aggregated mode
        await self.request("GET", "/api/alerts/aggregated?hours=24&limit=100", sc,
                           "aggregated_mode")
        await self.human_delay()

        # 6. Aggregated with array filter
        await self.request("GET", f"/api/alerts/aggregated?array_id={arr}&hours=24", sc,
                           "aggregated_filtered")
        await self.human_delay()

        # 7. Toggle back to flat
        await self.request("GET", "/api/alerts?limit=20&offset=0", sc, "back_to_flat")
        await self.human_delay()

        # 8. Rapid pagination
        for page in range(5):
            await self.request("GET", f"/api/alerts?limit=10&offset={page*10}", sc,
                               f"paginate_p{page}")
            await asyncio.sleep(0.15)

        # 9. Load stats for sidebar
        await self.request("GET", "/api/alerts/stats", sc, "alert_stats")

    # ═══════════════════════════════════════════════════════════
    # Scenario 5: Test Task Lifecycle
    # ═══════════════════════════════════════════════════════════
    async def scenario_test_tasks(self):
        """Simulate: create task, start, stop, view summary, delete."""
        sc = "test_tasks"

        # 1. List tasks
        await self.request("GET", "/api/test-tasks", sc, "list_tasks")
        await self.human_delay()

        # 2. Create a task
        task_data = {
            "name": f"自动化测试_{int(time.time())}",
            "task_type": random.choice(["normal_business", "controller_poweroff",
                                         "card_hotswap", "long_running"]),
            "array_ids": random.sample(ARRAY_IDS, k=random.randint(1, 2)),
            "notes": "Endurance test auto-created task",
        }
        r = await self.request("POST", "/api/test-tasks", sc, "create_task",
                               json=task_data)
        task_id = None
        if r.success:
            try:
                body = json.loads(r.error) if not r.success else None
                # Need to get the task ID from a separate call
                r2 = await self._get_json("/api/test-tasks")
                if isinstance(r2, list) and r2:
                    task_id = r2[-1].get("id")
                    self.test_task_ids.append(task_id)
            except Exception:
                pass
        await self.human_delay()

        # 3. Start the task
        if task_id:
            await self.request("POST", f"/api/test-tasks/{task_id}/start", sc, "start_task")
            await self.human_delay()

            # 4. View summary while running
            await self.request("GET", f"/api/test-tasks/{task_id}/summary", sc, "view_summary")
            await self.human_delay()

            # 5. Stop the task
            await self.request("POST", f"/api/test-tasks/{task_id}/stop", sc, "stop_task")
            await self.human_delay()

            # 6. View final summary
            await self.request("GET", f"/api/test-tasks/{task_id}/summary", sc, "final_summary")
            await self.human_delay()

            # 7. Delete task
            await self.request("DELETE", f"/api/test-tasks/{task_id}", sc, "delete_task")

    # ═══════════════════════════════════════════════════════════
    # Scenario 6: Cross-API Stress — Rapid Multi-Endpoint Calls
    # ═══════════════════════════════════════════════════════════
    async def scenario_cross_api_stress(self):
        """Simulate: rapid switching between different API endpoints,
        like a user quickly navigating between pages."""
        sc = "cross_api_stress"
        arr_id = random.choice(ARRAY_IDS)

        endpoints = [
            ("GET", "/api/arrays"),
            ("GET", "/api/arrays/statuses"),
            ("GET", "/api/alerts?limit=10"),
            ("GET", "/api/alerts/stats"),
            ("GET", "/api/alerts/recent?limit=5"),
            ("GET", f"/api/timeline/{arr_id}?hours=24"),
            ("GET", f"/api/traffic/{arr_id}/ports"),
            ("GET", f"/api/traffic/{arr_id}/data?port=eth0&minutes=30"),
            ("GET", "/api/test-tasks"),
            ("GET", "/api/system-alerts"),
            ("GET", "/api/system-alerts/stats"),
            ("GET", "/api/alerts/aggregated?hours=24&limit=50"),
            ("GET", f"/api/snapshots/{arr_id}"),
            ("GET", "/api/alerts/summary"),
        ]

        # Rapid-fire 20 random requests
        for _ in range(20):
            method, path = random.choice(endpoints)
            await self.request(method, path, sc, f"cross_{path.split('?')[0].replace('/', '_')}")
            await asyncio.sleep(random.uniform(0.1, 0.4))

    # ═══════════════════════════════════════════════════════════
    # Scenario 7: Edge Cases & Invalid Inputs
    # ═══════════════════════════════════════════════════════════
    async def scenario_edge_cases(self):
        """Test invalid inputs, missing params, nonexistent resources."""
        sc = "edge_cases"

        # Invalid array ID
        await self.request("GET", "/api/traffic/nonexistent-array/ports", sc, "invalid_array_traffic")
        await self.human_delay()

        # Invalid port name
        await self.request("GET", "/api/traffic/array-001/data?port=INVALID&minutes=30", sc,
                           "invalid_port")
        await self.human_delay()

        # Out-of-range minutes
        await self.request("GET", "/api/traffic/array-001/data?port=eth0&minutes=9999", sc,
                           "out_of_range_minutes")
        await self.human_delay()

        # Negative minutes
        await self.request("GET", "/api/traffic/array-001/data?port=eth0&minutes=-5", sc,
                           "negative_minutes")
        await self.human_delay()

        # Missing required params
        await self.request("GET", "/api/traffic/array-001/data", sc, "missing_port_param")
        await self.human_delay()

        # Nonexistent task ID
        await self.request("GET", "/api/test-tasks/99999", sc, "nonexistent_task")
        await self.human_delay()

        # Delete nonexistent task
        await self.request("DELETE", "/api/test-tasks/99999", sc, "delete_nonexistent")
        await self.human_delay()

        # Invalid alert filters
        await self.request("GET", "/api/alerts?level=INVALID_LEVEL", sc, "invalid_level_filter")
        await self.human_delay()

        # Large offset pagination
        await self.request("GET", "/api/alerts?limit=10&offset=999999", sc, "huge_offset")
        await self.human_delay()

        # Timeline for nonexistent array
        await self.request("GET", "/api/timeline/nonexistent?hours=24", sc, "timeline_bad_array")
        await self.human_delay()

        # Snapshot diff with invalid IDs
        await self.request("GET", "/api/snapshots/diff?id1=99999&id2=99998", sc, "diff_bad_ids")
        await self.human_delay()

        # Zero limit
        await self.request("GET", "/api/alerts?limit=0", sc, "zero_limit")

    # ═══════════════════════════════════════════════════════════
    # Scenario 8: Concurrent Requests (browser tabs / components)
    # ═══════════════════════════════════════════════════════════
    async def scenario_concurrent(self):
        """Simulate: multiple components loading data simultaneously,
        like when ArrayDetail mounts with traffic, timeline, snapshots."""
        sc = "concurrent"
        arr_id = random.choice(ARRAY_IDS)

        # Simulate ArrayDetail mount — 5 parallel requests
        tasks = [
            self.request("GET", f"/api/arrays/statuses", sc, "concurrent_statuses"),
            self.request("GET", f"/api/timeline/{arr_id}?hours=24", sc, "concurrent_timeline"),
            self.request("GET", f"/api/traffic/{arr_id}/ports", sc, "concurrent_ports"),
            self.request("GET", f"/api/snapshots/{arr_id}", sc, "concurrent_snapshots"),
            self.request("GET", f"/api/alerts?array_id={arr_id}&limit=20", sc, "concurrent_alerts"),
        ]
        await asyncio.gather(*tasks)
        await self.human_delay()

        # Simulate dashboard mount — 4 parallel requests
        tasks = [
            self.request("GET", "/api/alerts/stats", sc, "concurrent_stats"),
            self.request("GET", "/api/arrays/statuses", sc, "concurrent_statuses2"),
            self.request("GET", "/api/alerts/recent?limit=10", sc, "concurrent_recent"),
            self.request("GET", "/api/test-tasks", sc, "concurrent_tasks"),
        ]
        await asyncio.gather(*tasks)

    # ═══════════════════════════════════════════════════════════
    # Scenario 9: System Alerts Check
    # ═══════════════════════════════════════════════════════════
    async def scenario_system_alerts(self):
        """Check system alerts page and debug info."""
        sc = "system_alerts"
        await self.request("GET", "/api/system-alerts", sc, "list_system_alerts")
        await self.human_delay()
        await self.request("GET", "/api/system-alerts/stats", sc, "system_alert_stats")
        await self.human_delay()
        await self.request("GET", "/api/system-alerts/debug", sc, "debug_info")

    # ═══════════════════════════════════════════════════════════
    # Scenario 10: Snapshot Create + Diff
    # ═══════════════════════════════════════════════════════════
    async def scenario_snapshots(self):
        """Create snapshots and diff them."""
        sc = "snapshots"
        arr_id = random.choice(ARRAY_IDS)

        # Create snapshot 1
        r1 = await self.request("POST", f"/api/snapshots/{arr_id}", sc, "create_snap1")
        await self.human_delay()

        # Create snapshot 2
        r2 = await self.request("POST", f"/api/snapshots/{arr_id}", sc, "create_snap2")
        await self.human_delay()

        # List snapshots
        r3 = await self.request("GET", f"/api/snapshots/{arr_id}", sc, "list_snaps")
        await self.human_delay()

        # Try to diff if we have IDs
        try:
            body = await self._get_json(f"/api/snapshots/{arr_id}")
            if isinstance(body, list) and len(body) >= 2:
                id1 = body[0]["id"]
                id2 = body[1]["id"]
                await self.request("GET", f"/api/snapshots/diff?id1={id1}&id2={id2}", sc,
                                   "diff_snapshots")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # Helper
    # ═══════════════════════════════════════════════════════════
    async def _get_json(self, path: str):
        """Quick JSON GET."""
        url = f"{BASE_URL}{path}"
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return await resp.json()

    # ═══════════════════════════════════════════════════════════
    # Main Runner
    # ═══════════════════════════════════════════════════════════
    async def run(self):
        """Run endurance test for configured duration."""
        self.start_time = time.monotonic()
        end_time = self.start_time + TEST_DURATION_HOURS * 3600
        last_report = self.start_time
        cycle = 0

        scenarios = [
            ("dashboard", self.scenario_dashboard),
            ("array_detail", self.scenario_array_detail),
            ("traffic_switching", self.scenario_traffic_switching),
            ("alert_center", self.scenario_alert_center),
            ("cross_api_stress", self.scenario_cross_api_stress),
            ("edge_cases", self.scenario_edge_cases),
            ("concurrent", self.scenario_concurrent),
            ("system_alerts", self.scenario_system_alerts),
            ("test_tasks", self.scenario_test_tasks),
            ("snapshots", self.scenario_snapshots),
        ]

        print(f"╔══════════════════════════════════════════════════╗")
        print(f"║  Endurance Test — {TEST_DURATION_HOURS}h continuous run             ║")
        print(f"║  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                  ║")
        print(f"║  Target: {BASE_URL}                  ║")
        print(f"╚══════════════════════════════════════════════════╝")
        print()

        connector = aiohttp.TCPConnector(limit=10, limit_per_host=10)
        async with aiohttp.ClientSession(connector=connector) as session:
            self.session = session

            while time.monotonic() < end_time:
                cycle += 1
                # Pick 2-3 random scenarios per cycle
                chosen = random.sample(scenarios, k=min(3, len(scenarios)))

                for name, func in chosen:
                    try:
                        await func()
                    except Exception as e:
                        self._record_bug(
                            f"scenario_crash_{name}",
                            "FRAMEWORK_BUG",
                            "SCENARIO_CRASH",
                            f"Scenario '{name}' crashed: {str(e)[:200]}",
                            name,
                            f"Run scenario_{name}()",
                        )
                        print(f"  ⚠ Scenario {name} crashed: {str(e)[:100]}")

                # Progress report
                now = time.monotonic()
                if now - last_report >= REPORT_INTERVAL:
                    elapsed_h = (now - self.start_time) / 3600
                    remain_h = max(0, (end_time - now) / 3600)
                    total = sum(s["total"] for s in self.stats.values())
                    fails = sum(s["fail"] for s in self.stats.values())
                    bug_count = len(self.bugs)
                    print(f"  [{elapsed_h:.1f}h / {TEST_DURATION_HOURS}h] "
                          f"cycle={cycle} total={total} fail={fails} bugs={bug_count} "
                          f"remain={remain_h:.1f}h")
                    last_report = now

        elapsed = (time.monotonic() - self.start_time) / 3600
        print(f"\n✓ Test completed after {elapsed:.2f} hours, {cycle} cycles")
        return self.generate_report()

    def generate_report(self) -> str:
        """Generate markdown test report."""
        elapsed_h = (time.monotonic() - self.start_time) / 3600
        total = sum(s["total"] for s in self.stats.values())
        passes = sum(s["pass"] for s in self.stats.values())
        fails = sum(s["fail"] for s in self.stats.values())
        pass_rate = (passes / total * 100) if total > 0 else 0

        lines = []
        lines.append("# 耐久性测试报告")
        lines.append("")
        lines.append(f"**测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**持续时长**: {elapsed_h:.2f} 小时")
        lines.append(f"**总请求数**: {total}")
        lines.append(f"**通过**: {passes} | **失败**: {fails} | **通过率**: {pass_rate:.1f}%")
        lines.append(f"**发现 Bug 数**: {len(self.bugs)}")
        lines.append("")

        # Stats by scenario
        lines.append("## 一、各场景统计")
        lines.append("")
        lines.append("| 场景 | 总请求 | 通过 | 失败 | 平均耗时(ms) | 最大耗时(ms) |")
        lines.append("|------|--------|------|------|-------------|-------------|")
        for sc_name, s in sorted(self.stats.items()):
            lines.append(f"| {sc_name} | {s['total']} | {s['pass']} | {s['fail']} | "
                         f"{s['avg_ms']:.1f} | {s['max_ms']:.1f} |")
        lines.append("")

        # Response time distribution
        lines.append("## 二、响应时间分布")
        lines.append("")
        buckets = {"<100ms": 0, "100-500ms": 0, "500ms-1s": 0, "1-5s": 0, ">5s": 0}
        for r in self.results:
            ms = r.response_time_ms
            if ms < 100:
                buckets["<100ms"] += 1
            elif ms < 500:
                buckets["100-500ms"] += 1
            elif ms < 1000:
                buckets["500ms-1s"] += 1
            elif ms < 5000:
                buckets["1-5s"] += 1
            else:
                buckets[">5s"] += 1

        lines.append("| 区间 | 请求数 | 占比 |")
        lines.append("|------|--------|------|")
        for bucket, count in buckets.items():
            pct = (count / total * 100) if total > 0 else 0
            lines.append(f"| {bucket} | {count} | {pct:.1f}% |")
        lines.append("")

        # Bugs
        lines.append("## 三、发现的 Bug")
        lines.append("")
        if not self.bugs:
            lines.append("未发现 Bug。")
        else:
            small_bugs = [b for b in self.bugs.values() if b.severity == "SMALL_BUG"]
            framework_bugs = [b for b in self.bugs.values() if b.severity == "FRAMEWORK_BUG"]

            if small_bugs:
                lines.append("### 3.1 小型 Bug（已修复 / 可修复）")
                lines.append("")
                for i, b in enumerate(small_bugs, 1):
                    lines.append(f"**Bug-S{i}**: {b.description}")
                    lines.append(f"- 类别: {b.category}")
                    lines.append(f"- 端点: `{b.endpoint}`")
                    lines.append(f"- 出现次数: {b.occurrences}")
                    lines.append(f"- 首次出现: {b.first_seen}")
                    lines.append(f"- 复现: `{b.repro_steps}`")
                    if b.fixed:
                        lines.append(f"- **已修复**: {b.fix_description}")
                    lines.append("")

            if framework_bugs:
                lines.append("### 3.2 框架级 Bug（需架构调整，仅标记）")
                lines.append("")
                for i, b in enumerate(framework_bugs, 1):
                    lines.append(f"**Bug-F{i}**: {b.description}")
                    lines.append(f"- 类别: {b.category}")
                    lines.append(f"- 端点: `{b.endpoint}`")
                    lines.append(f"- 出现次数: {b.occurrences}")
                    lines.append(f"- 首次/末次: {b.first_seen} ~ {b.last_seen}")
                    lines.append(f"- 复现: `{b.repro_steps}`")
                    lines.append("")

        # Top failing endpoints
        fail_counts = defaultdict(int)
        for r in self.results:
            if not r.success:
                fail_counts[r.test_name] += 1

        if fail_counts:
            lines.append("## 四、失败热点")
            lines.append("")
            lines.append("| 测试项 | 失败次数 |")
            lines.append("|--------|----------|")
            for name, count in sorted(fail_counts.items(), key=lambda x: -x[1])[:20]:
                lines.append(f"| {name} | {count} |")
            lines.append("")

        # Slow endpoints
        lines.append("## 五、慢请求 Top 10")
        lines.append("")
        slow = sorted(self.results, key=lambda r: -r.response_time_ms)[:10]
        lines.append("| 测试项 | 场景 | 耗时(ms) | 状态 |")
        lines.append("|--------|------|----------|------|")
        for r in slow:
            status = "✓" if r.success else f"✗ {r.status_code}"
            lines.append(f"| {r.test_name} | {r.scenario} | {r.response_time_ms:.1f} | {status} |")
        lines.append("")

        # Conclusion
        lines.append("## 六、结论与建议")
        lines.append("")
        if pass_rate >= 99:
            lines.append("系统在4小时耐久测试中表现**优秀**，通过率 ≥99%。")
        elif pass_rate >= 95:
            lines.append("系统在4小时耐久测试中表现**良好**，通过率 ≥95%，存在少量非致命问题。")
        elif pass_rate >= 90:
            lines.append("系统在4小时耐久测试中表现**一般**，通过率 ≥90%，需要关注失败场景。")
        else:
            lines.append("系统在4小时耐久测试中**存在较多问题**，建议优先修复后再推广。")
        lines.append("")

        if any(b.severity == "FRAMEWORK_BUG" for b in self.bugs.values()):
            lines.append("### 框架级问题建议")
            lines.append("")
            for b in self.bugs.values():
                if b.severity == "FRAMEWORK_BUG":
                    lines.append(f"- **{b.description}**: 出现 {b.occurrences} 次，需要架构层面修复")
            lines.append("")

        return "\n".join(lines)


async def main():
    runner = EnduranceTestRunner()
    report = await runner.run()

    # Save report
    report_path = Path(__file__).parent.parent / "耐久性测试报告.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n📄 Report saved to: {report_path}")

    # Also save raw data for analysis
    raw_path = Path(__file__).parent / "endurance_raw.json"
    raw_data = {
        "bugs": {k: {
            "id": v.id, "severity": v.severity, "category": v.category,
            "description": v.description, "endpoint": v.endpoint,
            "occurrences": v.occurrences, "first_seen": v.first_seen,
            "last_seen": v.last_seen, "fixed": v.fixed,
        } for k, v in runner.bugs.items()},
        "stats": dict(runner.stats),
        "total_results": len(runner.results),
        "fail_results": [
            {"test": r.test_name, "scenario": r.scenario, "status": r.status_code,
             "error": r.error[:200], "ms": round(r.response_time_ms, 1)}
            for r in runner.results if not r.success
        ][:500],  # cap at 500 to keep file manageable
    }
    raw_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📊 Raw data saved to: {raw_path}")


if __name__ == "__main__":
    asyncio.run(main())
