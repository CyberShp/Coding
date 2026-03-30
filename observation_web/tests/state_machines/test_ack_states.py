"""
Layer 3 – State Machine Tests for Alert Acknowledgement.

Tests ack state transitions and field semantics using the DB model directly.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.models.alert import AlertModel, AlertAckModel, AckType
from backend.models.array import ArrayModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_array(db, array_id="arr1"):
    from sqlalchemy import select as _sel
    result = await db.execute(_sel(ArrayModel).where(ArrayModel.array_id == array_id))
    if result.scalars().first() is None:
        db.add(ArrayModel(
            array_id=array_id, name=array_id,
            host=f"10.0.0.{hash(array_id) % 254 + 1}",
            port=22, username="root", key_path="", folder="",
        ))
        await db.flush()


async def _seed_alert(db, array_id="arr1"):
    """Create a parent alert for ack records."""
    a = AlertModel(
        array_id=array_id,
        observer_name="ack_test",
        level="warning",
        message="test alert for ack",
        details="{}",
        timestamp=datetime.now(),
    )
    db.add(a)
    await db.flush()
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAckDismissDefault:

    async def test_ack_dismiss_default(self, db_session):
        """Default ack_type is dismiss."""
        db = db_session
        await _ensure_array(db)
        alert = await _seed_alert(db)

        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="127.0.0.1",
        )
        db.add(ack)
        await db.flush()

        result = await db.execute(select(AlertAckModel).where(AlertAckModel.id == ack.id))
        stored = result.scalars().first()
        assert stored.ack_type == AckType.DISMISS.value


class TestAckConfirmedOk:

    async def test_ack_confirmed_ok(self, db_session):
        """Can set confirmed_ok."""
        db = db_session
        await _ensure_array(db)
        alert = await _seed_alert(db)

        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="10.0.0.1",
            ack_type=AckType.CONFIRMED_OK.value,
            comment="Verified, not an issue",
        )
        db.add(ack)
        await db.flush()

        result = await db.execute(select(AlertAckModel).where(AlertAckModel.id == ack.id))
        stored = result.scalars().first()
        assert stored.ack_type == AckType.CONFIRMED_OK.value
        assert stored.ack_expires_at is None  # confirmed_ok has no expiry


class TestAckDeferred:

    async def test_ack_deferred_with_expiry(self, db_session):
        """Deferred has ack_expires_at."""
        db = db_session
        await _ensure_array(db)
        alert = await _seed_alert(db)

        expires = datetime.now() + timedelta(hours=4)
        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="10.0.0.2",
            ack_type=AckType.DEFERRED.value,
            ack_expires_at=expires,
            comment="Will revisit later",
        )
        db.add(ack)
        await db.flush()

        result = await db.execute(select(AlertAckModel).where(AlertAckModel.id == ack.id))
        stored = result.scalars().first()
        assert stored.ack_type == AckType.DEFERRED.value
        assert stored.ack_expires_at is not None
        assert stored.ack_expires_at > datetime.now()


class TestAckDismissExpires:

    async def test_ack_dismiss_expires(self, db_session):
        """Dismiss with hours → has expiry."""
        db = db_session
        await _ensure_array(db)
        alert = await _seed_alert(db)

        expires = datetime.now() + timedelta(hours=24)
        ack = AlertAckModel(
            alert_id=alert.id,
            acked_by_ip="10.0.0.3",
            ack_type=AckType.DISMISS.value,
            ack_expires_at=expires,
        )
        db.add(ack)
        await db.flush()

        result = await db.execute(select(AlertAckModel).where(AlertAckModel.id == ack.id))
        stored = result.scalars().first()
        assert stored.ack_type == AckType.DISMISS.value
        assert stored.ack_expires_at is not None


class TestAckTypesEnum:

    async def test_ack_types_enum(self, db_session):
        """All AckType values are valid and can be stored."""
        db = db_session
        await _ensure_array(db)

        for ack_type in AckType:
            alert = await _seed_alert(db)
            ack = AlertAckModel(
                alert_id=alert.id,
                acked_by_ip="10.0.0.99",
                ack_type=ack_type.value,
            )
            db.add(ack)
            await db.flush()

            result = await db.execute(select(AlertAckModel).where(AlertAckModel.id == ack.id))
            stored = result.scalars().first()
            assert stored.ack_type == ack_type.value
