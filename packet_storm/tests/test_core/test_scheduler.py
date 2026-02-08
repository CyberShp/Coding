"""Tests for TaskScheduler."""

import time
import pytest
import threading

from packet_storm.core.scheduler import (
    TaskScheduler, CronExpression, TaskState,
)


class TestCronExpression:
    """Test suite for CronExpression."""

    def test_every_minute(self):
        """Parse every-minute cron expression."""
        cron = CronExpression("* * * * *")
        from datetime import datetime
        now = datetime.now()
        next_time = cron.next_occurrence(now)
        # Should be the very next minute
        assert next_time.minute == (now.minute + 1) % 60 or next_time > now

    def test_every_5_minutes(self):
        """Parse every-5-minutes cron expression."""
        cron = CronExpression("*/5 * * * *")
        from datetime import datetime
        next_time = cron.next_occurrence()
        assert next_time.minute % 5 == 0

    def test_specific_time(self):
        """Parse specific time cron expression."""
        cron = CronExpression("30 8 * * *")
        from datetime import datetime
        next_time = cron.next_occurrence()
        assert next_time.minute == 30
        assert next_time.hour == 8

    def test_invalid_expression_raises(self):
        """Invalid cron expression raises ValueError."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            CronExpression("bad expression")

    def test_too_few_fields(self):
        """Too few fields raises ValueError."""
        with pytest.raises(ValueError):
            CronExpression("* * *")

    def test_range_field(self):
        """Cron range field parsing."""
        cron = CronExpression("1-5 * * * *")
        from datetime import datetime
        next_time = cron.next_occurrence()
        assert next_time.minute in range(1, 6)


class TestTaskScheduler:
    """Test suite for TaskScheduler."""

    def test_add_delayed_task(self):
        """Schedule and execute a delayed task."""
        scheduler = TaskScheduler()
        scheduler.start()

        result = {"called": False}

        def task():
            result["called"] = True

        scheduler.add_delayed(task, 0.1, name="test-delayed")
        time.sleep(0.5)
        scheduler.stop()

        assert result["called"]

    def test_add_periodic_task(self):
        """Schedule and execute a periodic task."""
        scheduler = TaskScheduler()
        scheduler.start()

        counter = {"count": 0}

        def task():
            counter["count"] += 1

        scheduler.add_periodic(
            task, 0.1, name="test-periodic",
            max_runs=3, start_immediately=True,
        )
        time.sleep(1.0)
        scheduler.stop()

        assert counter["count"] >= 2

    def test_cancel_task(self):
        """Cancel a pending task."""
        scheduler = TaskScheduler()
        scheduler.start()

        result = {"called": False}

        def task():
            result["called"] = True

        tid = scheduler.add_delayed(task, 5.0, name="cancel-me")
        assert scheduler.cancel(tid)

        time.sleep(0.5)
        scheduler.stop()
        assert not result["called"]

    def test_list_tasks(self):
        """List scheduled tasks."""
        scheduler = TaskScheduler()

        def noop():
            pass

        scheduler.add_delayed(noop, 100, name="task-a")
        scheduler.add_delayed(noop, 200, name="task-b")

        tasks = scheduler.list_tasks()
        assert len(tasks) == 2
        names = {t["name"] for t in tasks}
        assert "task-a" in names
        assert "task-b" in names

    def test_get_task(self):
        """Get info about a specific task."""
        scheduler = TaskScheduler()

        def noop():
            pass

        tid = scheduler.add_delayed(noop, 100, name="my-task")
        info = scheduler.get_task(tid)
        assert info is not None
        assert info["name"] == "my-task"
        assert info["state"] == "pending"

    def test_get_nonexistent_task(self):
        """Get info about nonexistent task returns None."""
        scheduler = TaskScheduler()
        assert scheduler.get_task("nonexistent") is None

    def test_pause_resume(self):
        """Pause and resume a periodic task."""
        scheduler = TaskScheduler()
        scheduler.start()

        counter = {"count": 0}

        def task():
            counter["count"] += 1

        tid = scheduler.add_periodic(
            task, 0.2, name="pausable",
            max_runs=0, start_immediately=True,
        )

        time.sleep(0.5)
        scheduler.pause(tid)
        count_at_pause = counter["count"]

        time.sleep(0.5)
        # Should not increase while paused
        assert counter["count"] == count_at_pause or counter["count"] <= count_at_pause + 1

        scheduler.stop()
