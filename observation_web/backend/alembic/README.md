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

- Alembic uses a **sync** SQLite engine (not async) — `sqlite:///` not `sqlite+aiosqlite:///`
- `render_as_batch=True` enables ALTER/DROP on SQLite via table recreation
- Always review auto-generated migrations before committing — autogenerate is not 100% perfect
- Test migration on a copy of the production DB before deploying
- `create_tables()` in `database.py` runs `alembic upgrade head` automatically at server startup

## Baseline

The `baseline: 41 ORM models` revision is a no-op snapshot of the initial schema.
Existing databases are stamped to `head` on first startup after Alembic was introduced.
New databases are created by `Base.metadata.create_all()` then immediately stamped.

## Archived migrations

`backend/db/_archived_migrations/` contains the 11 pre-Alembic migration scripts.
They are preserved for historical reference but are no longer executed.
