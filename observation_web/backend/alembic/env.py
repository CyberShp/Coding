"""Alembic environment configuration."""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to sys.path so backend.* imports work
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import Base FIRST so metadata is populated
from backend.db.database import Base  # noqa: E402

# Import ALL model modules to register their tables on Base.metadata
from backend.models import (  # noqa: E402, F401
    array, alert, query, lifecycle, scheduler, traffic,
    task_session, snapshot, tag, user_session, user_preference,
    array_lock, alert_rule, audit_log, issue, monitor_template,
    observer_config, ai_interpretation, card_inventory, alerts_v2,
    expected_window, observer_snapshot, agent_heartbeat, card_presence,
    viewer_profile, system_config, enrollment, baseline, causal,
)

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False preserves application loggers that were
    # configured before alembic runs (important when alembic is called embedded
    # in the app via run_in_executor rather than via the CLI).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _get_sync_database_url() -> str:
    """Build sync SQLite URL (not async) for Alembic's synchronous runner."""
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
    """Run migrations in 'offline' mode — generate SQL without a live DB connection."""
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
