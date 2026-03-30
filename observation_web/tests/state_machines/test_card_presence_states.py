"""
Layer 3 – State Machine Tests for Card Presence models.

Tests card presence state transitions, unique constraints, and history
records using the DB models directly.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.card_presence import (
    CardPresenceCurrentModel,
    CardPresenceHistoryModel,
    CardPresenceStatus,
)
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


def _make_card(array_id="arr1", board_id="B001", **overrides) -> CardPresenceCurrentModel:
    defaults = dict(
        array_id=array_id,
        board_id=board_id,
        card_no="No001",
        model="X100",
        status=CardPresenceStatus.PRESENT.value,
        last_confirmed_at=datetime.now(),
    )
    defaults.update(overrides)
    return CardPresenceCurrentModel(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCardDefaultState:

    async def test_card_default_state_present(self, db_session):
        """New card has status=present."""
        db = db_session
        card = _make_card()
        db.add(card)
        await db.flush()

        result = await db.execute(select(CardPresenceCurrentModel).where(
            CardPresenceCurrentModel.id == card.id
        ))
        assert result.scalars().first().status == CardPresenceStatus.PRESENT.value


class TestCardStateTransitions:

    async def test_card_state_present_to_suspect_missing(self, db_session):
        """After N missed scans → suspect_missing."""
        db = db_session
        card = _make_card()
        db.add(card)
        await db.flush()

        card.status = CardPresenceStatus.SUSPECT_MISSING.value
        await db.flush()

        result = await db.execute(select(CardPresenceCurrentModel).where(
            CardPresenceCurrentModel.id == card.id
        ))
        assert result.scalars().first().status == CardPresenceStatus.SUSPECT_MISSING.value

    async def test_card_state_suspect_missing_to_removed(self, db_session):
        """After grace period → removed."""
        db = db_session
        card = _make_card(status=CardPresenceStatus.SUSPECT_MISSING.value)
        db.add(card)
        await db.flush()

        card.status = CardPresenceStatus.REMOVED.value
        await db.flush()

        result = await db.execute(select(CardPresenceCurrentModel).where(
            CardPresenceCurrentModel.id == card.id
        ))
        assert result.scalars().first().status == CardPresenceStatus.REMOVED.value

    async def test_card_state_removed_to_present(self, db_session):
        """Card re-appears → back to present."""
        db = db_session
        card = _make_card(status=CardPresenceStatus.REMOVED.value)
        db.add(card)
        await db.flush()

        card.status = CardPresenceStatus.PRESENT.value
        card.last_confirmed_at = datetime.now()
        await db.flush()

        result = await db.execute(select(CardPresenceCurrentModel).where(
            CardPresenceCurrentModel.id == card.id
        ))
        stored = result.scalars().first()
        assert stored.status == CardPresenceStatus.PRESENT.value
        assert stored.last_confirmed_at is not None


class TestCardHistory:

    async def test_card_history_written_on_migration(self, db_session):
        """When card moves arrays, history record is written."""
        db = db_session
        now = datetime.now()

        history = CardPresenceHistoryModel(
            board_id="B_MIGRATE",
            array_id="arr_old",
            card_no="No050",
            model="X100",
            seen_at=now - timedelta(days=10),
            removed_at=now,
        )
        db.add(history)
        await db.flush()

        result = await db.execute(
            select(CardPresenceHistoryModel).where(
                CardPresenceHistoryModel.board_id == "B_MIGRATE"
            )
        )
        rec = result.scalars().first()
        assert rec is not None
        assert rec.array_id == "arr_old"
        assert rec.removed_at is not None

    async def test_card_history_records_timestamps(self, db_session):
        """seen_at and removed_at are correctly stored."""
        db = db_session
        seen = datetime(2024, 1, 15, 10, 0, 0)
        removed = datetime(2024, 3, 20, 14, 30, 0)

        history = CardPresenceHistoryModel(
            board_id="BTS1",
            array_id="arr1",
            card_no="No060",
            model="Y200",
            seen_at=seen,
            removed_at=removed,
        )
        db.add(history)
        await db.flush()

        result = await db.execute(
            select(CardPresenceHistoryModel).where(
                CardPresenceHistoryModel.board_id == "BTS1"
            )
        )
        rec = result.scalars().first()
        assert rec.seen_at == seen
        assert rec.removed_at == removed


class TestCardUniqueConstraint:

    async def test_card_unique_constraint(self, db_session):
        """(array_id, board_id) is unique."""
        db = db_session
        card1 = _make_card(array_id="arr_uc", board_id="B_UC1")
        db.add(card1)
        await db.flush()

        card2 = _make_card(array_id="arr_uc", board_id="B_UC1")
        db.add(card2)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
