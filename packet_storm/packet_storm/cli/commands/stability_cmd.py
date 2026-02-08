"""CLI commands for stability/endurance testing."""

import click
import time
from datetime import datetime

from ...core.stability import StabilityRunner, StabilityCheckpoint
from ...utils.logging import get_logger

logger = get_logger("cli.stability")


@click.group("stability")
def stability_group():
    """Long-running stability test commands."""
    pass


@stability_group.command("run")
@click.option("--duration", "-d", type=float, default=72.0,
              help="Test duration in hours (default: 72).")
@click.option("--checkpoint-interval", type=float, default=15.0,
              help="Minutes between checkpoints (default: 15).")
@click.option("--report-interval", type=float, default=60.0,
              help="Minutes between report exports (default: 60).")
@click.option("--report-dir", type=click.Path(), default="reports/stability",
              help="Directory for periodic reports.")
@click.option("--memory-limit", type=float, default=0,
              help="Memory limit in MB (0=unlimited). Stop if exceeded.")
@click.option("--name", type=str, default=None,
              help="Test name for the report.")
@click.option("--export", "-o", type=click.Path(), default=None,
              help="Export final report to JSON file.")
@click.pass_context
def stability_run(ctx, duration, checkpoint_interval, report_interval,
                  report_dir, memory_limit, name, export):
    """Run a long-duration stability test.

    Continuously sends packets for the specified duration while monitoring
    system health, memory usage, and error rates.

    \b
    Examples:
      # Run 72-hour stability test
      packet-storm stability run --duration 72

      # Quick 1-hour test with frequent checkpoints
      packet-storm stability run --duration 1 --checkpoint-interval 5

      # With memory limit
      packet-storm stability run --duration 24 --memory-limit 512
    """
    config_path = ctx.obj.get("config_path")
    test_name = name or f"stability_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    click.echo(f"=== Stability Test: {test_name} ===")
    click.echo(f"  Duration:            {duration} hours")
    click.echo(f"  Checkpoint interval: {checkpoint_interval} minutes")
    click.echo(f"  Report interval:     {report_interval} minutes")
    click.echo(f"  Memory limit:        {'Unlimited' if memory_limit == 0 else f'{memory_limit} MB'}")
    click.echo(f"  Report directory:    {report_dir}")
    click.echo()

    def on_checkpoint(cp: StabilityCheckpoint) -> None:
        elapsed_h = cp.elapsed_seconds / 3600
        click.echo(
            f"  [{elapsed_h:.1f}h] "
            f"Pkts: {cp.packets_sent:,} | "
            f"Rate: {cp.send_rate_pps:.0f} pps | "
            f"RSS: {cp.memory_rss_mb:.1f} MB | "
            f"Errors: {cp.error_count} | "
            f"State: {cp.session_state}"
        )

    def on_anomaly(message: str) -> None:
        click.echo(f"  [!] ANOMALY: {message}")

    runner = StabilityRunner(
        config_path=config_path,
        duration_hours=duration,
        checkpoint_interval_minutes=checkpoint_interval,
        report_interval_minutes=report_interval,
        report_dir=report_dir,
        memory_limit_mb=memory_limit,
        on_checkpoint=on_checkpoint,
        on_anomaly=on_anomaly,
    )

    try:
        click.echo("Starting stability test (Ctrl-C to stop early)...")
        click.echo()
        report = runner.run(test_name=test_name)

        # Print summary
        click.echo("\n=== Stability Test Summary ===")
        click.echo(f"  Test name:       {report.test_name}")
        click.echo(f"  Duration:        {report.duration_hours:.2f} hours")
        click.echo(f"  Completed:       {'Yes' if report.completed else 'No (stopped early)'}")
        click.echo(f"  Checkpoints:     {len(report.checkpoints)}")
        click.echo(f"  Memory trend:    {report.memory_trend}")
        click.echo(f"  Anomalies:       {len(report.anomalies_detected)}")

        if report.final_stats:
            click.echo(f"  Packets sent:    {report.final_stats.get('packets_sent', 0):,}")
            click.echo(f"  Packets failed:  {report.final_stats.get('packets_failed', 0):,}")
            click.echo(f"  Success rate:    {report.final_stats.get('success_rate', 0):.2%}")

        if report.anomalies_detected:
            click.echo("\n  Detected anomalies:")
            for anomaly in report.anomalies_detected:
                click.echo(f"    - {anomaly}")

        # Export final report
        export_path = export or f"{report_dir}/{test_name}_final.json"
        report.export_json(export_path)
        click.echo(f"\n  Final report: {export_path}")

    except KeyboardInterrupt:
        click.echo("\n\nStopping stability test (Ctrl-C)...")
        runner.stop()
        time.sleep(2)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        logger.error("Stability test failed: %s", e, exc_info=True)
        raise SystemExit(1)


@stability_group.command("quick")
@click.option("--minutes", "-m", type=float, default=10.0,
              help="Quick test duration in minutes (default: 10).")
@click.pass_context
def stability_quick(ctx, minutes):
    """Run a quick stability check (10 minutes default).

    Useful for verifying system stability before starting a long test.
    """
    ctx.invoke(
        stability_run,
        duration=minutes / 60.0,
        checkpoint_interval=max(1.0, minutes / 5),
        report_interval=minutes,
        name=f"quick_check_{datetime.now().strftime('%H%M%S')}",
    )
