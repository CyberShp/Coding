"""Tests for backend/models — Pydantic models and SQLAlchemy models."""
import json
import pytest
from datetime import datetime
from backend.models.alert import AlertLevel, AlertBase, AlertModel, AlertResponse, AlertStats
from backend.models.array import ArrayModel, ArrayCreate, ArrayUpdate, ArrayStatus, ConnectionState
from backend.models.query import RuleType, QueryStatus


# ---------- AlertLevel ----------

class TestAlertLevel:
    def test_values(self):
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.ERROR.value == "error"
        assert AlertLevel.CRITICAL.value == "critical"


# ---------- AlertBase (details validator) ----------

class TestAlertBase:
    def test_details_from_dict(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details={"k": "v"}, timestamp=datetime.now())
        assert a.details == {"k": "v"}

    def test_details_from_json_string(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details='{"k": "v"}', timestamp=datetime.now())
        assert a.details == {"k": "v"}

    def test_details_from_invalid_json_string(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details='{invalid}', timestamp=datetime.now())
        assert a.details == {}

    def test_details_none(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details=None, timestamp=datetime.now())
        assert a.details == {}

    def test_details_empty_string(self):
        a = AlertBase(observer_name="t", level=AlertLevel.INFO,
                      message="m", details='', timestamp=datetime.now())
        assert a.details == {}


# ---------- AlertModel ----------

class TestAlertModel:
    def test_create_model(self):
        m = AlertModel(
            array_id="arr-001", observer_name="test",
            level="error", message="test msg",
            details=json.dumps({"k": "v"}),
            timestamp=datetime.now()
        )
        assert m.array_id == "arr-001"
        assert m.level == "error"


# ---------- AlertStats ----------

class TestAlertStats:
    def test_default_values(self):
        s = AlertStats(total=10, by_level={"info": 5, "error": 5},
                       by_observer={}, by_array={}, trend_24h=[])
        assert s.total == 10


# ---------- ArrayModels ----------

class TestArrayModels:
    def test_create_array(self):
        a = ArrayCreate(name="Test", host="192.168.1.1", port=22, username="admin")
        assert a.port == 22

    def test_update_array(self):
        u = ArrayUpdate(name="Updated")
        assert u.name == "Updated"
        assert u.host is None

    def test_connection_state(self):
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.DISCONNECTED.value == "disconnected"

    def test_array_status_defaults(self):
        s = ArrayStatus(array_id="arr-001", name="Test", host="1.2.3.4")
        assert s.state == "disconnected"
        assert s.agent_deployed is False
        assert s.agent_running is False


# ---------- QueryModels ----------

class TestQueryModels:
    def test_rule_types(self):
        assert RuleType.VALID_MATCH.value == "valid_match"
        assert RuleType.INVALID_MATCH.value == "invalid_match"
        assert RuleType.REGEX_EXTRACT.value == "regex_extract"

    def test_query_status(self):
        assert QueryStatus.OK.value == "ok"
        assert QueryStatus.ERROR.value == "error"
        assert QueryStatus.TIMEOUT.value == "timeout"
