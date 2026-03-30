"""P1/P2 observer regression tests."""

import logging
from unittest.mock import patch

from agent.core.base import AlertLevel
from agent.observers.card_info import CardInfoObserver
from agent.observers.port_error_code import PortErrorCodeObserver
from agent.observers.sfp_monitor import SfpMonitorObserver
from agent.observers.start_work import StartWorkObserver


class TestCardInfoP1:
    """P1: card_info undefine + multi-field aggregation."""

    @patch("agent.observers.card_info.run_command")
    def test_aggregate_running_health_model_into_single_alert(self, mock_cmd):
        mock_cmd.return_value = (
            0,
            "\n".join(
                [
                    "No001  BoardId: B001",
                    "No001  RunningState: OFFLINE",
                    "No001  HealthState: FAULT",
                    "No001  Model: Undefine",
                ]
            ),
            "",
        )
        obs = CardInfoObserver("card_info", {"command": "anytest intfboardallinfo"})
        result = obs.check()

        assert result.has_alert is True
        assert result.alert_level == AlertLevel.ERROR
        alerts = result.details.get("alerts", [])
        assert len(alerts) == 1
        fields = {f.get("field") for f in alerts[0].get("fields", [])}
        assert {"RunningState", "HealthState", "Model"}.issubset(fields)
        assert "RunningState" in result.message
        assert "HealthState" in result.message
        assert "Model" in result.message

    @patch("agent.observers.card_info.run_command")
    def test_ignores_banner_block_and_parses_real_cards_only(self, mock_cmd):
        mock_cmd.return_value = (
            0,
            "\n".join(
                [
                    "anytest intfboardallinfo ------- ok",
                    "No001  BoardId: B001",
                    "No001  RunningState: RUNNING",
                    "No001  HealthState: NORMAL",
                    "No001  Model: X1",
                    "--------------------",
                    "No002  BoardId: B002",
                    "No002  RunningState: RUNNING",
                    "No002  HealthState: NORMAL",
                    "No002  Model: X2",
                ]
            ),
            "",
        )
        obs = CardInfoObserver("card_info", {"command": "anytest intfboardallinfo"})
        result = obs.check()

        assert result.has_alert is False
        cards = result.details.get("cards", {})
        assert set(cards.keys()) == {"No001", "No002"}
        assert all(not key.startswith("Unknown_") for key in cards.keys())

    @patch("agent.observers.card_info.run_command")
    def test_banner_without_no_prefix_cards_is_ignored_without_warning(self, mock_cmd):
        mock_cmd.return_value = (
            0,
            "anytest intfboardallinfo ------- ok\nheader only\n------------\nfooter only\n",
            "",
        )
        obs = CardInfoObserver("card_info", {"command": "anytest intfboardallinfo"})
        result = obs.check()

        assert result.has_alert is False
        assert "无数据或解析失败" not in result.message

    @patch("agent.observers.card_info.run_command")
    def test_keeps_last_card_without_trailing_separator(self, mock_cmd):
        mock_cmd.return_value = (
            0,
            "\n".join(
                [
                    "noise before header",
                    "anytest intfboardallinfo ------- ok",
                    "No001  BoardId: B001",
                    "No001  RunningState: RUNNING",
                    "No001  HealthState: NORMAL",
                    "No001  Model: X1",
                    "--------------------",
                    "No002  BoardId: B002",
                    "No002  RunningState: OFFLINE",
                    "No002  HealthState: NORMAL",
                    "No002  Model: X2",
                ]
            ),
            "",
        )
        obs = CardInfoObserver("card_info", {"command": "anytest intfboardallinfo"})
        result = obs.check()

        assert result.has_alert is True
        alerts = result.details.get("alerts", [])
        assert len(alerts) == 1
        assert alerts[0]["card"] == "No002"


class TestStartWorkP1:
    """P1: start_work parsing and alert behavior."""

    @patch("agent.observers.gate.start_work.run_command")
    def test_start_work_detects_unstarted_modules(self, mock_cmd):
        mock_cmd.return_value = (
            0,
            "system module num: 3\nivs_edft: 1\nfoo_mod: 0\nbar_mod: 1\n",
            "",
        )
        obs = StartWorkObserver("start_work", {})
        result = obs.check()
        assert result.has_alert is True
        assert result.alert_level == AlertLevel.WARNING
        assert result.details.get("started") is False
        assert "foo_mod" in result.details.get("failed_modules", [])

    @patch("agent.observers.gate.start_work.run_command")
    def test_start_work_all_modules_started(self, mock_cmd):
        mock_cmd.return_value = (
            0,
            "system module num: 2\nmod_a: 1\nmod_b: 1\n",
            "",
        )
        obs = StartWorkObserver("start_work", {})
        result = obs.check()
        assert result.has_alert is False
        assert result.details.get("started") is True
        assert result.details.get("total_modules") == 2


class TestFCToleranceP2:
    """P2: FC not required -> downgrade noisy warnings to info."""

    @patch("agent.observers.port_counters.run_command")
    def test_port_error_code_fc_list_failure_logs_info(self, mock_cmd, caplog):
        # After consolidation, PortCountersObserver._get_anytest_ports handles
        # both Ethernet and FC.  When both port-listing commands fail, it just
        # returns empty lists without noisy warnings.
        mock_cmd.side_effect = [
            (1, "", "Eth not found"),
            (1, "", "FC not found"),
        ]
        obs = PortErrorCodeObserver("port_error_code", {
            "anytest_enabled": True,
            "pcie_enabled": False,
            "ports": [],  # disable sysfs path
        })

        with caplog.at_level(logging.DEBUG):
            result = obs.check()

        # No alert should be raised for listing failure
        assert result.has_alert is False

    @patch("agent.observers.sfp_monitor.run_command")
    def test_sfp_monitor_command_failure_logs_info_and_skips_cycle(self, mock_cmd, caplog):
        mock_cmd.return_value = (1, "", "FC card not found")
        obs = SfpMonitorObserver("sfp_monitor", {})

        with caplog.at_level(logging.INFO):
            result = obs.check()

        assert result.has_alert is False
        assert "命令执行失败" in result.message
        assert any("跳过本轮检测" in r.message and r.levelno == logging.INFO for r in caplog.records)
