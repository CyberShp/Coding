"""Add dashboard_l1_tag_id to user_preferences."""

version = 10


def upgrade(conn):
    from .utils import add_column_if_not_exists

    add_column_if_not_exists(
        conn,
        "user_preferences",
        "dashboard_l1_tag_id",
        "INTEGER",
        default="NULL",
    )
