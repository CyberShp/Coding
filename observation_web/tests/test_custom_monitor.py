"""Tests for custom-observer rule-based alerting (scheduler._alert_from_rule).

Previously scheduled/auto-monitor query templates only stored stdout and never
raised alerts, so the whole "custom monitor detects an anomaly" promise was a
no-op.  These verify the rule is actually applied and a real Alert is created.
"""
import pytest

from backend.core.scheduler import TaskScheduler
from backend.core.alert_store import get_alert_store
from backend.models.query import QueryTemplateModel


def _template(name, alert_on_mismatch=True):
    return QueryTemplateModel(
        name=name,
        commands='["systemctl is-active sshd"]',
        rule_type="valid_match",
        pattern="OK",
        expect_match=True,           # "OK" present == normal
        auto_monitor=True,
        monitor_arrays='["arr1"]',
        alert_on_mismatch=alert_on_mismatch,
    )


@pytest.mark.asyncio
async def test_rule_creates_alert_on_anomaly(db_session):
    sched = TaskScheduler()
    tmpl = _template("svc-check")
    db_session.add(tmpl)
    await db_session.flush()

    await sched._alert_from_rule(db_session, tmpl, "arrA", "check", "FAIL: service down")

    alerts = await get_alert_store().get_alerts(db_session, array_id="arrA", limit=10)
    assert len(alerts) == 1
    assert alerts[0].observer_name == "custom:svc-check"


@pytest.mark.asyncio
async def test_rule_no_alert_when_output_normal(db_session):
    sched = TaskScheduler()
    tmpl = _template("svc-ok")
    db_session.add(tmpl)
    await db_session.flush()

    await sched._alert_from_rule(db_session, tmpl, "arrB", "check", "OK")

    alerts = await get_alert_store().get_alerts(db_session, array_id="arrB", limit=10)
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_alert_suppressed_when_flag_off(db_session):
    sched = TaskScheduler()
    tmpl = _template("svc-quiet", alert_on_mismatch=False)
    db_session.add(tmpl)
    await db_session.flush()

    await sched._alert_from_rule(db_session, tmpl, "arrC", "check", "FAIL")

    alerts = await get_alert_store().get_alerts(db_session, array_id="arrC", limit=10)
    assert len(alerts) == 0
