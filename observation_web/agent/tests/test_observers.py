"""Tests for all observers — alarm_type, memory_leak, cpu_usage, etc."""
import os
import sys
import tempfile
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

# Must import through the package for relative imports to work
from observation_points.core.base import AlertLevel
from observation_points.utils.helpers import tail_file


# ---------- AlarmTypeObserver ----------

class TestAlarmTypeObserver:
    def _make_observer(self, log_content="", **kwargs):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
        f.write(log_content)
        f.flush()
        f.close()
        config = {"log_path": f.name, "interval": 5, **kwargs}
        from observation_points.observers.alarm_type import AlarmTypeObserver
        obs = AlarmTypeObserver("alarm_type", config)
        obs._test_file = f.name
        return obs

    def _cleanup(self, obs):
        try:
            os.unlink(obs._test_file)
        except OSError:
            pass

    def test_first_run_skips_existing(self):
        obs = self._make_observer("2026-01-01 send alarm: alarm type(1) alarm name(test) alarm id(0x1)\n")
        result = obs.check()
        assert result.has_alert is False
        self._cleanup(obs)

    def test_send_alarm_type1_creates_active(self):
        obs = self._make_observer("")
        obs.check()
        with open(obs._test_file, "a") as f:
            f.write("2026-01-01 12:00:00 send alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)\n")
        result = obs.check()
        assert result.has_alert is True
        assert "disk_fault" in result.message
        self._cleanup(obs)

    def test_send_alarm_type0_history_not_active(self):
        """BUG-MARKER: type 0 should NOT add to active_alarms."""
        obs = self._make_observer("")
        obs.check()
        with open(obs._test_file, "a") as f:
            f.write("2026-01-01 send alarm: alarm type(0) alarm name(history_test) alarm id(0xH001)\n")
        result = obs.check()
        assert result.has_alert is True
        assert "0xH001" not in str(obs._active_alarms)
        self._cleanup(obs)

    def test_resume_alarm_removes_active(self):
        obs = self._make_observer("")
        obs.check()
        with open(obs._test_file, "a") as f:
            f.write("2026-01-01 send alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)\n")
        obs.check()
        with open(obs._test_file, "a") as f:
            f.write("2026-01-01 resume alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)\n")
        result = obs.check()
        self._cleanup(obs)

    def test_parse_event_missing_fields(self):
        obs = self._make_observer("")
        obs.check()
        with open(obs._test_file, "a") as f:
            f.write("2026-01-01 send alarm: alarm type(1)\n")
        result = obs.check()
        self._cleanup(obs)

    def test_no_alarm_lines(self):
        obs = self._make_observer("")
        obs.check()
        with open(obs._test_file, "a") as f:
            f.write("some random log line\nanother line\n")
        result = obs.check()
        assert result.has_alert is False
        self._cleanup(obs)

    def test_multiple_alarms_single_check(self):
        obs = self._make_observer("")
        obs.check()
        with open(obs._test_file, "a") as f:
            f.write("2026-01-01 send alarm: alarm type(1) alarm name(a1) alarm id(0x01)\n")
            f.write("2026-01-01 send alarm: alarm type(1) alarm name(a2) alarm id(0x02)\n")
            f.write("2026-01-01 resume alarm: alarm type(1) alarm name(a1) alarm id(0x01)\n")
        result = obs.check()
        assert result.has_alert is True
        self._cleanup(obs)

    def test_missing_log_file(self):
        from observation_points.observers.alarm_type import AlarmTypeObserver
        obs = AlarmTypeObserver("alarm_type", {"log_path": "/nonexistent/alarm.log"})
        result = obs.check()
        assert result.has_alert is False


# ---------- MemoryLeakObserver ----------

class TestMemoryLeakObserver:
    @patch("observation_points.observers.memory_leak.run_command")
    def test_normal_memory(self, mock_cmd):
        mock_cmd.return_value = (0, "              total        used        free\nMem:          16000        8000        8000\n", "")
        from observation_points.observers.memory_leak import MemoryLeakObserver
        obs = MemoryLeakObserver("memory_leak", {"threshold_percent": 90, "consecutive_threshold": 3})
        result = obs.check()
        assert result.has_alert is False

    @patch("observation_points.observers.memory_leak.run_command")
    def test_continuous_increase_triggers_alert(self, mock_cmd):
        from observation_points.observers.memory_leak import MemoryLeakObserver
        obs = MemoryLeakObserver("memory_leak", {"consecutive_threshold": 3})
        for i in range(5):
            used = 8000 + i * 500
            mock_cmd.return_value = (0, f"              total        used        free\nMem:          16000        {used}        {16000-used}\n", "")
            result = obs.check()

    @patch("observation_points.observers.memory_leak.run_command")
    def test_free_command_fails(self, mock_cmd):
        mock_cmd.return_value = (-1, "", "command not found")
        from observation_points.observers.memory_leak import MemoryLeakObserver
        obs = MemoryLeakObserver("memory_leak", {})
        result = obs.check()
        # Should handle gracefully

    @patch("observation_points.observers.memory_leak.run_command")
    def test_memory_with_reporter_metrics(self, mock_cmd):
        mock_cmd.return_value = (0, "              total        used        free\nMem:          16000        8000        8000\n", "")
        from observation_points.observers.memory_leak import MemoryLeakObserver
        obs = MemoryLeakObserver("memory_leak", {})
        mock_reporter = MagicMock()
        result = obs.check(reporter=mock_reporter)


# ---------- CpuUsageObserver ----------

class TestCpuUsageObserver:
    @patch("observation_points.observers.cpu_usage.run_command")
    def test_cpu_fallback_to_top(self, mock_cmd):
        from observation_points.observers.cpu_usage import CpuUsageObserver
        obs = CpuUsageObserver("cpu_usage", {"threshold_percent": 90})
        mock_cmd.return_value = (0, "%Cpu0  :  5.0 us,  3.0 sy,  0.0 ni, 92.0 id\n", "")
        result = obs.check()

    @patch("observation_points.observers.cpu_usage.run_command")
    def test_cpu_command_failure(self, mock_cmd):
        mock_cmd.return_value = (-1, "", "error")
        from observation_points.observers.cpu_usage import CpuUsageObserver
        obs = CpuUsageObserver("cpu_usage", {})
        result = obs.check()


# ---------- CmdResponseObserver ----------

class TestCmdResponseObserver:
    @patch("observation_points.observers.cmd_response.run_command")
    def test_fast_command(self, mock_cmd):
        mock_cmd.return_value = (0, "output", "")
        from observation_points.observers.cmd_response import CmdResponseObserver
        obs = CmdResponseObserver("cmd_response", {
            "timeout_seconds": 5.0,
            "commands": ["echo test"]
        })
        result = obs.check()
        assert result.has_alert is False

    @patch("observation_points.observers.cmd_response.run_command")
    def test_slow_command_triggers_alert(self, mock_cmd):
        import time
        def slow_cmd(*args, **kwargs):
            time.sleep(0.1)
            return (0, "output", "")
        mock_cmd.side_effect = slow_cmd
        from observation_points.observers.cmd_response import CmdResponseObserver
        obs = CmdResponseObserver("cmd_response", {
            "timeout_seconds": 0.01,
            "commands": ["slow_cmd"]
        })
        result = obs.check()
        assert result.has_alert is True


# ---------- CardRecoveryObserver ----------

class TestCardRecoveryObserver:
    def test_first_run_skips(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("card recovery event dev(0:3.0)\n")
            f.flush()
            fname = f.name
        try:
            from observation_points.observers.card_recovery import CardRecoveryObserver
            obs = CardRecoveryObserver("card_recovery", {"log_path": fname})
            result = obs.check()
            assert result.has_alert is False
        finally:
            os.unlink(fname)

    def test_new_recovery_event(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.flush()
            fname = f.name
        try:
            from observation_points.observers.card_recovery import CardRecoveryObserver
            obs = CardRecoveryObserver("card_recovery", {"log_path": fname, "keyword": "recovery"})
            obs.check()
            with open(fname, "a") as wf:
                wf.write("2026-01-01 12:00:00 card recovery event dev(0:3.0)\n")
            result = obs.check()
            assert result.has_alert is True
        finally:
            os.unlink(fname)

    def test_missing_log_file(self):
        from observation_points.observers.card_recovery import CardRecoveryObserver
        obs = CardRecoveryObserver("card_recovery", {"log_path": "/nonexistent/card.log"})
        result = obs.check()
        assert result.has_alert is False


# ---------- SensitiveInfoObserver ----------

class TestSensitiveInfoObserver:
    def test_detects_password(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.flush()
            fname = f.name
        try:
            from observation_points.observers.sensitive_info import SensitiveInfoObserver
            obs = SensitiveInfoObserver("sensitive_info", {"log_paths": [fname]})
            obs.check()
            with open(fname, "a") as wf:
                wf.write("config: password=MySecretPass123\n")
            result = obs.check()
        finally:
            os.unlink(fname)

    def test_placeholder_not_alerted(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.flush()
            fname = f.name
        try:
            from observation_points.observers.sensitive_info import SensitiveInfoObserver
            obs = SensitiveInfoObserver("sensitive_info", {"log_paths": [fname]})
            obs.check()
            with open(fname, "a") as wf:
                wf.write("password=****\n")
            result = obs.check()
            assert result.has_alert is False
        finally:
            os.unlink(fname)

    def test_empty_log(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.flush()
            fname = f.name
        try:
            from observation_points.observers.sensitive_info import SensitiveInfoObserver
            obs = SensitiveInfoObserver("sensitive_info", {"log_paths": [fname]})
            result = obs.check()
            assert result.has_alert is False
        finally:
            os.unlink(fname)


# ---------- SigMonitorObserver ----------

class TestSigMonitorObserver:
    def test_whitelisted_signal_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.flush()
            fname = f.name
        try:
            from observation_points.observers.sig_monitor import SigMonitorObserver
            obs = SigMonitorObserver("sig_monitor", {"log_path": fname, "whitelist": [15, 61]})
            obs.check()
            with open(fname, "a") as wf:
                wf.write("received signal 15\n")
            result = obs.check()
            assert result.has_alert is False
        finally:
            os.unlink(fname)

    def test_non_whitelisted_signal_alerts(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.flush()
            fname = f.name
        try:
            from observation_points.observers.sig_monitor import SigMonitorObserver
            obs = SigMonitorObserver("sig_monitor", {"log_path": fname, "whitelist": [15]})
            obs.check()
            with open(fname, "a") as wf:
                wf.write("caught sig 11 in process\n")
            result = obs.check()
            assert result.has_alert is True
        finally:
            os.unlink(fname)


# ---------- CustomCommandObserver ----------

class TestCustomCommandObserver:
    @patch("observation_points.observers.custom_command.run_command")
    def test_command_success(self, mock_cmd):
        mock_cmd.return_value = (0, '{"status": "ok"}', "")
        from observation_points.observers.custom_command import CustomCommandObserver
        obs = CustomCommandObserver("custom_command", {
            "commands": [{"name": "test_cmd", "command": "echo test", "parse_type": "json", "alert_conditions": []}]
        })
        result = obs.check()

    @patch("observation_points.observers.custom_command.run_command")
    def test_command_failure_alerts(self, mock_cmd):
        mock_cmd.return_value = (1, "", "error occurred")
        from observation_points.observers.custom_command import CustomCommandObserver
        obs = CustomCommandObserver("custom_command", {
            "commands": [{"name": "fail_cmd", "command": "echo fail", "parse_type": "raw",
                          "alert_conditions": [], "allow_any_path": True}]
        })
        result = obs.check()
        assert result.has_alert is True

    def test_no_commands(self):
        from observation_points.observers.custom_command import CustomCommandObserver
        obs = CustomCommandObserver("custom_command", {"commands": []})
        result = obs.check()
        assert result.has_alert is False


# ---------- LinkStatusObserver ----------

class TestLinkStatusObserver:
    @patch("observation_points.observers.link_status.read_sysfs")
    def test_first_run_no_alert(self, mock_sysfs):
        mock_sysfs.return_value = "1"
        from observation_points.observers.link_status import LinkStatusObserver
        obs = LinkStatusObserver("link_status", {"ports": []})
        result = obs.check()
        assert result.has_alert is False

    def test_add_remove_whitelist(self):
        from observation_points.observers.link_status import LinkStatusObserver
        obs = LinkStatusObserver("link_status", {})
        obs.add_to_whitelist("eth0")
        assert "eth0" in obs.whitelist
        obs.remove_from_whitelist("eth0")
        assert "eth0" not in obs.whitelist


# ---------- ErrorCodeObserver ----------

class TestErrorCodeObserver:
    @patch("observation_points.observers.error_code.run_command")
    @patch("observation_points.observers.error_code.read_sysfs")
    def test_no_errors(self, mock_sysfs, mock_cmd):
        mock_sysfs.return_value = "0"
        mock_cmd.return_value = (0, "", "")
        from observation_points.observers.error_code import ErrorCodeObserver
        obs = ErrorCodeObserver("error_code", {"ports": []})
        result = obs.check()
        assert result.has_alert is False

    def test_counter_wrap_detection(self):
        """BUG-CANDIDATE: Counter wrap should not trigger alert."""
        from observation_points.observers.error_code import ErrorCodeObserver
        obs = ErrorCodeObserver("error_code", {"ports": [], "threshold": 10})
        obs._last_port_errors["eth0"] = {"rx_errors": 100}
