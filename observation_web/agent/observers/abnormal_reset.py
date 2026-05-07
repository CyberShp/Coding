"""
异常复位检查观察点

归属：系统级检查
通过 os_cli 执行单命令，读取输出文件，检测异常复位原因。

os_cli 是单命令工具（非交互式 shell）：
  1. 运行 os_cli <cmd> → 将结果写入 /OSM/log/cur_debug/log_reset.txt
  2. 用 cat 读取输出文件
  3. 解析 reason / time 字段
"""

import logging
import re
import select
import subprocess
import threading
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
    """Background thread: non-blocking reads so small outputs don't stall."""
    try:
        while not stop_event.is_set():
            # select with 0.5 s timeout avoids blocking on pipes with < 4096 bytes
            ready, _, _ = select.select([pipe], [], [], 0.5)
            if ready:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                buf.append(chunk)
    except Exception:
        pass


class AbnormalResetObserver(BaseObserver):
    """
    异常复位检查 — 两步单命令模式

    工作流程：
    1. 执行 os_cli <inner_cmd>（单命令，写入 log_reset.txt）
    2. cat /OSM/log/cur_debug/log_reset.txt 读取输出
    3. 解析 reason / time，匹配异常关键字则上报告警
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.os_cli_cmd = config.get('os_cli_cmd', '') or config.get('os_cli_path', '') or 'os_cli'
        self.inner_cmd = config.get('inner_cmd', 'cat log_reset.txt')
        self.output_file = config.get('output_file', '/OSM/log/cur_debug/log_reset.txt')
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

    def _run_single_command(self, cmd: str) -> tuple:
        """
        Execute a single shell command.
        Returns (returncode, stdout, stderr).
        Uses select-based non-blocking reads to handle small outputs correctly.
        """
        if self.ensure_path:
            cmd = "export PATH=/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH && " + cmd

        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return -1, b"", f"Failed to start process: {e}".encode()

        stdout_buf = []
        stderr_buf = []
        stop = threading.Event()
        t_out = threading.Thread(
            target=_reader_thread, args=(proc.stdout, stdout_buf, stop), daemon=True
        )
        t_err = threading.Thread(
            target=_reader_thread, args=(proc.stderr, stderr_buf, stop), daemon=True
        )
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        finally:
            stop.set()
            t_out.join(timeout=2)
            t_err.join(timeout=2)

        stdout = b"".join(stdout_buf).decode(errors='replace')
        stderr = b"".join(stderr_buf).decode(errors='replace')
        return proc.returncode or 0, stdout, stderr

    def check(self) -> ObserverResult:
        # Step 1: run os_cli (single command — writes output to file)
        cli_cmd = f"{self.os_cli_cmd} {self.inner_cmd}"
        ret, _, stderr = self._run_single_command(cli_cmd)
        if ret != 0:
            err_preview = (stderr or '')[:200]
            if 'not found' in err_preview.lower() or 'no such file' in err_preview.lower():
                logger.warning(
                    "[abnormal_reset] os_cli 不存在或路径错误 (可配置 os_cli_cmd): %s", err_preview
                )
            else:
                logger.warning("[abnormal_reset] os_cli 执行失败: %s", err_preview)
            return self.create_result(
                has_alert=False,
                message="异常复位: 命令执行失败",
                details={'stderr': err_preview},
            )

        # Step 2: read the output file os_cli wrote
        ret, content, _ = self._run_single_command(f"cat {self.output_file}")
        if ret != 0:
            logger.warning("[abnormal_reset] 无法读取输出文件: %s", self.output_file)
            return self.create_result(
                has_alert=False,
                message="异常复位: 无法读取输出文件",
                details={'output_file': self.output_file},
            )

        # Step 3: parse and match
        entries = self._parse_log(content)
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
                    alerts.append({'reason': reason, 'time': ts})
                    self._last_reported_times.add(ts)
                    logger.warning("[abnormal_reset] 异常复位: %s @ %s", reason, ts)
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
        current: Dict[str, str] = {}

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
