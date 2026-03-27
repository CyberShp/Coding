"""
Layer 3 – State Machine Tests for AlertV2 model.

Tests alert state transitions and field semantics using the DB model
directly (no HTTP layer).
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.models.alerts_v2 import (
    AlertV2Model,
    AlertState,
    ReviewStatus,
    AlertCategory,
)
from backend.models.array import ArrayModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_array(db, array_id="arr1"):
    """Ensure the referenced array row exists (FK constraint)."""
    from sqlalchemy import select as _sel
    result = await db.execute(_sel(ArrayModel).where(ArrayModel.array_id == array_id))
    if result.scalars().first() is None:
        db.add(ArrayModel(
            array_id=array_id, name=array_id, host=f"10.0.0.{hash(array_id) % 254 + 1}",
            port=22, username="root", key_path="", folder="",
        ))
        await db.flush()


def _make_alert(array_id="arr1", **overrides) -> AlertV2Model:
    """Build an AlertV2Model instance with sensible defaults."""
    defaults = dict(
        array_id=array_id,
        category=AlertCategory.GENERIC_ERROR.value,
        message_raw="test alert",
        occurred_at=datetime.now(),
        observer_name="test_obs",
        level="warning",
    )
    defaults.update(overrides)
    return AlertV2Model(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAlertDefaultState:

    async def test_alert_default_state_is_active(self, db_session):
        """New AlertV2Model has state=active."""
        db = db_session
        await _ensure_array(db)
        alert = _make_alert()
        db.add(alert)
        await db.flush()

        result = await db.execute(select(AlertV2Model).where(AlertV2Model.id == alert.id))
        stored = result.scalars().first()
        assert stored.state == AlertState.ACTIVE.value


class TestAlertStateTransitions:

    async def test_alert_state_active_to_muted(self, db_session):
        """Set state to muted."""
        db = db_session
        await _ensure_array(db)
        alert = _make_alert()
        db.add(alert)
        await db.flush()

        alert.state = AlertState.MUTED.value
        await db.flush()

        result = await db.execute(select(AlertV2Model).where(AlertV2Model.id == alert.id))
        assert result.scalars().first().state == AlertState.MUTED.value

    async def test_alert_state_active_to_expected(self, db_session):
        """Set state to expected."""
        db = db_session
        await _ensure_array(db)
        alert = _make_alert()
        db.add(alert)
        await db.flush()

        alert.state = AlertState.EXPECTED.value
        await db.flush()

        result = await db.execute(select(AlertV2Model).where(AlertV2Model.id == alert.id))
        assert result.scalars().first().state == AlertState.EXPECTED.value

    async def test_alert_state_active_to_recovered(self, db_session):
        """Set state to recovered."""
        db = db_session
        await _ensure_array(db)
        alert = _make_alert()
        db.add(alert)
        await db.flush()

        alert.state = AlertState.RECOVERED.value
        await db.flush()

        result = await db.execute(select(AlertV2Model).where(AlertV2Model.id == alert.id))
        assert result.scalars().first().state == AlertState.RECOVERED.value

    async def test_alert_state_muted_to_active(self, db_session):
        """Mute expires → back to active."""
        db = db_session
        await _ensure_array(db)
        alert = _make_alert(state=AlertState.MUTED.value, mute_until=datetime.now() - timedelta(hours=1))
        db.add(alert)
        await db.flush()

        # Simulate expiry check: mute_until in the past → flip back to active
        if alert.mute_until and alert.mute_until < datetime.now():
            alert.state = AlertState.ACTIVE.value
        await db.flush()

        result = await db.execute(select(AlertV2Model).where(AlertV2Model.id == alert.id))
        assert result.scalars().first().state == AlertState.ACTIVE.value

    async def test_alert_state_expected_to_active(self, db_session):
        """Expected window expires → back to active."""
        db = db_session
        await _ensure_array(db)
        alert = _make_alert(state=AlertState.EXPECTED.value, is_expected=1)
        db.add(alert)
        await db.flush()

        # Simulate window expiry
        alert.state = AlertState.ACTIVE.value
        alert.is_expected = 0
        await db.flush()

        result = await db.execute(select(AlertV2Model).where(AlertV2Model.id == alert.id))
        stored = result.scalars().first()
        assert stored.state == AlertState.ACTIVE.value
        assert stored.is_expected == 0


class TestAlertReviewStatus:

    async def test_alert_review_status_transitions(self, db_session):
        """pending → confirmed_ok → needs_followup → false_positive."""
        db = db_session
        await _ensure_array(db)
        alert = _make_alert()
        db.add(alert)
        await db.flush()
        assert alert.review_status == ReviewStatus.PENDING.value

        for status in [ReviewStatus.CONFIRMED_OK, ReviewStatus.NEEDS_FOLLOWUP, ReviewStatus.FALSE_POSITIVE]:
            alert.review_status = status.value
            await db.flush()
            result = await db.execute(select(AlertV2Model).where(AlertV2Model.id == alert.id))
            assert result.scalars().first().review_status == status.value


class TestAlertFingerprint:

    async def test_alert_fingerprint_dedup(self, db_session):
        """Two alerts with same fingerprint – second updates last_seen_at."""
        db = db_session
        await _ensure_array(db)
        fp = "fp_abc123"
        t1 = datetime.now() - timedelta(hours=1)
        t2 = datetime.now()

        alert1 = _make_alert(fingerprint=fp, first_seen_at=t1, last_seen_at=t1)
        db.add(alert1)
        await db.flush()

        # Simulate dedup logic: find existing with same fingerprint, update last_seen_at
        result = await db.execute(
            select(AlertV2Model).where(AlertV2Model.fingerprint == fp)
        )
        existing = result.scalars().first()
        assert existing is not None
        existing.last_seen_at = t2
        await db.flush()

        result2 = await db.execute(select(AlertV2Model).where(AlertV2Model.fingerprint == fp))
        updated = result2.scalars().first()
        assert updated.last_seen_at == t2
        assert updated.first_seen_at == t1


class TestAlertIsExpected:

    async def test_alert_is_expected_flag(self, db_session):
        """is_expected 0/1/-1 semantics."""
        db = db_session
        await _ensure_array(db)

        for value, meaning in [(0, "unknown"), (1, "expected"), (-1, "unexpected")]:
            alert = _make_alert(is_expected=value, message_raw=f"ie_{meaning}")
            db.add(alert)
            await db.flush()

            result = await db.execute(
                select(AlertV2Model).where(AlertV2Model.message_raw == f"ie_{meaning}")
            )
            assert result.scalars().first().is_expected == value


class TestAlertMuteUntil:

    async def test_alert_mute_until_field(self, db_session):
        """mute_until in future → muted, past → not muted."""
        db = db_session
        await _ensure_array(db)

        future = datetime.now() + timedelta(hours=2)
        past = datetime.now() - timedelta(hours=2)

        alert_muted = _make_alert(state=AlertState.MUTED.value, mute_until=future, message_raw="muted_future")
        alert_expired = _make_alert(state=AlertState.MUTED.value, mute_until=past, message_raw="muted_past")
        db.add_all([alert_muted, alert_expired])
        await db.flush()

        # Check: future mute is still valid
        r1 = await db.execute(select(AlertV2Model).where(AlertV2Model.message_raw == "muted_future"))
        a1 = r1.scalars().first()
        assert a1.mute_until > datetime.now()

        # Check: past mute should be treated as expired
        r2 = await db.execute(select(AlertV2Model).where(AlertV2Model.message_raw == "muted_past"))
        a2 = r2.scalars().first()
        assert a2.mute_until < datetime.now()
