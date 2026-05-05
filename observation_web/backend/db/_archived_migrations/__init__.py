"""
Database migrations registry and runner.

Each migration file must export:
- version: int
- upgrade(conn): callable that receives a sync SQLAlchemy connection
"""

import importlib
import logging
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent


def _discover_migrations():
    """Discover all migration modules and return sorted by version."""
    modules = []
    for f in sorted(_MIGRATIONS_DIR.glob("*.py")):
        if f.name.startswith("_") or f.name == "__init__.py":
            continue
        name = f.stem
        if not name[0:3].isdigit():
            continue
        try:
            mod = importlib.import_module(f".{name}", package=__name__)
            if hasattr(mod, "version") and hasattr(mod, "upgrade"):
                modules.append((mod.version, mod))
        except Exception as e:
            logger.warning("Failed to load migration %s: %s", name, e)
    return sorted(modules, key=lambda x: x[0])


def run_migrations(conn):
    """Run all pending migrations. Idempotent."""
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER NOT NULL)"
    ))
    row = conn.execute(text("SELECT version FROM _schema_version")).fetchone()
    if not row:
        conn.execute(text("INSERT INTO _schema_version (version) VALUES (0)"))
        current = 0
    else:
        current = row[0]

    for ver, mod in _discover_migrations():
        if ver > current:
            logger.info("Running migration %s (version %d)", mod.__name__, ver)
            mod.upgrade(conn)
            conn.execute(text(f"UPDATE _schema_version SET version = {ver}"))
            current = ver
