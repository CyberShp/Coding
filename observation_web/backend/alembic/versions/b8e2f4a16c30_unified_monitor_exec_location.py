"""unify custom monitors: add exec_location/commands_json/monitor_arrays

Extends ``monitor_templates`` into the single monitor-definition base:
- ``exec_location`` (agent|backend) — where the definition runs
- ``commands_json`` — backend multi-command list (agent path keeps ``command``)
- ``monitor_arrays`` — backend target array ids (agent path uses assignments)

Fault-tolerant/idempotent: each column is guarded by an existence check so it is
safe against databases that already carry it (create_all on a fresh start).

Revision ID: b8e2f4a16c30
Revises: a3b7c1e4f209
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e2f4a16c30"
down_revision: Union[str, None] = "a3b7c1e4f209"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns_for(inspector: sa.Inspector, table: str) -> set:
    try:
        return {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "monitor_templates" not in set(inspector.get_table_names()):
        return
    cols = _columns_for(inspector, "monitor_templates")
    if "exec_location" not in cols:
        op.add_column(
            "monitor_templates",
            sa.Column("exec_location", sa.String(length=16), nullable=False,
                      server_default="agent"),
        )
    if "commands_json" not in cols:
        op.add_column("monitor_templates", sa.Column("commands_json", sa.Text(), nullable=True))
    if "monitor_arrays" not in cols:
        op.add_column("monitor_templates", sa.Column("monitor_arrays", sa.Text(), nullable=True))
    if "rule_spec_json" not in cols:
        op.add_column("monitor_templates", sa.Column("rule_spec_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "monitor_templates" not in set(inspector.get_table_names()):
        return
    cols = _columns_for(inspector, "monitor_templates")
    for col in ("rule_spec_json", "monitor_arrays", "commands_json", "exec_location"):
        if col in cols:
            op.drop_column("monitor_templates", col)
