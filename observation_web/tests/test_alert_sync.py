"""Behavioural tests for incremental alert sync (array_alert_sync.sync_array_alerts).

These cover the correctness fixes that previously had zero coverage:
- alert bursts > 500 lines are no longer truncated (tail -n +K, batched)
- log rotation / truncation is detected and re-synced from the start
- dedup uses the full message (hash), not a 50-char prefix that merged distinct alerts
- a successful pull stamps arrays.last_heartbeat_at (so agent_healthy can be reached)
"""
import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.array_alert_sync import sync_array_alerts
from backend.models.array import ArrayModel

CONFIG = SimpleNamespace(remote=SimpleNamespace(agent_log_path="/var/log/alerts.log"))


class FakeConn:
    """Minimal SSH connection stub backed by an in-memory list of log lines."""

    def __init__(self, lines):
        self.lines = list(lines)
        self.host = "1.2.3.4"
        self.port = 22

    def set_lines(self, lines):
        self.lines = list(lines)

    async def execute_async(self, cmd, timeout=10):
        if cmd.startswith("wc -l"):
            return (0, str(len(self.lines)), "")
        m = re.search(r"tail -n \+(\d+).*head -n (\d+)", cmd)
        if m:
            start = int(m.group(1))
            count = int(m.group(2))
            chunk = self.lines[start - 1:start - 1 + count]
            return (0, "\n".join(chunk), "")
        return (1, "", "unexpected cmd")


def _line(i, observer="obs", message=None, ts=None):
    return json.dumps({
        "timestamp": ts or (datetime(2026, 1, 1) + timedelta(seconds=i)).isoformat(),
        "observer_name": observer,
        "level": "warning",
        "message": message if message is not None else f"alert {i}",
        "details": {},
    })


@pytest.mark.asyncio
async def test_burst_over_500_not_truncated(db_session):
    """600-line burst must all be ingested (old code capped at tail -n 500)."""
    conn = FakeConn([_line(i) for i in range(600)])
    n = await sync_array_alerts("arr1", db_session, conn, CONFIG, full_sync=True)
    assert n == 600


@pytest.mark.asyncio
async def test_dedup_uses_full_message_not_prefix(db_session):
    """Same timestamp+observer, 60-char common prefix, different suffix → both kept."""
    common = "x" * 60
    conn = FakeConn([
        _line(0, message=common + "AAA", ts="2026-01-01T00:00:00"),
        _line(0, message=common + "BBB", ts="2026-01-01T00:00:00"),
    ])
    n = await sync_array_alerts("arr2", db_session, conn, CONFIG, full_sync=True)
    assert n == 2  # old key ts_observer_message[:50] would merge these to 1


@pytest.mark.asyncio
async def test_rotation_triggers_resync(db_session):
    """When the file shrinks (rotation/truncate), resync from the start."""
    conn = FakeConn([_line(i) for i in range(10)])
    assert await sync_array_alerts("arr3", db_session, conn, CONFIG) == 10
    # rotate: fewer, brand-new lines
    conn.set_lines([_line(i, message=f"new {i}", ts=f"2026-02-01T00:00:0{i}") for i in range(3)])
    assert await sync_array_alerts("arr3", db_session, conn, CONFIG) == 3


@pytest.mark.asyncio
async def test_incremental_advances_cursor(db_session):
    """Second sync only picks up lines appended after the first."""
    conn = FakeConn([_line(i) for i in range(5)])
    assert await sync_array_alerts("arr4", db_session, conn, CONFIG) == 5
    conn.set_lines([_line(i) for i in range(5)] + [_line(i, ts=f"2026-03-01T00:00:0{i}") for i in range(4)])
    assert await sync_array_alerts("arr4", db_session, conn, CONFIG) == 4


@pytest.mark.asyncio
async def test_successful_pull_stamps_heartbeat(db_session):
    """A successful pull must set last_heartbeat_at so agent_healthy is reachable."""
    db_session.add(ArrayModel(array_id="arrH", name="h", host="10.0.0.9"))
    await db_session.flush()
    conn = FakeConn([_line(0)])
    await sync_array_alerts("arrH", db_session, conn, CONFIG, full_sync=True)
    row = (await db_session.execute(
        select(ArrayModel).where(ArrayModel.array_id == "arrH")
    )).scalar_one()
    assert row.last_heartbeat_at is not None
