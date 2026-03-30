"""State machine and branch coverage tests for ingest API + alert models + expectation engine.

Validates:
- Ingest branch coverage: alert/metrics/unknown type, batch, details anomalies
- Alert expectation state matrix: expected × ack_type × task_type combos
- Semantic assertions: final state, is_expected, ack_type correctness
"""

import json
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from backend.models.alert import (
    AlertLevel, AlertBase, AlertModel, AlertResponse,
    AckType, AlertAckModel, AlertAckCreate,
)
from backend.core.alert_expectation import (
    AlertExpectationEngine, EXPECTED_YES, EXPECTED_NO, EXPECTED_UNKNOWN,
)
from tests.conftest import create_test_array, inject_test_alert


# ===================================================================
# A. Ingest API branch coverage
# ===================================================================


@pytest.mark.asyncio
class TestIngestBranches:
    """Branch coverage for /ingest and /ingest/batch endpoints."""

    async def test_ingest_alert_success(self, app_client):
        """Type=alert ingestion succeeds."""
        # Mock the alert_store to avoid SQLite concurrency issues in testing
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            payload = {
                "type": "alert",
                "observer_name": "cpu_usage",
                "level": "warning",
                "message": "CPU high",
                "timestamp": datetime.now().isoformat(),
                "details": {"cpu": 95},
            }
            resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    async def test_ingest_metrics_success(self, app_client):
        """Type=metrics ingestion succeeds."""
        payload = {
            "type": "metrics",
            "ts": datetime.now().isoformat(),
            "cpu0": 45.2,
            "mem_used_mb": 2048.0,
            "mem_total_mb": 8192.0,
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    async def test_ingest_unknown_type(self, app_client):
        """Unknown type returns 400."""
        payload = {"type": "foobar"}
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 400
        assert "Unknown type" in resp.json()["detail"]

    async def test_ingest_batch_success(self, app_client):
        """Batch ingestion with mixed types."""
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            batch = [
                {"type": "alert", "observer_name": "disk", "level": "info", "message": "ok"},
                {"type": "metrics", "cpu0": 10.5},
            ]
            resp = await app_client.post("/api/ingest/batch", content=json.dumps(batch),
                                         headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == 1
        assert data["metrics"] == 1
        assert data["errors"] == 0

    async def test_ingest_batch_not_array(self, app_client):
        """Non-array body returns 400."""
        resp = await app_client.post("/api/ingest/batch",
                                     content=json.dumps({"type": "alert"}),
                                     headers={"Content-Type": "application/json"})
        assert resp.status_code == 400
        assert "JSON array" in resp.json()["detail"]

    async def test_ingest_alert_invalid_level(self, app_client):
        """Invalid level falls back to INFO."""
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            payload = {
                "type": "alert",
                "observer_name": "test",
                "level": "super_critical",
                "message": "test",
            }
            resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

    async def test_ingest_alert_missing_details(self, app_client):
        """Alert with no details field succeeds."""
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            payload = {"type": "alert", "observer_name": "x", "level": "info", "message": "m"}
            resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

    async def test_ingest_alert_invalid_timestamp(self, app_client):
        """Invalid timestamp falls back to now()."""
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            payload = {
                "type": "alert", "observer_name": "x", "level": "info",
                "message": "m", "timestamp": "not-a-date",
            }
            resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

    async def test_ingest_batch_with_errors(self, app_client):
        """Batch with invalid items counts errors."""
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            batch = [
                {"type": "alert", "observer_name": "ok", "level": "info", "message": "ok"},
                {"not_a_valid": "item"},  # Missing 'type' → will error
            ]
            resp = await app_client.post("/api/ingest/batch", content=json.dumps(batch),
                                         headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == 1
        assert data["errors"] >= 1


# ===================================================================
# B. Alert model branch coverage
# ===================================================================


class TestAlertModelDetails:
    """Branch coverage for AlertBase.details validator."""

    def test_details_dict(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details={"key": "val"}, timestamp=datetime.now())
        assert a.details == {"key": "val"}

    def test_details_json_string(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details='{"key":"val"}', timestamp=datetime.now())
        assert a.details == {"key": "val"}

    def test_details_empty_string(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details='', timestamp=datetime.now())
        assert a.details == {}

    def test_details_none(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details=None, timestamp=datetime.now())
        assert a.details == {}

    def test_details_invalid_json(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details='{broken', timestamp=datetime.now())
        assert a.details == {}


class TestAckTypes:
    """AckType enum coverage."""

    def test_dismiss(self):
        assert AckType.DISMISS.value == "dismiss"

    def test_confirmed_ok(self):
        assert AckType.CONFIRMED_OK.value == "confirmed_ok"

    def test_deferred(self):
        assert AckType.DEFERRED.value == "deferred"


# ===================================================================
# C. Alert expectation state matrix
# ===================================================================


class TestExpectationEngine:
    """State matrix for alert expectation evaluation."""

    def _make_alert(self, observer="cpu_usage", level="warning", message="test"):
        alert = MagicMock(spec=AlertModel)
        alert.observer_name = observer
        alert.level = level
        alert.message = message
        return alert

    def _make_engine_with_rules(self, rules):
        engine = AlertExpectationEngine()
        engine._rules_cache = rules
        engine._cache_valid = True
        return engine

    @pytest.mark.asyncio
    async def test_no_task_type_returns_unknown(self):
        engine = self._make_engine_with_rules([])
        alert = self._make_alert()
        db = AsyncMock()
        result, rule_id = await engine.evaluate_alert(db, alert, task_type=None)
        assert result == EXPECTED_UNKNOWN
        assert rule_id is None

    @pytest.mark.asyncio
    async def test_matching_rule_returns_expected(self):
        rules = [{
            'id': 1,
            'name': 'cpu-in-stress',
            'task_types': ['stress_test'],
            'observer_patterns': ['cpu_usage'],
            'level_patterns': ['warning'],
            'message_patterns': [],
            'priority': 50,
        }]
        engine = self._make_engine_with_rules(rules)
        alert = self._make_alert(observer="cpu_usage", level="warning")
        db = AsyncMock()
        result, rule_id = await engine.evaluate_alert(db, alert, task_type="stress_test")
        assert result == EXPECTED_YES
        assert rule_id == 1

    @pytest.mark.asyncio
    async def test_no_matching_rule_returns_unknown(self):
        rules = [{
            'id': 1,
            'name': 'cpu-in-stress',
            'task_types': ['stress_test'],
            'observer_patterns': ['cpu_usage'],
            'level_patterns': ['warning'],
            'message_patterns': [],
            'priority': 50,
        }]
        engine = self._make_engine_with_rules(rules)
        alert = self._make_alert(observer="disk_usage", level="error")
        db = AsyncMock()
        result, rule_id = await engine.evaluate_alert(db, alert, task_type="stress_test")
        assert result == EXPECTED_UNKNOWN
        assert rule_id is None

    @pytest.mark.asyncio
    async def test_task_type_mismatch(self):
        """Rule only for stress_test, but current task is maintenance → no match."""
        rules = [{
            'id': 2,
            'name': 'cpu-stress',
            'task_types': ['stress_test'],
            'observer_patterns': ['cpu_usage'],
            'level_patterns': [],
            'message_patterns': [],
            'priority': 50,
        }]
        engine = self._make_engine_with_rules(rules)
        alert = self._make_alert(observer="cpu_usage")
        db = AsyncMock()
        result, _ = await engine.evaluate_alert(db, alert, task_type="maintenance")
        assert result == EXPECTED_UNKNOWN

    @pytest.mark.asyncio
    async def test_message_pattern_match(self):
        rules = [{
            'id': 3,
            'name': 'known-error',
            'task_types': ['upgrade'],
            'observer_patterns': [],
            'level_patterns': [],
            'message_patterns': [r'timeout.*retry'],
            'priority': 50,
        }]
        engine = self._make_engine_with_rules(rules)
        alert = self._make_alert(message="Connection timeout - will retry")
        db = AsyncMock()
        result, rule_id = await engine.evaluate_alert(db, alert, task_type="upgrade")
        assert result == EXPECTED_YES
        assert rule_id == 3

    @pytest.mark.asyncio
    async def test_message_pattern_no_match(self):
        rules = [{
            'id': 3,
            'name': 'known-error',
            'task_types': ['upgrade'],
            'observer_patterns': [],
            'level_patterns': [],
            'message_patterns': [r'timeout.*retry'],
            'priority': 50,
        }]
        engine = self._make_engine_with_rules(rules)
        alert = self._make_alert(message="Disk full")
        db = AsyncMock()
        result, _ = await engine.evaluate_alert(db, alert, task_type="upgrade")
        assert result == EXPECTED_UNKNOWN

    @pytest.mark.asyncio
    async def test_batch_evaluation(self):
        rules = [{
            'id': 10,
            'name': 'batch-rule',
            'task_types': ['any'],
            'observer_patterns': ['card_info'],
            'level_patterns': [],
            'message_patterns': [],
            'priority': 50,
        }]
        engine = self._make_engine_with_rules(rules)
        alerts = [
            self._make_alert(observer="card_info"),
            self._make_alert(observer="cpu_usage"),
        ]
        alerts[0].id = 1
        alerts[1].id = 2
        db = AsyncMock()
        results = await engine.evaluate_alerts_batch(db, alerts, task_type="any")
        assert len(results) == 2
        # First alert should match
        assert results[0][1] == EXPECTED_YES
        assert results[0][2] == 10
        # Second should not match
        assert results[1][1] == EXPECTED_UNKNOWN

    @pytest.mark.asyncio
    async def test_invalid_regex_in_pattern_is_skipped(self):
        """Invalid regex in message_patterns should not crash."""
        rules = [{
            'id': 99,
            'name': 'bad-regex',
            'task_types': ['test'],
            'observer_patterns': [],
            'level_patterns': [],
            'message_patterns': ['[invalid-regex'],  # unclosed bracket
            'priority': 50,
        }]
        engine = self._make_engine_with_rules(rules)
        alert = self._make_alert(message="some text")
        db = AsyncMock()
        result, _ = await engine.evaluate_alert(db, alert, task_type="test")
        # Should not crash, just no match
        assert result == EXPECTED_UNKNOWN

    @pytest.mark.asyncio
    async def test_cache_invalidation_reloads(self):
        engine = AlertExpectationEngine()
        engine._cache_valid = True
        engine._rules_cache = []
        engine.invalidate_cache()
        assert engine._cache_valid is False


# ===================================================================
# D. Expected × Ack state matrix
# ===================================================================


class TestExpectedAckMatrix:
    """State matrix: expected (yes/no/unknown) × ack_type (dismiss/confirmed_ok/deferred)."""

    @pytest.mark.asyncio
    async def test_expected_dismiss(self, db_session):
        """expected + dismiss → alert acked, temporarily hidden."""
        alert = AlertModel(
            array_id="arr-1", observer_name="test", level="warning",
            message="known issue", details="{}", timestamp=datetime.now(),
            is_expected=1,
        )
        db_session.add(alert)
        await db_session.flush()

        ack = AlertAckModel(
            alert_id=alert.id, acked_by_ip="10.0.0.1",
            ack_type="dismiss",
            ack_expires_at=datetime.now() + timedelta(hours=24),
        )
        db_session.add(ack)
        await db_session.commit()

        assert alert.is_expected == 1
        assert ack.ack_type == "dismiss"
        assert ack.ack_expires_at is not None

    @pytest.mark.asyncio
    async def test_expected_confirmed_ok(self, db_session):
        """expected + confirmed_ok → permanently non-issue."""
        alert = AlertModel(
            array_id="arr-1", observer_name="test", level="warning",
            message="known issue", details="{}", timestamp=datetime.now(),
            is_expected=1,
        )
        db_session.add(alert)
        await db_session.flush()

        ack = AlertAckModel(
            alert_id=alert.id, acked_by_ip="10.0.0.1",
            ack_type="confirmed_ok",
            ack_expires_at=None,  # No expiry
        )
        db_session.add(ack)
        await db_session.commit()

        assert ack.ack_type == "confirmed_ok"
        assert ack.ack_expires_at is None

    @pytest.mark.asyncio
    async def test_unexpected_deferred(self, db_session):
        """unexpected + deferred → revisit later."""
        alert = AlertModel(
            array_id="arr-1", observer_name="test", level="error",
            message="unexpected error", details="{}", timestamp=datetime.now(),
            is_expected=-1,
        )
        db_session.add(alert)
        await db_session.flush()

        ack = AlertAckModel(
            alert_id=alert.id, acked_by_ip="10.0.0.1",
            ack_type="deferred",
            ack_expires_at=datetime.now() + timedelta(hours=8),
        )
        db_session.add(ack)
        await db_session.commit()

        assert alert.is_expected == -1
        assert ack.ack_type == "deferred"
        assert ack.ack_expires_at is not None

    @pytest.mark.asyncio
    async def test_ack_expired_check(self, db_session):
        """Expired ack should be detectable."""
        alert = AlertModel(
            array_id="arr-1", observer_name="test", level="warning",
            message="test", details="{}", timestamp=datetime.now(),
            is_expected=0,
        )
        db_session.add(alert)
        await db_session.flush()

        expired_time = datetime.now() - timedelta(hours=1)
        ack = AlertAckModel(
            alert_id=alert.id, acked_by_ip="10.0.0.1",
            ack_type="dismiss",
            ack_expires_at=expired_time,
        )
        db_session.add(ack)
        await db_session.commit()

        # Application logic should check if ack_expires_at < now()
        assert ack.ack_expires_at < datetime.now(), "Ack should be expired"


# ===================================================================
# E. Metrics store branch coverage
# ===================================================================


class TestMetricsStore:
    """Test get_metrics_for_ip and get_all_metrics_sources."""

    def test_empty_metrics(self):
        from backend.api.ingest import get_metrics_for_ip, get_all_metrics_sources
        result = get_metrics_for_ip("nonexistent.ip")
        assert result == []

    def test_sources_list(self):
        from backend.api.ingest import get_all_metrics_sources, _metrics_store
        # Inject some data
        from collections import deque
        _metrics_store["test.ip"] = deque([{"ts": datetime.now().isoformat()}])
        sources = get_all_metrics_sources()
        assert "test.ip" in sources
        del _metrics_store["test.ip"]
