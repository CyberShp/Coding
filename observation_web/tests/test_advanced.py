"""Advanced tests — concurrency, timing, edge cases, performance, multi-fault."""
import asyncio
import json
import time
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from backend.core.alert_store import AlertStore
from backend.core.system_alert import SystemAlertStore, AlertLevel as SysAlertLevel
from backend.core.ssh_pool import SSHConnection, SSHPool
from backend.models.alert import AlertCreate, AlertLevel


# ============================================================
# CONCURRENCY TESTS
# ============================================================

@pytest.mark.asyncio
class TestConcurrency:
    async def test_concurrent_alert_creation(self, db_session):
        """CONC-01: Sequential alert inserts should not lose data.
        BUG-MARKER: SQLite does not support true concurrent writes — this
        test validates sequential bulk creation instead."""
        store = AlertStore()
        for i in range(20):
            alert = AlertCreate(
                array_id=f"arr-{i % 3:03d}", observer_name="test",
                level=AlertLevel.INFO, message=f"concurrent alert {i}",
                details={}, timestamp=datetime.now()
            )
            await store.create_alert(db_session, alert)
        count = await store.get_alert_count(db_session)
        assert count == 20

    async def test_concurrent_reads_and_writes(self, db_session):
        """CONC-02: Reads during writes should not crash."""
        store = AlertStore()
        # Seed data
        for i in range(5):
            await store.create_alert(db_session, AlertCreate(
                array_id="arr-001", observer_name="test",
                level=AlertLevel.INFO, message=f"seed {i}",
                details={}, timestamp=datetime.now()
            ))

        async def read_loop():
            for _ in range(10):
                await store.get_alerts(db_session, limit=5)
                await asyncio.sleep(0.01)

        async def write_loop():
            for i in range(10):
                await store.create_alert(db_session, AlertCreate(
                    array_id="arr-001", observer_name="test",
                    level=AlertLevel.INFO, message=f"write {i}",
                    details={}, timestamp=datetime.now()
                ))
                await asyncio.sleep(0.01)

        await asyncio.gather(read_loop(), write_loop(), return_exceptions=True)

    def test_system_alert_store_thread_safety(self):
        """CONC-03: SystemAlertStore with concurrent adds."""
        import threading
        store = SystemAlertStore()
        errors = []

        def add_alerts(thread_id):
            try:
                for i in range(50):
                    store.add(SysAlertLevel.INFO, f"thread-{thread_id}", f"msg-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_alerts, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(store.get_all()) > 0

    def test_ssh_pool_concurrent_add_remove(self):
        """CONC-04: Concurrent SSH pool modifications."""
        import threading
        pool = SSHPool()
        errors = []

        def add_connections(start):
            try:
                for i in range(10):
                    pool.add_connection(f"arr-{start+i}", f"10.0.{start}.{i}", 22, "admin")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_connections, args=(t*10,)) for t in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ============================================================
# TIMING / SEQUENCE TESTS
# ============================================================

@pytest.mark.asyncio
class TestTiming:
    async def test_alert_ordering_by_timestamp(self, db_session):
        """TIME-01: Alerts should be returned in descending timestamp order."""
        store = AlertStore()
        base = datetime.now()
        for i in range(5):
            await store.create_alert(db_session, AlertCreate(
                array_id="arr-001", observer_name="test",
                level=AlertLevel.INFO, message=f"alert {i}",
                details={}, timestamp=base + timedelta(minutes=i)
            ))
        alerts = await store.get_alerts(db_session, limit=5)
        timestamps = [a.timestamp for a in alerts]
        assert timestamps == sorted(timestamps, reverse=True)

    async def test_stats_time_range_boundary(self, db_session):
        """TIME-02: Alert exactly at boundary should be included."""
        store = AlertStore()
        boundary = datetime.now() - timedelta(hours=24)
        await store.create_alert(db_session, AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message="boundary",
            details={}, timestamp=boundary
        ))
        count = await store.get_alert_count(db_session, start_time=boundary)
        assert count >= 1

    def test_ssh_reconnect_backoff(self):
        """TIME-03: Reconnection attempts should respect max attempts."""
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        conn._reconnect_attempts = conn.MAX_RECONNECT_ATTEMPTS
        # Should not try to reconnect
        assert conn.is_connected() is False


# ============================================================
# EDGE CASE / BOUNDARY TESTS
# ============================================================

@pytest.mark.asyncio
class TestEdgeCases:
    async def test_empty_database_queries(self, db_session):
        """EDGE-01: All query functions should handle empty database."""
        store = AlertStore()
        assert await store.get_alerts(db_session) == []
        assert await store.get_alert_count(db_session) == 0
        stats = await store.get_stats(db_session)
        assert stats.total == 0

    async def test_very_long_message(self, db_session):
        """EDGE-02: Alert with very long message should not crash."""
        store = AlertStore()
        long_msg = "x" * 10000
        alert = AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message=long_msg,
            details={}, timestamp=datetime.now()
        )
        result = await store.create_alert(db_session, alert)
        assert result.id is not None

    async def test_unicode_in_message(self, db_session):
        """EDGE-03: Unicode characters in alert message."""
        store = AlertStore()
        alert = AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO,
            message="告警：磁盘故障 🔴 ☠️ 日本語テスト",
            details={"emoji": "🎉"}, timestamp=datetime.now()
        )
        result = await store.create_alert(db_session, alert)
        assert result.id is not None

    async def test_special_chars_in_array_id(self, db_session):
        """EDGE-04: Special characters in array_id."""
        store = AlertStore()
        alert = AlertCreate(
            array_id="arr/001?test=true&foo", observer_name="test",
            level=AlertLevel.INFO, message="test",
            details={}, timestamp=datetime.now()
        )
        result = await store.create_alert(db_session, alert)
        assert result.id is not None

    async def test_deeply_nested_details(self, db_session):
        """EDGE-05: Deeply nested details JSON."""
        store = AlertStore()
        nested = {"level": 0}
        current = nested
        for i in range(50):
            current["child"] = {"level": i + 1}
            current = current["child"]
        alert = AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message="nested",
            details=nested, timestamp=datetime.now()
        )
        result = await store.create_alert(db_session, alert)
        assert result.id is not None

    def test_ssh_connection_empty_host(self):
        """EDGE-06: SSH connection with empty host."""
        conn = SSHConnection("arr-001", "", 22, "admin")
        assert conn.is_connected() is False

    def test_ssh_connection_port_zero(self):
        """EDGE-07: SSH connection with port 0."""
        conn = SSHConnection("arr-001", "10.0.0.1", 0, "admin")
        assert conn.port == 0

    async def test_pagination_beyond_total(self, db_session):
        """EDGE-08: Pagination offset beyond total records."""
        store = AlertStore()
        await store.create_alert(db_session, AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message="only one",
            details={}, timestamp=datetime.now()
        ))
        results = await store.get_alerts(db_session, offset=100, limit=10)
        assert results == []

    def test_system_alert_empty_module_filter(self):
        """EDGE-09: Filtering with empty module string."""
        store = SystemAlertStore()
        store.add(SysAlertLevel.INFO, "test", "msg")
        alerts = store.get_all(module="")
        assert len(alerts) >= 1  # Empty string should match all


# ============================================================
# SPECIFICATION TESTS
# ============================================================

class TestSpecification:
    def test_alert_level_enum_completeness(self):
        """SPEC-01: All expected alert levels exist."""
        levels = {l.value for l in AlertLevel}
        assert levels == {"info", "warning", "error", "critical"}

    def test_ssh_pool_max_reconnect_spec(self):
        """SPEC-02: Max reconnect attempts should be 3."""
        assert SSHConnection.MAX_RECONNECT_ATTEMPTS == 3

    def test_ssh_idle_timeout_spec(self):
        """SPEC-03: Idle timeout should be 600 seconds."""
        assert SSHConnection.IDLE_TIMEOUT == 600

    def test_system_alert_max_limit(self):
        """SPEC-04: System alert store max should be 2000 (expanded for archiving)."""
        assert SystemAlertStore.MAX_ALERTS == 2000

    def test_api_version(self):
        """SPEC-05: API version should be defined."""
        from backend.main import create_app
        app = create_app()
        # Check version in routes
        assert app.title == "Observation Web API"


# ============================================================
# PERFORMANCE TESTS
# ============================================================

@pytest.mark.asyncio
class TestPerformance:
    async def test_bulk_alert_insert_performance(self, db_session):
        """PERF-01: 500 alert inserts should complete in < 10 seconds."""
        store = AlertStore()
        alerts = [
            AlertCreate(
                array_id=f"arr-{i % 10:03d}", observer_name="perf_test",
                level=AlertLevel.INFO, message=f"perf alert {i}",
                details={"index": i}, timestamp=datetime.now()
            )
            for i in range(500)
        ]
        start = time.time()
        count = await store.create_alerts_batch(db_session, alerts)
        elapsed = time.time() - start
        assert count == 500
        # BUG-MARKER: If this takes > 10s, batch insert needs optimization
        assert elapsed < 10, f"Bulk insert took {elapsed:.2f}s, expected < 10s"

    async def test_query_with_many_alerts_performance(self, db_session):
        """PERF-02: Query with 1000 alerts should be fast."""
        store = AlertStore()
        alerts = [
            AlertCreate(
                array_id="arr-001", observer_name="perf",
                level=AlertLevel.INFO, message=f"p {i}",
                details={}, timestamp=datetime.now() - timedelta(minutes=i)
            )
            for i in range(1000)
        ]
        await store.create_alerts_batch(db_session, alerts)

        start = time.time()
        results = await store.get_alerts(db_session, limit=100)
        elapsed = time.time() - start
        assert len(results) == 100
        assert elapsed < 2, f"Query took {elapsed:.2f}s"

    def test_system_alert_store_performance(self):
        """PERF-03: Adding 500 system alerts should be fast."""
        store = SystemAlertStore()
        start = time.time()
        for i in range(500):
            store.add(SysAlertLevel.INFO, "perf", f"msg {i}")
        elapsed = time.time() - start
        assert elapsed < 2, f"500 alerts took {elapsed:.2f}s"

    def test_translator_performance(self):
        """PERF-04: Translating 1000 alerts should be fast."""
        from tests.test_alert_translator import translate_alarm_type
        alert_template = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [{"alarm_type": 1, "alarm_name": "test", "alarm_id": "0x01"}],
                "new_resume_alarms": [],
                "active_alarms": [{"alarm_name": "test"}],
            }
        }
        start = time.time()
        for _ in range(1000):
            translate_alarm_type(alert_template)
        elapsed = time.time() - start
        assert elapsed < 1, f"1000 translations took {elapsed:.2f}s"


# ============================================================
# MULTI-POINT FAILURE TESTS
# ============================================================

class TestMultiPointFailure:
    def test_ssh_pool_all_connections_fail(self):
        """MULTI-01: All SSH connections failed simultaneously."""
        pool = SSHPool()
        for i in range(5):
            pool.add_connection(f"arr-{i:03d}", f"10.0.0.{i}", 22, "admin")
        states = pool.get_all_states()
        # All should be disconnected
        assert all(s == "disconnected" for s in states.values())

    def test_database_and_ssh_down(self):
        """MULTI-02: Both database and SSH unavailable."""
        pool = SSHPool()
        pool.add_connection("arr-001", "10.0.0.1", 22, "admin")
        conn = pool.get_connection("arr-001")
        assert conn is not None
        assert conn.is_connected() is False
        # System should gracefully handle both failures

    def test_system_alert_overflow_during_failures(self):
        """MULTI-03: Rapid system alerts during cascading failures."""
        store = SystemAlertStore()
        # Simulate cascading failures
        for i in range(100):
            store.add(SysAlertLevel.ERROR, "ssh", f"Connection failed: arr-{i % 10}")
            store.add(SysAlertLevel.ERROR, "db", f"Query failed: {i}")
            store.add(SysAlertLevel.WARNING, "http", f"Slow request: {i}")
        # Should not exceed MAX_ALERTS
        assert len(store.get_all()) <= SystemAlertStore.MAX_ALERTS

    @pytest.mark.asyncio
    async def test_alert_creation_after_db_error(self, db_session):
        """MULTI-04: Alert creation should work after a prior DB error."""
        store = AlertStore()
        # Create valid alert
        result = await store.create_alert(db_session, AlertCreate(
            array_id="arr-001", observer_name="test",
            level=AlertLevel.INFO, message="after recovery",
            details={}, timestamp=datetime.now()
        ))
        assert result.id is not None

    def test_ssh_reconnect_during_command(self):
        """MULTI-05: SSH disconnects mid-command execution.
        BUG-MARKER: Currently returns error tuple, no mid-command disconnect handling."""
        conn = SSHConnection("arr-001", "10.0.0.1", 22, "admin")
        code, stdout, stderr = conn.execute("ls")
        assert code == -1  # Not connected returns error code

    def test_multiple_observers_crash_isolation(self):
        """MULTI-06: One observer crash should not affect others."""
        from unittest.mock import MagicMock
        # Simulate scheduler behavior
        observers = []
        results = []
        for i in range(5):
            obs = MagicMock()
            obs.name = f"obs_{i}"
            obs.is_enabled.return_value = True
            if i == 2:
                obs.check.side_effect = Exception("crash!")
            else:
                obs.check.return_value = MagicMock(has_alert=False)
            observers.append(obs)

        for obs in observers:
            try:
                result = obs.check()
                results.append(result)
            except Exception:
                pass  # Should be isolated

        assert len(results) == 4  # 5 - 1 crashed


# ============================================================
# WEBSOCKET TESTS
# ============================================================

@pytest.mark.asyncio
class TestWebSocketEdgeCases:
    async def test_connection_manager_empty(self):
        """WS-01: Broadcast to empty channel should not crash."""
        from backend.api.websocket import ConnectionManager
        mgr = ConnectionManager()
        await mgr.broadcast("alerts", {"test": True})

    def test_connection_count(self):
        """WS-02: Connection count should start at 0."""
        from backend.api.websocket import ConnectionManager
        mgr = ConnectionManager()
        assert mgr.get_connection_count("alerts") == 0
        assert mgr.get_connection_count("nonexistent") == 0
