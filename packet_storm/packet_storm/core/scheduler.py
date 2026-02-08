"""Task scheduler for timed and periodic test execution.

Supports:
- One-time delayed execution
- Periodic recurring tasks with configurable intervals
- Cron-like schedule expressions (simplified)
- Task lifecycle management (add, cancel, pause, resume)
- Thread-safe operation
"""

import time
import threading
import heapq
from datetime import datetime, timedelta
from typing import Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from ..utils.logging import get_logger

logger = get_logger("scheduler")


class TaskState(str, Enum):
    """Scheduled task state."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass(order=True)
class ScheduledTask:
    """A single scheduled task entry.

    Ordered by next_run for priority queue scheduling.
    """
    next_run: float
    task_id: str = field(compare=False)
    name: str = field(compare=False)
    callback: Callable = field(compare=False, repr=False)
    args: tuple = field(compare=False, default_factory=tuple, repr=False)
    kwargs: dict = field(compare=False, default_factory=dict, repr=False)
    interval: float = field(compare=False, default=0.0)
    max_runs: int = field(compare=False, default=1)
    run_count: int = field(compare=False, default=0)
    state: TaskState = field(compare=False, default=TaskState.PENDING)
    last_result: Any = field(compare=False, default=None, repr=False)
    last_error: str = field(compare=False, default="")
    created_at: float = field(compare=False, default_factory=time.time)

    @property
    def is_recurring(self) -> bool:
        return self.interval > 0 and (self.max_runs == 0 or self.run_count < self.max_runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "state": self.state.value,
            "next_run": datetime.fromtimestamp(self.next_run).isoformat()
            if self.next_run > 0 else None,
            "interval_seconds": self.interval,
            "run_count": self.run_count,
            "max_runs": self.max_runs,
            "is_recurring": self.is_recurring,
            "last_error": self.last_error,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
        }


class CronExpression:
    """Simplified cron-like expression parser.

    Supports expressions like:
    - "*/5 * * * *"  -> every 5 minutes
    - "0 */2 * * *"  -> every 2 hours
    - "30 8 * * *"   -> daily at 08:30
    - "0 0 * * 1"    -> every Monday at midnight

    Fields: minute hour day_of_month month day_of_week
    """

    def __init__(self, expression: str):
        self.expression = expression
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression: '{expression}'. "
                "Expected format: 'minute hour day month weekday'"
            )
        self._minute = self._parse_field(parts[0], 0, 59)
        self._hour = self._parse_field(parts[1], 0, 23)
        self._dom = self._parse_field(parts[2], 1, 31)
        self._month = self._parse_field(parts[3], 1, 12)
        self._dow = self._parse_field(parts[4], 0, 6)  # 0=Mon in our impl

    @staticmethod
    def _parse_field(field_str: str, min_val: int, max_val: int) -> set[int]:
        """Parse a single cron field into a set of valid values."""
        values: set[int] = set()

        for part in field_str.split(","):
            part = part.strip()
            if part == "*":
                values.update(range(min_val, max_val + 1))
            elif part.startswith("*/"):
                step = int(part[2:])
                values.update(range(min_val, max_val + 1, step))
            elif "-" in part:
                start, end = part.split("-", 1)
                values.update(range(int(start), int(end) + 1))
            else:
                values.add(int(part))

        return values

    def next_occurrence(self, after: Optional[datetime] = None) -> datetime:
        """Calculate the next occurrence of this cron schedule.

        Args:
            after: Calculate next occurrence after this time.
                   Defaults to now.

        Returns:
            Next datetime matching the cron expression.
        """
        if after is None:
            after = datetime.now()

        # Start from the next minute
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Search up to 1 year ahead
        max_iterations = 525960  # ~1 year of minutes
        for _ in range(max_iterations):
            if (
                candidate.minute in self._minute
                and candidate.hour in self._hour
                and candidate.day in self._dom
                and candidate.month in self._month
                and candidate.weekday() in self._dow
            ):
                return candidate
            candidate += timedelta(minutes=1)

        raise ValueError(
            f"No matching time found for cron expression: {self.expression}"
        )


class TaskScheduler:
    """Thread-safe task scheduler for timed and periodic execution.

    Runs scheduled tasks in a dedicated background thread with
    precise timing using a priority queue.
    """

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._queue: list[ScheduledTask] = []  # min-heap by next_run
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._next_id = 0

    def _generate_id(self) -> str:
        """Generate a unique task ID."""
        self._next_id += 1
        return f"task-{self._next_id:04d}"

    def add_delayed(
        self,
        callback: Callable,
        delay_seconds: float,
        name: str = "",
        args: tuple = (),
        kwargs: Optional[dict] = None,
        task_id: Optional[str] = None,
    ) -> str:
        """Schedule a one-time task after a delay.

        Args:
            callback: Function to execute.
            delay_seconds: Seconds to wait before execution.
            name: Human-readable task name.
            args: Positional arguments for the callback.
            kwargs: Keyword arguments for the callback.
            task_id: Optional custom task ID.

        Returns:
            Task ID.
        """
        tid = task_id or self._generate_id()
        task = ScheduledTask(
            next_run=time.time() + delay_seconds,
            task_id=tid,
            name=name or f"delayed-{tid}",
            callback=callback,
            args=args,
            kwargs=kwargs or {},
            interval=0.0,
            max_runs=1,
        )

        with self._lock:
            self._tasks[tid] = task
            heapq.heappush(self._queue, task)

        self._wake_event.set()
        logger.info("Scheduled task '%s' in %.1fs", task.name, delay_seconds)
        return tid

    def add_periodic(
        self,
        callback: Callable,
        interval_seconds: float,
        name: str = "",
        args: tuple = (),
        kwargs: Optional[dict] = None,
        max_runs: int = 0,
        start_immediately: bool = False,
        task_id: Optional[str] = None,
    ) -> str:
        """Schedule a recurring periodic task.

        Args:
            callback: Function to execute periodically.
            interval_seconds: Seconds between executions.
            name: Human-readable task name.
            args: Positional arguments for the callback.
            kwargs: Keyword arguments for the callback.
            max_runs: Maximum number of runs (0=unlimited).
            start_immediately: Run immediately instead of waiting.
            task_id: Optional custom task ID.

        Returns:
            Task ID.
        """
        tid = task_id or self._generate_id()
        first_run = time.time() if start_immediately else time.time() + interval_seconds

        task = ScheduledTask(
            next_run=first_run,
            task_id=tid,
            name=name or f"periodic-{tid}",
            callback=callback,
            args=args,
            kwargs=kwargs or {},
            interval=interval_seconds,
            max_runs=max_runs,
        )

        with self._lock:
            self._tasks[tid] = task
            heapq.heappush(self._queue, task)

        self._wake_event.set()
        logger.info(
            "Scheduled periodic task '%s' every %.1fs (max_runs=%d)",
            task.name, interval_seconds, max_runs,
        )
        return tid

    def add_cron(
        self,
        callback: Callable,
        cron_expression: str,
        name: str = "",
        args: tuple = (),
        kwargs: Optional[dict] = None,
        max_runs: int = 0,
        task_id: Optional[str] = None,
    ) -> str:
        """Schedule a task using cron-like expression.

        Args:
            callback: Function to execute.
            cron_expression: Cron expression (minute hour day month weekday).
            name: Human-readable task name.
            args: Positional arguments for the callback.
            kwargs: Keyword arguments for the callback.
            max_runs: Maximum number of runs (0=unlimited).
            task_id: Optional custom task ID.

        Returns:
            Task ID.
        """
        tid = task_id or self._generate_id()
        cron = CronExpression(cron_expression)
        next_time = cron.next_occurrence()

        task = ScheduledTask(
            next_run=next_time.timestamp(),
            task_id=tid,
            name=name or f"cron-{tid}",
            callback=callback,
            args=args,
            kwargs=kwargs or {},
            interval=-1,  # Sentinel: use cron for next time calculation
            max_runs=max_runs,
        )
        # Store cron expression for recalculation
        task.kwargs["__cron_expr__"] = cron_expression

        with self._lock:
            self._tasks[tid] = task
            heapq.heappush(self._queue, task)

        self._wake_event.set()
        logger.info(
            "Scheduled cron task '%s' (%s), next: %s",
            task.name, cron_expression, next_time.isoformat(),
        )
        return tid

    def cancel(self, task_id: str) -> bool:
        """Cancel a scheduled task.

        Args:
            task_id: ID of the task to cancel.

        Returns:
            True if cancelled, False if not found.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.state in (TaskState.PENDING, TaskState.PAUSED):
                task.state = TaskState.CANCELLED
                logger.info("Cancelled task '%s'", task.name)
                return True
        return False

    def pause(self, task_id: str) -> bool:
        """Pause a recurring task.

        Args:
            task_id: ID of the task to pause.

        Returns:
            True if paused, False if not found.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.state == TaskState.PENDING:
                task.state = TaskState.PAUSED
                logger.info("Paused task '%s'", task.name)
                return True
        return False

    def resume(self, task_id: str) -> bool:
        """Resume a paused task.

        Args:
            task_id: ID of the task to resume.

        Returns:
            True if resumed, False if not found.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.state == TaskState.PAUSED:
                task.state = TaskState.PENDING
                task.next_run = time.time()
                heapq.heappush(self._queue, task)
                logger.info("Resumed task '%s'", task.name)
                self._wake_event.set()
                return True
        return False

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="task-scheduler",
        )
        self._thread.start()
        logger.info("Task scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("Task scheduler stopped")

    def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            self._wake_event.clear()

            with self._lock:
                now = time.time()

                # Process due tasks
                while self._queue and self._queue[0].next_run <= now:
                    task = heapq.heappop(self._queue)

                    if task.state in (TaskState.CANCELLED, TaskState.COMPLETED):
                        continue
                    if task.state == TaskState.PAUSED:
                        continue

                    # Execute task
                    task.state = TaskState.RUNNING
                    task.run_count += 1

                    # Release lock during execution
                    self._lock.release()
                    try:
                        # Remove internal cron key from kwargs before calling
                        call_kwargs = {
                            k: v for k, v in task.kwargs.items()
                            if not k.startswith("__")
                        }
                        result = task.callback(*task.args, **call_kwargs)
                        task.last_result = result
                        task.last_error = ""
                        logger.debug(
                            "Task '%s' completed (run %d)",
                            task.name, task.run_count,
                        )
                    except Exception as e:
                        task.last_error = str(e)
                        task.state = TaskState.FAILED
                        logger.error(
                            "Task '%s' failed: %s", task.name, e, exc_info=True
                        )
                    finally:
                        self._lock.acquire()

                    # Reschedule recurring tasks
                    if task.state != TaskState.FAILED:
                        if task.interval > 0 and (
                            task.max_runs == 0 or task.run_count < task.max_runs
                        ):
                            task.next_run = time.time() + task.interval
                            task.state = TaskState.PENDING
                            heapq.heappush(self._queue, task)
                        elif task.interval == -1:
                            # Cron-based: calculate next occurrence
                            cron_expr = task.kwargs.get("__cron_expr__")
                            if cron_expr and (
                                task.max_runs == 0 or task.run_count < task.max_runs
                            ):
                                try:
                                    cron = CronExpression(cron_expr)
                                    next_dt = cron.next_occurrence()
                                    task.next_run = next_dt.timestamp()
                                    task.state = TaskState.PENDING
                                    heapq.heappush(self._queue, task)
                                except ValueError:
                                    task.state = TaskState.COMPLETED
                            else:
                                task.state = TaskState.COMPLETED
                        else:
                            task.state = TaskState.COMPLETED

                # Calculate wait time
                if self._queue:
                    wait_time = max(
                        0.1, self._queue[0].next_run - time.time()
                    )
                else:
                    wait_time = 60.0

            # Wait for next task or wake signal
            self._wake_event.wait(timeout=wait_time)

    def list_tasks(self) -> list[dict]:
        """List all scheduled tasks.

        Returns:
            List of task dictionaries.
        """
        with self._lock:
            return [
                task.to_dict()
                for task in self._tasks.values()
                if task.state not in (TaskState.CANCELLED,)
            ]

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get information about a specific task.

        Args:
            task_id: Task ID.

        Returns:
            Task dictionary or None.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            return task.to_dict() if task else None
