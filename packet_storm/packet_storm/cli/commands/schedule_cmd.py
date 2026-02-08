"""CLI commands for scheduled and timed test execution."""

import click
import time

from ...core.scheduler import TaskScheduler
from ...core.config import ConfigManager
from ...core.engine import PacketStormEngine
from ...utils.logging import get_logger

logger = get_logger("cli.schedule")

# Module-level scheduler instance
_scheduler: TaskScheduler | None = None


def _get_scheduler() -> TaskScheduler:
    """Get or create the global scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
        _scheduler.start()
    return _scheduler


@click.group("schedule")
def schedule_group():
    """Schedule timed and periodic test execution."""
    pass


@schedule_group.command("delayed")
@click.option("--delay", "-d", type=float, required=True,
              help="Delay in seconds before execution.")
@click.option("--protocol", "-p", type=click.Choice(["iscsi", "nvmeof", "nas"]),
              default=None, help="Protocol type.")
@click.option("--name", type=str, default="", help="Task name.")
@click.pass_context
def schedule_delayed(ctx, delay, protocol, name):
    """Schedule a one-time test after a delay.

    Example:

      packet-storm schedule delayed --delay 60 --name "Delayed iSCSI test"
    """
    config_path = ctx.obj.get("config_path")
    scheduler = _get_scheduler()

    def run_test() -> None:
        click.echo(f"[Scheduled] Starting delayed test...")
        try:
            config_mgr = ConfigManager(config_path)
            if protocol:
                config_mgr.set("protocol.type", protocol)
            _import_protocols()
            engine = PacketStormEngine(config_mgr)
            engine.setup()
            engine.start()
            while engine.session and engine.session.is_active:
                time.sleep(0.5)
            engine.stop()
            if engine.session:
                stats = engine.session.stats
                click.echo(
                    f"[Scheduled] Test complete: {stats.packets_sent} packets sent"
                )
        except Exception as e:
            click.echo(f"[Scheduled] Test error: {e}", err=True)

    task_name = name or f"delayed-test-{int(delay)}s"
    task_id = scheduler.add_delayed(run_test, delay, name=task_name)
    click.echo(f"Scheduled task '{task_name}' (ID: {task_id}) in {delay}s")

    # Wait for completion
    try:
        click.echo("Waiting for scheduled task (Ctrl-C to cancel)...")
        while True:
            time.sleep(1)
            info = scheduler.get_task(task_id)
            if info and info["state"] in ("completed", "failed", "cancelled"):
                break
    except KeyboardInterrupt:
        scheduler.cancel(task_id)
        click.echo("\nTask cancelled.")
    finally:
        scheduler.stop()


@schedule_group.command("periodic")
@click.option("--interval", "-i", type=float, required=True,
              help="Interval between runs (seconds).")
@click.option("--max-runs", "-n", type=int, default=0,
              help="Maximum number of runs (0=unlimited).")
@click.option("--protocol", "-p", type=click.Choice(["iscsi", "nvmeof", "nas"]),
              default=None, help="Protocol type.")
@click.option("--name", type=str, default="", help="Task name.")
@click.pass_context
def schedule_periodic(ctx, interval, max_runs, protocol, name):
    """Schedule periodic recurring tests.

    Example:

      packet-storm schedule periodic --interval 300 --max-runs 10
    """
    config_path = ctx.obj.get("config_path")
    scheduler = _get_scheduler()
    run_counter = {"count": 0}

    def run_test() -> None:
        run_counter["count"] += 1
        click.echo(f"\n[Periodic] Run #{run_counter['count']} starting...")
        try:
            config_mgr = ConfigManager(config_path)
            if protocol:
                config_mgr.set("protocol.type", protocol)
            _import_protocols()
            engine = PacketStormEngine(config_mgr)
            engine.setup()
            engine.start()
            while engine.session and engine.session.is_active:
                time.sleep(0.5)
            engine.stop()
            if engine.session:
                stats = engine.session.stats
                click.echo(
                    f"[Periodic] Run #{run_counter['count']} complete: "
                    f"{stats.packets_sent} packets"
                )
        except Exception as e:
            click.echo(f"[Periodic] Run error: {e}", err=True)

    task_name = name or f"periodic-{int(interval)}s"
    task_id = scheduler.add_periodic(
        run_test, interval, name=task_name,
        max_runs=max_runs, start_immediately=True,
    )
    click.echo(
        f"Scheduled periodic task '{task_name}' (ID: {task_id}) "
        f"every {interval}s (max_runs={max_runs or 'unlimited'})"
    )

    try:
        click.echo("Running periodic tests (Ctrl-C to stop)...")
        while True:
            time.sleep(1)
            if max_runs > 0:
                info = scheduler.get_task(task_id)
                if info and info["state"] in ("completed", "failed"):
                    break
    except KeyboardInterrupt:
        click.echo("\nStopping periodic tests...")
        scheduler.cancel(task_id)
    finally:
        scheduler.stop()

    click.echo(f"Completed {run_counter['count']} runs.")


@schedule_group.command("cron")
@click.option("--expr", "-e", type=str, required=True,
              help="Cron expression (minute hour day month weekday).")
@click.option("--max-runs", "-n", type=int, default=0,
              help="Maximum number of runs (0=unlimited).")
@click.option("--name", type=str, default="", help="Task name.")
@click.pass_context
def schedule_cron(ctx, expr, max_runs, name):
    """Schedule tests using cron-like expression.

    \b
    Cron format: minute hour day_of_month month day_of_week
    Examples:
      */5 * * * *     -> Every 5 minutes
      0 */2 * * *     -> Every 2 hours
      30 8 * * *      -> Daily at 08:30
      0 0 * * 1       -> Every Monday at midnight

    \b
    Example:
      packet-storm schedule cron --expr "*/10 * * * *" --name "Every 10 min"
    """
    config_path = ctx.obj.get("config_path")
    scheduler = _get_scheduler()

    def run_test() -> None:
        click.echo(f"\n[Cron] Scheduled test starting...")
        try:
            config_mgr = ConfigManager(config_path)
            _import_protocols()
            engine = PacketStormEngine(config_mgr)
            engine.setup()
            engine.start()
            while engine.session and engine.session.is_active:
                time.sleep(0.5)
            engine.stop()
            if engine.session:
                click.echo(
                    f"[Cron] Complete: {engine.session.stats.packets_sent} packets"
                )
        except Exception as e:
            click.echo(f"[Cron] Error: {e}", err=True)

    task_name = name or f"cron-{expr.replace(' ', '_')}"
    try:
        task_id = scheduler.add_cron(
            run_test, expr, name=task_name, max_runs=max_runs,
        )
        click.echo(f"Scheduled cron task '{task_name}' (ID: {task_id})")

        info = scheduler.get_task(task_id)
        if info:
            click.echo(f"Next run: {info['next_run']}")

        click.echo("Waiting for cron schedule (Ctrl-C to stop)...")
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        click.echo("\nStopping cron scheduler...")
    except ValueError as e:
        click.echo(f"Invalid cron expression: {e}", err=True)
        raise SystemExit(1)
    finally:
        scheduler.stop()


@schedule_group.command("list")
def schedule_list():
    """List all scheduled tasks."""
    scheduler = _get_scheduler()
    tasks = scheduler.list_tasks()

    if not tasks:
        click.echo("No scheduled tasks.")
        return

    click.echo(f"{'ID':<12} {'Name':<25} {'State':<12} {'Runs':<8} {'Next Run'}")
    click.echo("-" * 80)
    for task in tasks:
        click.echo(
            f"{task['task_id']:<12} "
            f"{task['name']:<25} "
            f"{task['state']:<12} "
            f"{task['run_count']:<8} "
            f"{task['next_run'] or 'N/A'}"
        )


def _import_protocols() -> None:
    """Import protocol modules for registration."""
    try:
        import packet_storm.protocols.iscsi  # noqa: F401
    except ImportError:
        pass
    try:
        import packet_storm.transport  # noqa: F401
    except ImportError:
        pass
    try:
        import packet_storm.anomaly  # noqa: F401
    except ImportError:
        pass
