"""
Schema migration: create fresh database from ORM and copy data from old DB.

Replaces incremental ALTER migrations. When upgrading:
1. Create new DB with Base.metadata.create_all (latest schema)
2. ATTACH old DB, copy data using column intersection
3. Replace old DB file with new one

Run before init_db/create_tables. Requires no other process holding the DB.
"""

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, text

from .database import Base

logger = logging.getLogger(__name__)

# Tables in FK-safe order: parents before children
# tags (self), arrays, user_preferences depend on tags
# alert_acknowledgements depends on alerts; array_locks depends on task_sessions
TABLE_ORDER = [
    "sync_state",
    "archive_config",
    "tags",
    "query_templates",
    "monitor_templates",
    "observer_configs",
    "user_sessions",
    "task_sessions",
    "scheduled_tasks",
    "task_results",
    "arrays",
    "port_traffic",
    "snapshots",
    "alerts",
    "alert_acknowledgements",
    "alert_expectation_rules",
    "array_locks",
    "audit_logs",
    "issues",
    "user_preferences",
    "card_inventory",
    "ai_interpretations",
    "alerts_archive",
]


def _get_resolved_db_path() -> str:
    """Return absolute path to database file."""
    from ..config import get_config

    config = get_config()
    db_path = config.database.path
    if not os.path.isabs(db_path):
        config_dir = Path(__file__).parent.parent.parent
        db_path = str(config_dir / db_path)
    return db_path


def _get_columns(conn, table: str, schema: str = "main") -> list[str]:
    """Get column names for a table. schema is 'main' or attached db name."""
    result = conn.execute(
        text(f"PRAGMA {schema}.table_info({table})")
    )
    return [row[1] for row in result.fetchall()]


def _table_exists(conn, table: str, schema: str = "main") -> bool:
    """Check if table exists in schema."""
    result = conn.execute(
        text(
            f"SELECT name FROM {schema}.sqlite_master "
            "WHERE type='table' AND name=:t"
        ),
        {"t": table},
    )
    return result.fetchone() is not None


def _migrate_data(old_path: str, new_path: str) -> None:
    """Copy data from old DB to new DB using column intersection."""
    old_path_abs = os.path.abspath(old_path)
    new_url = f"sqlite:///{new_path}"
    engine = create_engine(new_url, echo=False)

    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))

        # Attach old database (escape single quotes in path)
        path_escaped = old_path_abs.replace("'", "''")
        conn.execute(text(f"ATTACH DATABASE '{path_escaped}' AS old_db"))

        # Include any ORM tables not in TABLE_ORDER
        all_tables = list(TABLE_ORDER) + [
            t for t in Base.metadata.tables.keys()
            if t not in TABLE_ORDER
        ]

        for table in all_tables:
            if not _table_exists(conn, table, "main"):
                continue
            if not _table_exists(conn, table, "old_db"):
                logger.debug("Table %s not in old DB, skipping copy", table)
                continue

            old_cols = set(_get_columns(conn, table, "old_db"))
            new_cols = set(_get_columns(conn, table, "main"))
            common = old_cols & new_cols
            if not common:
                logger.warning("No common columns for %s, skipping", table)
                continue

            cols_str = ", ".join(sorted(common))
            sql = (
                f"INSERT INTO main.{table} ({cols_str}) "
                f"SELECT {cols_str} FROM old_db.{table}"
            )
            try:
                conn.execute(text(sql))
                conn.commit()
                count = conn.execute(
                    text(f"SELECT COUNT(*) FROM main.{table}")
                ).scalar()
                logger.info("Migrated %s: %d rows", table, count)
            except Exception as e:
                logger.error("Failed to migrate %s: %s", table, e)
                raise

        conn.execute(text("DETACH DATABASE old_db"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def migrate_if_needed() -> bool:
    """
    If DB file exists, create fresh schema and migrate data. Return True if
    migration ran, False if fresh install (no existing DB).
    """
    db_path = _get_resolved_db_path()
    if not os.path.exists(db_path):
        logger.info("No existing DB at %s, skip migration", db_path)
        return False

    new_path = db_path + ".migrate_new"
    try:
        logger.info("Starting schema migration: %s -> %s", db_path, new_path)

        # 1. Create new DB with latest ORM schema
        from ..models import (  # noqa: F401
            array,
            alert,
            query,
            lifecycle,
            scheduler,
            traffic,
            task_session,
            snapshot,
            tag,
            user_session,
            user_preference,
            array_lock,
            alert_rule,
            audit_log,
            issue,
            monitor_template,
            observer_config,
            ai_interpretation,
            card_inventory,
        )

        new_url = f"sqlite:///{new_path}"
        engine = create_engine(new_url, echo=False)
        Base.metadata.create_all(engine)
        engine.dispose()

        # 2. Copy data from old to new
        _migrate_data(db_path, new_path)

        # 3. Replace old with new (atomic on same filesystem)
        os.replace(new_path, db_path)

        # Remove WAL/shm if they exist (new db starts clean)
        for suffix in ("-wal", "-shm"):
            p = db_path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

        logger.info("Schema migration completed: %s", db_path)
        return True
    except Exception as e:
        logger.exception("Schema migration failed: %s", e)
        if os.path.exists(new_path):
            try:
                os.remove(new_path)
            except OSError:
                pass
        raise
