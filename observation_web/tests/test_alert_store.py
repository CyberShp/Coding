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
        count = await store.create_alerts_batch(db_session, alerts)
        assert count == 5

    async def test_create_alerts_batch_empty(self, db_session):
        store = AlertStore()
        count = await store.create_alerts_batch(db_session, [])
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
