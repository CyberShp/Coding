---
feature_ids: [F-ALEMBIC]
topics: [database, migration, alembic, infrastructure]
doc_kind: implementation-spec
created: 2026-05-06
---

# Alembic Migration System — Implementation Spec

Owner: Opus-46 (architect) → Sonnet (coder) → GPT-5.4 (reviewer)

---

## Background

3 migration systems exist, 2 are dead code:
- `_apply_column_migrations()` in `database.py:117-131` — **only working one**, 1 hardcoded migration
- `backend/db/migrations/` (11 scripts + runner in `__init__.py`) — **NEVER CALLED**
- `backend/db/schema_migrate.py` (204 lines) — **NEVER CALLED**

Replace all with Alembic. Single source of truth for schema evolution.

---

## Phase A: Alembic Infrastructure

### A1: Add alembic dependency

**File**: `requirements.txt`

Add after the `aiosqlite` line:
```
alembic>=1.13
```

### A2: Initialize alembic

Run from project root (`observation_web/`):
```bash
alembic init backend/alembic
```

This creates:
- `alembic.ini` (project root)
- `backend/alembic/env.py`
- `backend/alembic/script.py.mako`
- `backend/alembic/versions/` (empty)

### A3: Configure alembic.ini

**File**: `alembic.ini` (project root)

Key settings:
```ini
[alembic]
script_location = backend/alembic
# sqlalchemy.url is set programmatically in env.py, not here
# Leave as empty or placeholder:
sqlalchemy.url = 

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### A4: Write env.py

**File**: `backend/alembic/env.py`

**Critical rules**:
1. Use **SYNC** engine (`sqlite:///` not `sqlite+aiosqlite:///`) — Alembic's migration runner is synchronous
2. Import ALL 41 model modules to populate `Base.metadata`
3. Set `render_as_batch=True` for SQLite (SQLite cannot ALTER column / DROP column without batch mode)
4. Resolve database path the same way `database.py:get_database_url()` does

```python
"""Alembic environment configuration."""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to sys.path so imports work
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import Base FIRST
from backend.db.database import Base

# Import ALL model modules to register them on Base.metadata
from backend.models import (  # noqa: F401
    array, alert, query, lifecycle, scheduler, traffic,
    task_session, snapshot, tag, user_session, user_preference,
    array_lock, alert_rule, audit_log, issue, monitor_template,
    observer_config, ai_interpretation, card_inventory, alerts_v2,
    expected_window, observer_snapshot, agent_heartbeat, card_presence,
    viewer_profile, system_config, enrollment, baseline, causal,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_sync_database_url() -> str:
    """Build sync SQLite URL (not async) for Alembic."""
    # Try loading app config; fall back to env var or default
    try:
        from backend.config import get_config
        app_cfg = get_config()
        db_path = app_cfg.database.path
    except Exception:
        db_path = os.environ.get("OBS_DB_PATH", "observation_web.db")

    if not os.path.isabs(db_path):
        db_path = str(project_root / db_path)

    return f"sqlite:///{db_path}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generate SQL without DB connection."""
    url = _get_sync_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connect to DB and apply."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_sync_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### A5: Create baseline revision

This revision captures the current 41-model schema as the starting point. It should be **empty** (no operations) because existing databases already have the correct schema, and new databases use `create_tables()`.

```bash
alembic revision -m "baseline: 41 ORM models"
```

Edit the generated file to have empty `upgrade()` and `downgrade()`:

```python
"""baseline: 41 ORM models

Revision ID: <auto-generated>
Revises: 
Create Date: 2026-05-06
"""
from alembic import op

revision = '<auto-generated>'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline revision — current schema already exists.
    # All 41 ORM model tables are created by create_tables().
    # Future migrations build on this baseline.
    pass


def downgrade() -> None:
    # Cannot downgrade past baseline
    pass
```

### A6: Modify create_tables() for Alembic integration

**File**: `backend/db/database.py`

Replace `create_tables()` (lines 90-114) with:

```python
async def create_tables():
    """Create tables and run Alembic migrations."""
    import asyncio
    from ..models import (  # noqa: F401
        array, alert, query, lifecycle, scheduler, traffic,
        task_session, snapshot, tag, user_session, user_preference,
        array_lock, alert_rule, audit_log, issue, monitor_template,
        observer_config, ai_interpretation, card_inventory, alerts_v2,
        expected_window, observer_snapshot, agent_heartbeat, card_presence,
        viewer_profile, system_config, enrollment, baseline, causal,
    )

    # Step 1: create_all for new databases (idempotent)
    async with _async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Step 2: run Alembic migrations (sync, via thread)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_alembic_upgrade)

    # Step 3: stamp head if alembic_version table is empty
    # (existing databases that predate Alembic)
    await loop.run_in_executor(None, _stamp_head_if_needed)

    # Step 4: verify all tables
    async with _async_engine.begin() as conn:
        def _check_tables(sync_conn):
            from sqlalchemy import text as _text
            result = sync_conn.execute(
                _text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            existing = {row[0] for row in result.fetchall()}
            expected = set(Base.metadata.tables.keys())
            missing = expected - existing
            if missing:
                logger.error("MISSING TABLES after create_all: %s", missing)
            else:
                logger.info("All %d tables verified", len(expected))

        await conn.run_sync(_check_tables)
```

Add these helper functions before `create_tables()`:

```python
def _get_alembic_config():
    """Build Alembic config pointing to our alembic directory."""
    from alembic.config import Config as AlembicConfig
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    alembic_ini = project_root / "alembic.ini"
    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("script_location", str(project_root / "backend" / "alembic"))
    return cfg


def _run_alembic_upgrade():
    """Run alembic upgrade head (synchronous — called via run_in_executor)."""
    from alembic import command
    try:
        cfg = _get_alembic_config()
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as e:
        logger.error("Alembic migration failed: %s", e)
        raise


def _stamp_head_if_needed():
    """Stamp the database as 'head' if alembic_version table is missing or empty.
    
    This handles existing databases that were created before Alembic was introduced.
    They already have the correct schema, just need the version marker.
    """
    from alembic import command
    from sqlalchemy import create_engine, text as _text

    # Get sync URL
    db_url = get_database_url().replace("sqlite+aiosqlite://", "sqlite://")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            # Check if alembic_version table exists
            result = conn.execute(
                _text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
            )
            if result.fetchone() is None:
                # Table doesn't exist yet — stamp will create it
                logger.info("No alembic_version table, stamping head")
                cfg = _get_alembic_config()
                command.stamp(cfg, "head")
                return

            # Table exists — check if empty
            result = conn.execute(_text("SELECT COUNT(*) FROM alembic_version"))
            count = result.scalar()
            if count == 0:
                logger.info("Empty alembic_version, stamping head")
                cfg = _get_alembic_config()
                command.stamp(cfg, "head")
    finally:
        engine.dispose()
```

### A7: Delete _apply_column_migrations

**File**: `backend/db/database.py`

Delete the entire `_apply_column_migrations()` function (lines 117-131) and remove the call to it from `create_tables()` (this is already handled by the new `create_tables()` above).

The single migration it contained (`monitor_templates.consecutive_threshold`) is already in the current ORM model, so `create_all()` handles it for new databases, and existing databases already have the column.

---

## Phase B: Clean Dead Code

### B1: Archive old migrations

Move `backend/db/migrations/` → `backend/db/_archived_migrations/`

This preserves history (someone might want to read them) but makes it clear they're not active. The `__init__.py` runner, `utils.py`, and all 11 scripts go together.

### B2: Delete schema_migrate.py

**File**: `backend/db/schema_migrate.py` — delete entirely (204 lines)

This file is never imported, never called. Verified via grep.

### B3: Verify no imports reference deleted code

Grep for:
- `from.*schema_migrate`
- `from.*migrations.*import`
- `_apply_column_migrations`

Fix any found (there should be none based on current codebase analysis).

---

## Phase C: Developer Workflow

### C1: Add migration creation docs

**File**: Add a brief section to `backend/alembic/README.md`

```markdown
# Database Migrations

Uses Alembic for schema migrations. SQLite with batch mode.

## Creating a new migration

After modifying any ORM model in `backend/models/`:

```bash
# Auto-generate migration from model diff
alembic revision --autogenerate -m "add column_name to table_name"

# Review the generated file in backend/alembic/versions/
# Then apply:
alembic upgrade head
```

## Key rules

- Alembic uses a **sync** SQLite engine (not async)
- `render_as_batch=True` enables ALTER/DROP on SQLite
- Always review auto-generated migrations before committing
- Test migration on a copy of production DB before deploying
- `create_tables()` runs `alembic upgrade head` automatically at startup
```

---

## Execution Checklist

```
A1: requirements.txt — add alembic>=1.13
A2: alembic init backend/alembic
A3: Configure alembic.ini
A4: Write env.py (SYNC engine, 41 models, render_as_batch)
A5: Create empty baseline revision
A6: Modify create_tables() — create_all + alembic upgrade + stamp
A7: Delete _apply_column_migrations()
B1: Archive backend/db/migrations/ → backend/db/_archived_migrations/
B2: Delete backend/db/schema_migrate.py
B3: Verify no broken imports
C1: Add backend/alembic/README.md

→ Run full test suite (pytest)
→ Manual smoke test: start server, verify tables
→ @gpt52 review
→ Merge
```

## Test Verification

After implementation, run:
1. `pytest` — all 532 tests must pass (no regressions)
2. Manual: delete `observation_web.db`, start server → verify all tables created + alembic_version stamped
3. Manual: start server with existing DB → verify alembic stamp, no errors
4. `alembic revision --autogenerate -m "test"` → verify it generates empty migration (no drift)
5. Delete the test migration file after verifying

---

## Constraints

- Do NOT modify any ORM models — pure infrastructure change
- Do NOT add new migrations beyond the baseline — that's for future work
- `create_tables()` must remain async (called from async `lifespan()`)
- Alembic commands are sync → use `run_in_executor` 
- SQLite batch mode is mandatory (`render_as_batch=True`)
