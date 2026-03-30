"""Schema creation and migration compatibility tests.

Validates that ALL database models can be created, have correct structure,
and that old data patterns are compatible with the new schema.
"""

import pytest
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.db.database import Base

# Import every model module so Base.metadata is fully populated
from backend.models.array import ArrayModel, EnrollmentStatus, ConnectionMode
from backend.models.alert import AlertModel
from backend.models.alerts_v2 import AlertV2Model, AlertCategory, AlertState, ReviewStatus
from backend.models.tag import TagModel, ArrayTagModel, TagType
from backend.models.card_presence import (
    CardPresenceCurrentModel,
    CardPresenceHistoryModel,
    CardPresenceStatus,
)
from backend.models.viewer_profile import (
    ViewerProfileModel,
    ViewerFollowTagModel,
    ViewerFollowArrayModel,
    ViewerPreferenceModel,
    ViewerSavedViewModel,
)
from backend.models.enrollment import (
    ArrayImportJobModel,
    ArrayEnrollmentJobModel,
    AgentRegistrationModel,
)
from backend.models.system_config import SystemConfigModel, SchemaVersionModel
from backend.models.observer_snapshot import ObserverSnapshotModel
from backend.models.agent_heartbeat import AgentHeartbeatModel
from backend.models.expected_window import ExpectedWindowModel

# Ensure remaining models are also registered with Base.metadata
from backend.models import (  # noqa: F401
    alert_rule, audit_log, issue, monitor_template, observer_config,
    ai_interpretation, card_inventory, array_lock, lifecycle, scheduler,
    traffic, task_session, snapshot, user_session, user_preference, query,
)

# Complete set of tables that must exist after create_all
ALL_EXPECTED_TABLES = sorted([
    "agent_heartbeats", "agent_registrations", "ai_interpretations",
    "alert_acknowledgements", "alert_expectation_rules", "alerts",
    "alerts_archive", "alerts_v2", "archive_config",
    "array_enrollment_jobs", "array_import_jobs", "array_locks",
    "array_tags", "arrays", "audit_logs", "card_inventory",
    "card_presence_current", "card_presence_history", "expected_windows",
    "issues", "monitor_templates", "observer_configs", "observer_snapshots",
    "port_traffic", "query_templates", "scheduled_tasks", "schema_version",
    "snapshots", "sync_state", "system_config", "tags", "task_results",
    "task_sessions", "user_preferences", "user_sessions",
    "viewer_follow_arrays", "viewer_follow_tags", "viewer_preferences",
    "viewer_profiles", "viewer_saved_views",
])


# ---------------------------------------------------------------------------
# A. Table creation verification
# ---------------------------------------------------------------------------

class TestTableCreation:
    """Verify every expected table is created by Base.metadata.create_all."""

    async def test_all_tables_created(self, db_session: AsyncSession):
        result = await db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        tables = sorted(row[0] for row in result.fetchall())
        for expected in ALL_EXPECTED_TABLES:
            assert expected in tables, f"Table '{expected}' not found in database"

    async def test_alerts_v2_table_columns(self, db_session: AsyncSession):
        required = {
            "id", "array_id", "category", "object_type", "object_key",
            "symptom_code", "message_raw", "message_cn", "evidence_json",
            "occurred_at", "ingested_at", "first_seen_at", "last_seen_at",
            "fingerprint", "state", "review_status", "is_expected",
            "expected_window_id", "mute_until", "observer_name", "level",
            "task_id", "created_at",
        }
        cols = await _get_column_names(db_session, "alerts_v2")
        for col in required:
            assert col in cols, f"Column '{col}' missing from alerts_v2"

    async def test_array_tags_table_exists(self, db_session: AsyncSession):
        tables = await _get_table_names(db_session)
        assert "array_tags" in tables

    async def test_card_presence_tables_exist(self, db_session: AsyncSession):
        tables = await _get_table_names(db_session)
        assert "card_presence_current" in tables
        assert "card_presence_history" in tables

    async def test_viewer_profile_tables_exist(self, db_session: AsyncSession):
        expected = [
            "viewer_profiles", "viewer_preferences",
            "viewer_follow_tags", "viewer_follow_arrays", "viewer_saved_views",
        ]
        tables = await _get_table_names(db_session)
        for t in expected:
            assert t in tables, f"Table '{t}' not found"

    async def test_enrollment_tables_exist(self, db_session: AsyncSession):
        expected = [
            "array_import_jobs", "array_enrollment_jobs", "agent_registrations",
        ]
        tables = await _get_table_names(db_session)
        for t in expected:
            assert t in tables, f"Table '{t}' not found"

    async def test_system_config_tables_exist(self, db_session: AsyncSession):
        tables = await _get_table_names(db_session)
        assert "system_config" in tables
        assert "schema_version" in tables

    async def test_observer_snapshots_table_exists(self, db_session: AsyncSession):
        tables = await _get_table_names(db_session)
        assert "observer_snapshots" in tables

    async def test_agent_heartbeats_table_exists(self, db_session: AsyncSession):
        tables = await _get_table_names(db_session)
        assert "agent_heartbeats" in tables

    async def test_expected_windows_table_exists(self, db_session: AsyncSession):
        tables = await _get_table_names(db_session)
        assert "expected_windows" in tables


# ---------------------------------------------------------------------------
# B. Default values and backward compatibility
# ---------------------------------------------------------------------------

class TestDefaultValues:
    """Ensure new fields have sensible defaults so old code paths still work."""

    async def test_array_new_fields_have_defaults(self, db_session: AsyncSession):
        arr = ArrayModel(
            array_id="def-001", name="default-test",
            host="10.0.0.1", port=22, username="root", key_path="",
        )
        db_session.add(arr)
        await db_session.flush()
        assert arr.enrollment_status == "draft"
        assert arr.connection_mode == "ssh_only"

    async def test_array_old_fields_still_work(self, db_session: AsyncSession):
        arr = ArrayModel(
            array_id="old-001", name="legacy",
            host="10.0.0.2", port=22, username="admin", key_path="/keys/id",
        )
        db_session.add(arr)
        await db_session.flush()
        assert arr.name == "legacy"
        assert arr.host == "10.0.0.2"
        assert arr.port == 22
        assert arr.username == "admin"
        assert arr.key_path == "/keys/id"

    async def test_tag_type_defaults_to_general(self, db_session: AsyncSession):
        tag = TagModel(name="auto-default-tag")
        db_session.add(tag)
        await db_session.flush()
        assert tag.tag_type == "general"

    async def test_alert_v2_state_defaults(self, db_session: AsyncSession):
        alert = AlertV2Model(
            array_id="def-002", category="generic_error",
            message_raw="test",
            occurred_at=datetime.now(), observer_name="obs",
        )
        db_session.add(alert)
        await db_session.flush()
        assert alert.state == "active"
        assert alert.review_status == "pending"

    async def test_card_presence_status_defaults(self, db_session: AsyncSession):
        card = CardPresenceCurrentModel(
            array_id="def-003", board_id="board-1",
        )
        db_session.add(card)
        await db_session.flush()
        assert card.status == "present"


# ---------------------------------------------------------------------------
# C. Old data → new schema compatibility
# ---------------------------------------------------------------------------

class TestOldDataCompatibility:
    """Insert rows with only legacy fields and verify the new model can read them."""

    async def test_old_array_data_readable(self, db_session: AsyncSession):
        # Simulate legacy INSERT with the minimum required columns
        await db_session.execute(text(
            "INSERT INTO arrays (array_id, name, host, port, username, key_path, version) "
            "VALUES ('legacy-arr', 'Legacy', '192.168.1.1', 22, 'root', '', 1)"
        ))
        await db_session.flush()

        result = await db_session.execute(
            text("SELECT * FROM arrays WHERE array_id = 'legacy-arr'")
        )
        row = result.mappings().fetchone()
        assert row is not None
        assert row["name"] == "Legacy"
        # New columns should have their Python-level defaults via ORM;
        # raw SQL gets the server_default or NULL for Python-only defaults
        assert row["enrollment_status"] in ("draft", None)
        assert row["connection_mode"] in ("ssh_only", None)

    async def test_old_alert_data_readable(self, db_session: AsyncSession):
        await db_session.execute(text(
            "INSERT INTO alerts (array_id, observer_name, level, message, details, timestamp) "
            "VALUES ('legacy-arr', 'obs1', 'warning', 'old alert', '{}', "
            "datetime('now'))"
        ))
        await db_session.flush()

        result = await db_session.execute(
            text("SELECT * FROM alerts WHERE array_id = 'legacy-arr'")
        )
        row = result.mappings().fetchone()
        assert row is not None
        assert row["message"] == "old alert"

    async def test_old_tag_data_readable(self, db_session: AsyncSession):
        await db_session.execute(text(
            "INSERT INTO tags (name) VALUES ('legacy-tag')"
        ))
        await db_session.flush()

        result = await db_session.execute(
            text("SELECT * FROM tags WHERE name = 'legacy-tag'")
        )
        row = result.mappings().fetchone()
        assert row is not None
        # tag_type uses a Python-side default; raw SQL inserts get NULL.
        # Verify the row is readable and tag_type is either the default or NULL.
        assert row["tag_type"] in ("general", None)


# ---------------------------------------------------------------------------
# D. New model validation – enum & config models
# ---------------------------------------------------------------------------

class TestEnumValues:
    """Verify enum classes expose the expected set of values."""

    async def test_alerts_v2_enum_values(self, db_session: AsyncSession):
        assert set(e.value for e in AlertCategory) == {
            "physical_error", "drop", "fifo_overrun", "generic_error",
            "link_down", "link_flap", "controller_reboot", "card_missing",
            "collector_failure", "observer_timeout", "parse_failure",
            "expected_test_event", "recovery_event",
        }
        assert set(e.value for e in AlertState) == {
            "active", "muted", "expected", "recovered", "closed",
        }
        assert set(e.value for e in ReviewStatus) == {
            "pending", "confirmed_ok", "needs_followup", "false_positive",
        }

    async def test_card_presence_status_enum(self, db_session: AsyncSession):
        assert set(e.value for e in CardPresenceStatus) == {
            "present", "suspect_missing", "removed",
        }

    async def test_enrollment_status_enum(self, db_session: AsyncSession):
        assert set(e.value for e in EnrollmentStatus) == {
            "draft", "imported", "deploying_agent", "registered",
            "error", "retired",
        }

    async def test_connection_mode_enum(self, db_session: AsyncSession):
        assert set(e.value for e in ConnectionMode) == {
            "ssh_only", "agent_preferred", "agent_only",
        }


class TestConfigModels:
    """Verify system_config and schema_version can be written and read."""

    async def test_schema_version_can_be_recorded(self, db_session: AsyncSession):
        sv = SchemaVersionModel(
            version="11", description="Add enrollment tables",
        )
        db_session.add(sv)
        await db_session.flush()
        assert sv.id is not None

        result = await db_session.execute(
            text("SELECT version, description FROM schema_version WHERE id = :id"),
            {"id": sv.id},
        )
        row = result.fetchone()
        assert row[0] == "11"
        assert row[1] == "Add enrollment tables"

    async def test_system_config_key_value(self, db_session: AsyncSession):
        cfg = SystemConfigModel(key="ui.theme", value="dark")
        db_session.add(cfg)
        await db_session.flush()
        assert cfg.id is not None

        result = await db_session.execute(
            text("SELECT key, value FROM system_config WHERE id = :id"),
            {"id": cfg.id},
        )
        row = result.fetchone()
        assert row[0] == "ui.theme"
        assert row[1] == "dark"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_table_names(session: AsyncSession) -> set[str]:
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    )
    return {row[0] for row in result.fetchall()}


async def _get_column_names(session: AsyncSession, table: str) -> set[str]:
    result = await session.execute(text(f"PRAGMA table_info('{table}')"))
    return {row[1] for row in result.fetchall()}
