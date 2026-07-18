"""Tests for backend/core/alert_store.py — AlertStore CRUD and stats."""
import json
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from backend.core.alert_store import AlertStore
from backend.models.alert import AlertCreate, AlertLevel, AlertModel


@pytest.mark.asyncio
class TestAlertStore:
    async def test_create_alert(self, db_session):
        store = AlertStore()
        alert = AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.ERROR, message="test alert",
            details={"key": "val"}, timestamp=datetime.now()
        )
        result = await store.create_alert(db_session, alert)
        assert result.id is not None
        assert result.array_id == "arr-001"

    async def test_create_alerts_batch(self, db_session):
        store = AlertStore()
        alerts = [
            AlertCreate(
                array_id=f"arr-{i:03d}", observer_name="test",
                level=AlertLevel.INFO, message=f"alert {i}",
                details={}, timestamp=datetime.now()
            )
            for i in range(5)
        ]
        count, created = await store.create_alerts_batch(db_session, alerts)
        assert count == 5
        assert len(created) == 5
        assert all(a.id is not None for a in created)

    async def test_create_alerts_batch_persists_duplicates(self, db_session):
        """AlertStore.create_alerts_batch does NOT dedupe — every row is stored.

        Deduplication is an import-layer concern (see TestAlertDeduplication);
        the store layer must faithfully persist each alert it is given, even when
        the alerts are byte-identical.
        """
        store = AlertStore()
        ts = datetime(2024, 1, 15, 10, 0, 0)

        def _dup():
            return AlertCreate(
                array_id="arr-dup", observer_name="cpu_usage",
                level=AlertLevel.WARNING, message="same message",
                details={}, timestamp=ts,
            )

        count, created = await store.create_alerts_batch(
            db_session, [_dup(), _dup(), _dup()]
        )
        assert count == 3
        assert len({a.id for a in created}) == 3  # three distinct rows
        stored = await store.get_alert_count(db_session, array_id="arr-dup")
        assert stored == 3

    async def test_create_alerts_batch_empty(self, db_session):
        store = AlertStore()
        count, _ = await store.create_alerts_batch(db_session, [])
        assert count == 0

    async def test_get_alerts_with_filters(self, db_session):
        store = AlertStore()
        # Create alerts
        for level in [AlertLevel.INFO, AlertLevel.ERROR]:
            await store.create_alert(db_session, AlertCreate(
                array_id="arr-001", observer_name="test",
                level=level, message="test",
                details={}, timestamp=datetime.now()
            ))

        # Filter by level
        errors = await store.get_alerts(db_session, level="error")
        assert all(a.level == "error" for a in errors)

    async def test_get_alerts_pagination(self, db_session):
        store = AlertStore()
        for i in range(10):
            await store.create_alert(db_session, AlertCreate(
                array_id="arr-001", observer_name="test",
                level=AlertLevel.INFO, message=f"alert {i}",
                details={}, timestamp=datetime.now()
            ))

        page1 = await store.get_alerts(db_session, limit=5, offset=0)
        page2 = await store.get_alerts(db_session, limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5

    async def test_get_alerts_time_filter(self, db_session):
        store = AlertStore()
        # Old alert
        await store.create_alert(db_session, AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message="old",
            details={}, timestamp=datetime.now() - timedelta(hours=48)
        ))
        # Recent alert
        await store.create_alert(db_session, AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message="new",
            details={}, timestamp=datetime.now()
        ))

        recent = await store.get_alerts(
            db_session, start_time=datetime.now() - timedelta(hours=24)
        )
        assert len(recent) == 1
        assert recent[0].message == "new"

    async def test_get_alert_count(self, db_session):
        store = AlertStore()
        for i in range(3):
            await store.create_alert(db_session, AlertCreate(
                array_id="arr-001", observer_name="test",
                level=AlertLevel.INFO, message="test",
                details={}, timestamp=datetime.now()
            ))
        count = await store.get_alert_count(db_session)
        assert count == 3

    async def test_get_stats(self, db_session):
        store = AlertStore()
        await store.create_alert(db_session, AlertCreate(
            array_id="arr-001", observer_name="cpu_usage",
            level=AlertLevel.ERROR, message="high cpu",
            details={}, timestamp=datetime.now()
        ))
        stats = await store.get_stats(db_session)
        assert stats.total >= 1
        assert "error" in stats.by_level

    async def test_delete_old_alerts(self, db_session):
        store = AlertStore()
        # Old alert
        await store.create_alert(db_session, AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message="old",
            details={}, timestamp=datetime.now() - timedelta(days=60)
        ))
        deleted = await store.delete_old_alerts(db_session, days=30)
        assert deleted == 1


@pytest.mark.asyncio
class TestAlertDeduplication:
    """Exercise the REAL alert-import dedup interface.

    Deduplication of imported log alerts is performed by
    ``DataLifecycleManager`` using a (timestamp | observer | message) hash.
    These tests run that real hashing logic against rows created through the
    real ``AlertStore`` — no hand-rolled dedup simulation.
    """

    async def test_duplicate_alert_hash_is_detected_against_stored_rows(self, db_session):
        from backend.core.data_lifecycle import DataLifecycleManager

        store = AlertStore()
        lifecycle = DataLifecycleManager()  # SSH not needed for the hashing helpers
        ts = datetime(2024, 1, 15, 10, 0, 0)

        await store.create_alert(db_session, AlertCreate(
            array_id="arr-dedup", observer_name="memory_leak",
            level=AlertLevel.ERROR, message="Memory leak detected",
            details={}, timestamp=ts,
        ))

        existing = await lifecycle._get_existing_hashes(
            db_session, "arr-dedup", ts - timedelta(days=1)
        )

        # A byte-identical alert hashes to a value already present → it would be
        # skipped by import_history (dedup works).
        dup_hash = lifecycle._compute_message_hash(
            ts.isoformat(), "memory_leak", "Memory leak detected"
        )
        assert dup_hash in existing

        # A genuinely different alert is NOT considered a duplicate.
        other_hash = lifecycle._compute_message_hash(
            ts.isoformat(), "memory_leak", "A different message"
        )
        assert other_hash not in existing

    async def test_existing_hashes_scoped_by_array_and_time(self, db_session):
        """Dedup lookup must be scoped to the array and the cutoff window."""
        from backend.core.data_lifecycle import DataLifecycleManager

        store = AlertStore()
        lifecycle = DataLifecycleManager()
        ts = datetime(2024, 1, 15, 10, 0, 0)

        await store.create_alert(db_session, AlertCreate(
            array_id="arr-A", observer_name="cpu_usage",
            level=AlertLevel.WARNING, message="cpu high",
            details={}, timestamp=ts,
        ))

        target_hash = lifecycle._compute_message_hash(ts.isoformat(), "cpu_usage", "cpu high")

        # Different array → not seen.
        other_array = await lifecycle._get_existing_hashes(
            db_session, "arr-B", ts - timedelta(days=1)
        )
        assert target_hash not in other_array

        # Same array but cutoff after the alert → outside window, not seen.
        outside_window = await lifecycle._get_existing_hashes(
            db_session, "arr-A", ts + timedelta(days=1)
        )
        assert target_hash not in outside_window

        # Same array, cutoff before the alert → seen.
        inside_window = await lifecycle._get_existing_hashes(
            db_session, "arr-A", ts - timedelta(days=1)
        )
        assert target_hash in inside_window
