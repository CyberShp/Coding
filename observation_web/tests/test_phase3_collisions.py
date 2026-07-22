"""Phase 3 multi-user collision rules: ack-undo protection + test-window expected."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from backend.api.acknowledgements import _can_modify_ack
from backend.core.alert_store import get_alert_store
from backend.models.alert import AlertCreate, AlertLevel
from backend.models.array_lock import ArrayLockModel
from backend.models.task_session import TaskSessionModel


# ── ack undo protection (pure permission logic) ──────────────────────────
def _user(nickname, is_admin=False):
    return SimpleNamespace(id=1, nickname=nickname, is_admin=is_admin)


def _ack(acked_by):
    return SimpleNamespace(acked_by_ip=acked_by)


def test_acknowledger_can_undo_own():
    assert _can_modify_ack(_user("alice"), _ack("alice")) is True


def test_other_user_cannot_undo():
    assert _can_modify_ack(_user("bob"), _ack("alice")) is False


def test_admin_can_undo_any():
    assert _can_modify_ack(_user("carol", is_admin=True), _ack("alice")) is True


def test_anyone_can_undo_system_ack():
    assert _can_modify_ack(_user("bob"), _ack("system")) is True


# ── test-window expected auto-flagging ───────────────────────────────────
def _alert(array_id="arrL", msg="disk fault"):
    return AlertCreate(
        array_id=array_id, observer_name="disk", level=AlertLevel.ERROR,
        message=msg, details={}, timestamp=datetime(2026, 1, 1),
    )


async def _mk_task(db):
    t = TaskSessionModel(name="io-test-1", task_type="io_test", array_ids='["arrL"]', status="running")
    db.add(t)
    await db.flush()
    return t


@pytest.mark.asyncio
async def test_alert_not_expected_when_unlocked(db_session):
    created = await get_alert_store().create_alert(db_session, _alert())
    assert created.is_expected == 0


@pytest.mark.asyncio
async def test_alert_flagged_expected_under_test_lock(db_session):
    from datetime import datetime
    task = await _mk_task(db_session)
    db_session.add(ArrayLockModel(array_id="arrL", task_id=task.id, locked_by_nickname="alice"))
    await db_session.flush()

    a = _alert()
    a.timestamp = datetime(2026, 1, 1)
    created = await get_alert_store().create_alert(db_session, a)
    assert created.is_expected == 1
    assert created.task_id == task.id
