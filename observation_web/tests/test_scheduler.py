"""
Tests for backend/core/scheduler.py — exit_code-aware command execution.

Verifies that the scheduler correctly uses exit_code from execute_async()
rather than silently discarding it.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.db.database as db_mod
import backend.core.scheduler as sched_mod


class _CaptureResult:
    """Captures attribute assignments made to task_result inside _execute_task."""

    id = 99  # simulate DB-assigned PK

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def _build_fake_task(command: str, array_ids=None) -> MagicMock:
    task = MagicMock()
    task.id = 1
    task.name = "probe"
    task.enabled = True
    task.command = command
    task.query_template_id = None
    task.array_ids = array_ids or ["arr-001"]
    task.last_run_at = None
    task.next_run_at = None
    return task


def _make_mock_db(task):
    """Minimal async DB mock for _execute_task tests.

    execute() is async → await returns a sync-ish result object.
    scalar() on that result is synchronous, so we need a plain MagicMock there.
    """
    mock_db = AsyncMock()

    # `await db.execute(...)` returns this; `.scalar()` on it is NOT awaited
    query_result = MagicMock()
    query_result.scalar.return_value = task
    query_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = query_result

    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    return mock_db


def _make_session_factory(mock_db):
    """Return a mock AsyncSessionLocal whose context manager yields mock_db."""
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_db
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_ctx)


def _make_conn(exit_code: int, stdout: str, stderr: str) -> MagicMock:
    """Build a sync-is_connected + async-execute_async SSH connection mock."""
    conn = MagicMock()
    conn.is_connected.return_value = True
    conn.execute_async = AsyncMock(return_value=(exit_code, stdout, stderr))
    return conn


async def _run_task(scheduler, mock_pool, mock_db, fake_result, task_id=1):
    """Execute _execute_task under patched dependencies."""
    orig_session = db_mod.AsyncSessionLocal
    try:
        db_mod.AsyncSessionLocal = _make_session_factory(mock_db)
        with (
            patch.object(sched_mod, "get_ssh_pool", return_value=mock_pool),
            patch.object(sched_mod, "TaskResultModel", return_value=fake_result),
            patch.object(sched_mod, "sys_info"),
            patch.object(sched_mod, "sys_error"),
        ):
            await scheduler._execute_task(task_id)
    finally:
        db_mod.AsyncSessionLocal = orig_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonzero_exitcode_with_empty_stderr_is_recorded_as_failure():
    """
    exit_code != 0 + empty stderr → must still be recorded as an error.

    Regression case: old code only checked stderr, so a command that exits
    with code 1 but produces no stderr would be silently treated as success.
    """
    scheduler = sched_mod.TaskScheduler()
    scheduler.scheduler = MagicMock()

    fake_task = _build_fake_task("check_disk")
    fake_result = _CaptureResult()

    # exit_code=2, empty stdout, empty stderr — worst-case silent failure
    mock_pool = MagicMock()
    mock_pool.get_connection.return_value = _make_conn(2, "", "")
    mock_pool._connections = {}

    await _run_task(scheduler, mock_pool, _make_mock_db(fake_task), fake_result)

    assert fake_result.status == "failed", (
        f"Expected 'failed', got {fake_result.status!r}. "
        "exit_code=2 with empty stderr must be treated as failure."
    )
    assert fake_result.error is not None, "error field must not be None on non-zero exit"
    assert "exit code 2" in fake_result.error or "check_disk" in fake_result.error, (
        f"Error message should mention exit code or command. Got: {fake_result.error!r}"
    )


@pytest.mark.asyncio
async def test_zero_exitcode_no_stderr_is_success():
    """exit_code=0 + stdout + empty stderr → clean success, no errors recorded."""
    scheduler = sched_mod.TaskScheduler()
    scheduler.scheduler = MagicMock()

    fake_task = _build_fake_task("ls /tmp")
    fake_result = _CaptureResult()

    mock_pool = MagicMock()
    mock_pool.get_connection.return_value = _make_conn(0, "file.txt\n", "")
    mock_pool._connections = {}

    await _run_task(scheduler, mock_pool, _make_mock_db(fake_task), fake_result)

    assert fake_result.status == "success", (
        f"Expected 'success', got {fake_result.status!r}."
    )
    assert fake_result.error is None, (
        f"No error expected for exit_code=0. Got: {fake_result.error!r}"
    )


@pytest.mark.asyncio
async def test_nonzero_exitcode_with_stderr_includes_stderr_in_error():
    """exit_code != 0 + non-empty stderr → error message must contain the stderr text."""
    scheduler = sched_mod.TaskScheduler()
    scheduler.scheduler = MagicMock()

    fake_task = _build_fake_task("df -h")
    fake_result = _CaptureResult()

    mock_pool = MagicMock()
    mock_pool.get_connection.return_value = _make_conn(1, "", "No such file or directory")
    mock_pool._connections = {}

    await _run_task(scheduler, mock_pool, _make_mock_db(fake_task), fake_result)

    assert fake_result.status == "failed"
    assert "No such file or directory" in fake_result.error


@pytest.mark.asyncio
async def test_zero_exitcode_with_stderr_is_partial_success():
    """
    exit_code=0 + stdout + non-empty stderr → recorded in errors as warning,
    task has outputs so status is 'partial', not 'failed'.
    """
    scheduler = sched_mod.TaskScheduler()
    scheduler.scheduler = MagicMock()

    fake_task = _build_fake_task("some_cmd")
    fake_result = _CaptureResult()

    mock_pool = MagicMock()
    # exit_code=0, has stdout AND stderr warning
    mock_pool.get_connection.return_value = _make_conn(0, "ok output", "deprecation warning")
    mock_pool._connections = {}

    await _run_task(scheduler, mock_pool, _make_mock_db(fake_task), fake_result)

    # Has both outputs (stdout) and errors (stderr warning) → "partial"
    assert fake_result.status == "partial", (
        f"exit_code=0 with stdout+stderr should be 'partial'. Got: {fake_result.status!r}"
    )
    assert fake_result.error is not None
    assert "deprecation warning" in fake_result.error


@pytest.mark.asyncio
async def test_template_commands_path_multi_cmd_partial():
    """
    query_template_id → template.commands JSON array → multi-command execution.

    This is the original bug path (scheduler.py:170-182):
      task.command=None → falls to query_template_id branch
      → DB query for QueryTemplateModel → json.loads(template.commands)
      → loop over ["ls /tmp", "df -h"]

    First command succeeds (exit_code=0), second fails (exit_code=1).
    Expected: both commands executed, status="partial", errors contain stderr of 2nd cmd.
    """
    scheduler = sched_mod.TaskScheduler()
    scheduler.scheduler = MagicMock()

    # Task with template reference, no direct command
    fake_task = MagicMock()
    fake_task.id = 1
    fake_task.name = "template-task"
    fake_task.enabled = True
    fake_task.command = None        # forces template branch
    fake_task.query_template_id = 42
    fake_task.array_ids = ["arr-001"]
    fake_task.last_run_at = None
    fake_task.next_run_at = None

    # Template with two commands stored as JSON array string
    fake_template = MagicMock()
    fake_template.commands = '["ls /tmp", "df -h"]'

    fake_result = _CaptureResult()

    # DB is called TWICE in the template path:
    #   1st: fetch ScheduledTaskModel by task_id
    #   2nd: fetch QueryTemplateModel by query_template_id
    task_qr = MagicMock()
    task_qr.scalar.return_value = fake_task

    tmpl_qr = MagicMock()
    tmpl_qr.scalar.return_value = fake_template

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [task_qr, tmpl_qr]  # sequential per call
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    # SSH: first command succeeds, second exits non-zero
    mock_conn = MagicMock()
    mock_conn.is_connected.return_value = True
    mock_conn.execute_async = AsyncMock(side_effect=[
        (0, "file.txt", ""),       # ls /tmp → success
        (1, "", "disk full"),      # df -h → failure
    ])

    mock_pool = MagicMock()
    mock_pool.get_connection.return_value = mock_conn
    mock_pool._connections = {}

    await _run_task(scheduler, mock_pool, mock_db, fake_result)

    # Both commands in the template must have been executed
    assert mock_conn.execute_async.call_count == 2, (
        f"Expected 2 execute_async calls (one per template command). "
        f"Got: {mock_conn.execute_async.call_count}"
    )

    # One success + one failure → "partial"
    assert fake_result.status == "partial", (
        f"Expected 'partial' (success + failure). Got: {fake_result.status!r}"
    )
    assert fake_result.error is not None
    assert "disk full" in fake_result.error, (
        f"Error must contain stderr from failing command. Got: {fake_result.error!r}"
    )
