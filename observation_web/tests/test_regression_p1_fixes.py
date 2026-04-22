"""
Targeted regression tests for gpt52 P1 review findings on commit 4509720.

P1-1: health_checker per-array failure key never resets → false escalation
P1-2: idle_connection_cleaner sub-task failures swallowed, not escalated
P1-3: observer consecutive failures invisible to backend (no reporter.report call)
P1-4: observer backoff computed as interval × multiplier, no absolute cap
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_scheduler(reporter=None):
    """Instantiate Scheduler with mocked-out _load_observers and AgentUpdater."""
    import agent.core.scheduler as sched_mod

    if reporter is None:
        reporter = MagicMock()

    config = {"observers": {}, "global": {}}
    with (
        patch.object(sched_mod.Scheduler, "_load_observers"),
        patch("agent.core.scheduler.AgentUpdater"),
    ):
        s = sched_mod.Scheduler(config, reporter)
    return s


# ---------------------------------------------------------------------------
# P1-1: per-array health_checker failure counter resets independently
# ---------------------------------------------------------------------------


def test_per_array_failure_key_resets_on_success():
    """_reset_bg_failure("health_checker/arr-X") must not affect other array keys."""
    import backend.main as main_mod

    # Inject two independent per-array failure counts
    main_mod._bg_failure_counts["health_checker/arr-001"] = 4
    main_mod._bg_failure_counts["health_checker/arr-002"] = 2

    # Simulate arr-001 recovering
    main_mod._reset_bg_failure("health_checker/arr-001")

    assert "health_checker/arr-001" not in main_mod._bg_failure_counts, (
        "Per-array counter must be cleared after reset"
    )
    assert main_mod._bg_failure_counts.get("health_checker/arr-002") == 2, (
        "Unrelated per-array counter must not be touched"
    )

    # Cleanup
    main_mod._bg_failure_counts.pop("health_checker/arr-002", None)


def test_outer_health_checker_reset_does_not_clear_per_array_keys():
    """
    The outer _reset_bg_failure("health_checker") that was the sole reset
    before the fix must NOT clear per-array keys — they are keyed differently.
    """
    import backend.main as main_mod

    main_mod._bg_failure_counts["health_checker/arr-001"] = 3
    main_mod._bg_failure_counts["health_checker"] = 1

    main_mod._reset_bg_failure("health_checker")

    # Outer key cleared
    assert "health_checker" not in main_mod._bg_failure_counts
    # Per-array key untouched (must now be reset by the per-array reset call)
    assert main_mod._bg_failure_counts.get("health_checker/arr-001") == 3, (
        "Per-array key is separate from the outer key"
    )

    # Cleanup
    main_mod._bg_failure_counts.pop("health_checker/arr-001", None)


# ---------------------------------------------------------------------------
# P1-2: idle_connection_cleaner sub-task failures escalate to sys_error
# ---------------------------------------------------------------------------


def test_idle_cleanup_subtask_failure_escalates_after_threshold(monkeypatch):
    """
    idle_cleanup/traffic and idle_cleanup/ack failures must reach sys_error
    after _BG_FAILURE_THRESHOLD consecutive failures.
    """
    import backend.main as main_mod

    captured_errors = []
    monkeypatch.setattr(
        main_mod, "sys_error", lambda *a, **kw: captured_errors.append(a)
    )

    threshold = main_mod._BG_FAILURE_THRESHOLD

    # Drive failure count to threshold − 1 (still at WARNING)
    for _ in range(threshold - 1):
        main_mod._track_bg_failure("idle_cleanup/traffic", Exception("db gone"))

    assert not captured_errors, "Should not escalate below threshold"

    # One more → crosses threshold → sys_error
    main_mod._track_bg_failure("idle_cleanup/traffic", Exception("db gone"))

    assert captured_errors, "Must escalate to sys_error at threshold"

    # Cleanup
    main_mod._bg_failure_counts.pop("idle_cleanup/traffic", None)


def test_idle_cleanup_subtask_reset_clears_counter(monkeypatch):
    """_reset_bg_failure clears the sub-task counter on success."""
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "sys_info", lambda *a, **kw: None)

    main_mod._bg_failure_counts["idle_cleanup/ack"] = 3
    main_mod._reset_bg_failure("idle_cleanup/ack")

    assert "idle_cleanup/ack" not in main_mod._bg_failure_counts


# ---------------------------------------------------------------------------
# P1-3: observer consecutive failures emit backend-visible sticky alert
# Spec (critical-review-refactor-spec.md L243):
#   report only when count >= 10 AND count % 10 == 0
#   local ERROR log escalates at count >= 3 (separate threshold)
# ---------------------------------------------------------------------------


def test_observer_failure_below_log_threshold_is_warning():
    """Fewer than _FAILURE_LOG_THRESHOLD (3) failures → no ERROR log and no backend report."""
    mock_reporter = MagicMock()
    sched = _make_agent_scheduler(reporter=mock_reporter)

    import agent.core.scheduler as sched_mod

    for _ in range(sched_mod._FAILURE_LOG_THRESHOLD - 1):
        sched._record_failure("link_status", Exception("timeout"))

    mock_reporter.report.assert_not_called()


def test_observer_failure_below_alert_threshold_no_backend_report():
    """9 consecutive failures (< _ALERT_REPORT_THRESHOLD=10) must NOT call reporter.report()."""
    mock_reporter = MagicMock()
    sched = _make_agent_scheduler(reporter=mock_reporter)

    import agent.core.scheduler as sched_mod

    for _ in range(sched_mod._ALERT_REPORT_THRESHOLD - 1):
        sched._record_failure("error_code", Exception("SSH broken"))

    mock_reporter.report.assert_not_called()


def test_observer_failure_at_alert_threshold_emits_sticky_alert():
    """Exactly _ALERT_REPORT_THRESHOLD (10) consecutive failures → one sticky alert."""
    from agent.core.base import AlertLevel

    mock_reporter = MagicMock()
    sched = _make_agent_scheduler(reporter=mock_reporter)

    import agent.core.scheduler as sched_mod

    for _ in range(sched_mod._ALERT_REPORT_THRESHOLD):
        sched._record_failure("error_code", Exception("SSH broken"))

    mock_reporter.report.assert_called_once()
    result = mock_reporter.report.call_args[0][0]
    assert result.has_alert is True
    assert result.sticky is True
    assert result.alert_level == AlertLevel.ERROR
    assert result.observer_name == "error_code"


def test_observer_failure_between_multiples_no_extra_report():
    """Failures at counts 11-19 must NOT emit another alert (next is at 20)."""
    mock_reporter = MagicMock()
    sched = _make_agent_scheduler(reporter=mock_reporter)

    import agent.core.scheduler as sched_mod

    # Drive to exactly 10 (1 report)
    for _ in range(sched_mod._ALERT_REPORT_THRESHOLD):
        sched._record_failure("cpu_usage", Exception("stalled"))

    mock_reporter.report.reset_mock()

    # Counts 11-19: no additional reports
    for _ in range(sched_mod._ALERT_REPORT_THRESHOLD - 1):
        sched._record_failure("cpu_usage", Exception("stalled"))

    mock_reporter.report.assert_not_called()


def test_observer_failure_at_double_threshold_emits_second_alert():
    """At count=20 (2nd multiple of 10) exactly one additional alert is emitted."""
    mock_reporter = MagicMock()
    sched = _make_agent_scheduler(reporter=mock_reporter)

    import agent.core.scheduler as sched_mod

    for _ in range(sched_mod._ALERT_REPORT_THRESHOLD * 2):
        sched._record_failure("cpu_usage", Exception("stalled"))

    assert mock_reporter.report.call_count == 2


# ---------------------------------------------------------------------------
# P1-4: observer backoff has an absolute 900 s ceiling
# ---------------------------------------------------------------------------


def test_backoff_short_interval_within_cap():
    """A 30 s observer with 3 failures → 30 × 8 = 240 s, well under 900 s cap."""
    sched = _make_agent_scheduler()
    sched._observer_failures["link_status"] = 3

    delay = sched._backoff_delay("link_status", 30)
    assert delay == 30 * (2 ** 3)  # 240 s
    assert delay < 900


def test_backoff_long_interval_capped_at_900():
    """A 3600 s observer with 3 failures → 3600 × 8 = 28800 s > cap → must return 900."""
    sched = _make_agent_scheduler()
    sched._observer_failures["port_traffic"] = 3

    delay = sched._backoff_delay("port_traffic", 3600)
    assert delay == 900, f"Expected 900 s cap, got {delay}"


def test_backoff_no_previous_failures_uses_base_interval():
    """An observer with 0 failures → delay equals base_interval (2^0 = 1)."""
    sched = _make_agent_scheduler()

    delay = sched._backoff_delay("new_observer", 60)
    assert delay == 60


def test_backoff_always_positive():
    """Backoff must never be 0 regardless of failure count."""
    sched = _make_agent_scheduler()

    for count in range(10):
        sched._observer_failures["x"] = count
        assert sched._backoff_delay("x", 30) > 0
