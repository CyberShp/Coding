"""
异常复位检查观察点

归属：系统级检查
通过 os_cli 进入阵列环境，读取 log_reset.txt，检测异常复位原因。

os_cli 是交互式命令：
  1. 运行 os_cli → 等待回显 "succeed" 或 "success"（约 5 秒）
  2. 就绪后在同一会话中执行 cat log_reset.txt
  3. 解析输出中的 reason / time 字段
"""

import logging
import os
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Set

from ..core.base import BaseObserver, ObserverResult, AlertLevel

logger = logging.getLogger(__name__)

DEFAULT_ABNORMAL_REASONS = [
    'watchDog reset',
    'oops reset',
    'unknown reset',
    'oom reset',
    'panic reset',
    'kernel reset',
    'mce reset',
    'bios reset',
    'software unknown reset',
    'failure recovery reset',
]


def _reader_thread(pipe, buf: list, stop_event: threading.Event):
    """Background thread to read from pipe without blocking."""
    try:
        while not stop_event.is_set():
            chunk = pipe.read(4096)
            if not chunk:
                break
            buf.append(chunk)
    except Exception:
        pass


class AbnormalResetObserver(BaseObserver):
    """
    异常复位检查 — 两阶段交互执行 os_cli

    工作流程：
    1. 启动 os_cli 子进程
    2. 等待 stdout 中出现就绪关键字（succeed / success）
    3. 向 stdin 写入 inner_cmd（默认 cat log_reset.txt）
    4. 写入 exit 退出 os_cli
    5. 读取全部输出并解析 reason / time
    6. 匹配异常关键字则上报告警，记录时间戳避免重复
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.os_cli_cmd = config.get('os_cli_cmd', '') or config.get('os_cli_path', '') or 'os_cli'
        self.inner_cmd = config.get('inner_cmd', 'cat log_reset.txt')
        self.ready_timeout = config.get('ready_timeout', 10)
        self.ready_keyword = config.get('ready_keyword', 'succeed')
        self.ensure_path = config.get('ensure_path', True)

        # Legacy: support old 'command' field for backward-compat
        old_cmd = config.get('command', '')
        if old_cmd and 'os_cli' not in old_cmd:
            self.inner_cmd = old_cmd

        reasons = config.get('abnormal_reasons', DEFAULT_ABNORMAL_REASONS)
        self.abnormal_patterns = [
            re.compile(re.escape(r), re.IGNORECASE)
            for r in reasons
        ]
        self._last_reported_times: Set[str] = set()

    def _run_os_cli(self) -> tuple:
        """
        Two-stage interactive execution:
          Stage 1: start os_cli, wait for ready keyword
          Stage 2: send inner command, read output
        Returns (returncode, stdout, stderr)
        """
        cmd = self.os_cli_cmd
        if self.ensure_path:
            cmd = "export PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH && " + cmd

        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            return -1, "", f"Failed to start os_cli: {e}"

        stdout_buf = []
        stderr_buf = []
        stop = threading.Event()
        t_out = threading.Thread(target=_reader_thread, args=(proc.stdout, stdout_buf, stop), daemon=True)
        t_err = threading.Thread(target=_reader_thread, args=(proc.stderr, stderr_buf, stop), daemon=True)
        t_out.start()
        t_err.start()

        # Stage 1: wait for ready keyword
        deadline = time.time() + self.ready_timeout
        ready = False
        keywords = [self.ready_keyword.lower()]
        if self.ready_keyword.lower() != 'success':
            keywords.append('success')

        while time.time() < deadline:
            combined = "".join(stdout_buf).lower()
            if any(kw in combined for kw in keywords):
                ready = True
                break
            time.sleep(0.3)

        if not ready:
            proc.kill()
            stop.set()
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            return -1, "".join(stdout_buf), "os_cli 未就绪 (未检测到 succeed/success)"

        # Stage 2: send the actual command
        try:
            proc.stdin.write(self.inner_cmd + "\n")
            proc.stdin.write("exit\n")
            proc.stdin.flush()
        except Exception as e:
            proc.kill()
            stop.set()
            return -1, "".join(stdout_buf), f"写入命令失败: {e}"

        # Wait for process to finish
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()

        stop.set()
        t_out.join(timeout=2)
        t_err.join(timeout=2)

        return proc.returncode or 0, "".join(stdout_buf), "".join(stderr_buf)

    def check(self) -> ObserverResult:
        ret, stdout, stderr = self._run_os_cli()

        if ret != 0:
            err_preview = (stderr or '')[:200]
            if 'not found' in err_preview.lower() or 'no such file' in err_preview.lower():
                logger.warning(
                    f"[abnormal_reset] os_cli 不存在或路径错误 (可配置 os_cli_cmd): {err_preview}"
                )
            else:
                logger.warning(f"[abnormal_reset] 命令执行失败: {err_preview}")
            return self.create_result(
                has_alert=False,
                message="异常复位: 命令执行失败",
                details={'stderr': err_preview},
            )

        entries = self._parse_log(stdout)
        alerts = []

        for entry in entries:
            reason = entry.get('reason', '')
            ts = entry.get('time', '')
            if not reason or not ts:
                continue

            if ts in self._last_reported_times:
                continue

            for pat in self.abnormal_patterns:
                if pat.search(reason):
                    alerts.append({
                        'reason': reason,
                        'time': ts,
                    })
                    self._last_reported_times.add(ts)
                    logger.warning(f"[abnormal_reset] 异常复位: {reason} @ {ts}")
                    break

        if alerts:
            msgs = [f"{a['reason']} ({a['time']})" for a in alerts]
            msg = "; ".join(msgs[:5])
            if len(msgs) > 5:
                msg += f" ... 共 {len(msgs)} 条"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"异常复位: {msg}",
                details={'alerts': alerts},
            )

        return self.create_result(
            has_alert=False,
            message="异常复位: 无新增异常",
        )

    def _parse_log(self, text: str) -> List[Dict[str, str]]:
        """解析 log_reset.txt，提取 reason 和 time"""
        entries = []
        current = {}

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                if current:
                    entries.append(current)
                    current = {}
                continue

            if ':' in line:
                key, _, val = line.partition(':')
                key = key.strip().lower()
                val = val.strip()
                if key in ('reason', 'time'):
                    current[key] = val

        if current:
            entries.append(current)
        return entries
