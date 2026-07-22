#!/usr/bin/env python3
"""CLI: fold legacy query auto-monitors and scheduled query-templates into the
unified monitor_templates base (exec_location=backend). Idempotent.

    python3 -m scripts.migrate_to_unified_monitors      # from repo root
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def _main():
    from backend.db.database import init_db, AsyncSessionLocal, create_tables
    from backend.core.monitor_migration import migrate_all

    init_db()
    await create_tables()
    async with AsyncSessionLocal() as db:
        result = await migrate_all(db)
    print(f"Migration complete: {result}")


if __name__ == "__main__":
    asyncio.run(_main())
