"""CLI commands for running packet storm tests."""

import click
import time
import json

from ...core.config import ConfigManager
from ...core.engine import PacketStormEngine
from ...utils.logging import get_logger

logger = get_logger("cli.run")


@click.group("run")
def run_group():
    """Start, stop, pause, resume packet sending."""
    pass


@run_group.command("start")
@click.option("--protocol", "-p", type=click.Choice(["iscsi", "nvmeof", "nas"]),
              default=None, help="Override protocol type.")
@click.option("--packet-type", "-t", default=None,
              help="Packet type to send (e.g., login_request, scsi_read).")
@click.option("--count", "-n", type=int, default=None,
              help="Override total repeat count.")
@click.option("--interval", "-i", type=float, default=None,
              help="Override interval between packets (ms).")
@click.option("--duration", "-d", type=float, default=None,
              help="Override duration in seconds (0=unlimited).")
@click.option("--backend", "-b", type=click.Choice(["scapy", "raw_socket", "dpdk"]),
              default=None, help="Override transport backend.")
@click.pass_context
def start(ctx, protocol, packet_type, count, interval, duration, backend):
    """Start sending anomalous packets.

    Examples:

      packet-storm run start

      packet-storm run start -p iscsi -t login_request -n 1000

      packet-storm run start -c my_config.json --backend raw_socket
    """
    config_path = ctx.obj.get("config_path")

    try:
        # Load configuration
        config_mgr = ConfigManager(config_path)

        # Apply CLI overrides
        if protocol:
            config_mgr.set("protocol.type", protocol)
        if count:
            config_mgr.set("execution.repeat", count)
        if interval is not None:
            config_mgr.set("execution.interval_ms", interval)
        if duration is not None:
            config_mgr.set("execution.duration_seconds", duration)
        if backend:
            config_mgr.set("transport.backend", backend)

        # Ensure protocol modules are imported for registration
        _import_protocols()

        # Create and run engine
        engine = PacketStormEngine(config_mgr)

        click.echo(f"Setting up engine (protocol={config_mgr.get_protocol_type()})...")
        engine.setup()

        click.echo("Starting packet sending...")
        engine.start()

        # Wait for completion or Ctrl-C
        try:
            while engine.session and engine.session.is_active:
                time.sleep(0.5)
                stats = engine.session.stats
                click.echo(
                    f"\r  Sent: {stats.packets_sent} | "
                    f"Failed: {stats.packets_failed} | "
                    f"Rate: {stats.send_rate_pps:.0f} pps | "
                    f"Duration: {stats.duration:.1f}s",
                    nl=False,
                )
        except KeyboardInterrupt:
            click.echo("\n\nStopping (Ctrl-C)...")
            engine.stop()

        # Print final stats
        if engine.session:
            click.echo("\n")
            _print_stats(engine.session.stats.to_dict())

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        logger.error("Start failed: %s", e, exc_info=True)
        raise SystemExit(1)


@run_group.command("step")
@click.option("--protocol", "-p", type=click.Choice(["iscsi", "nvmeof", "nas"]),
              default=None, help="Override protocol type.")
@click.option("--packet-type", "-t", default=None, help="Packet type to send.")
@click.pass_context
def step(ctx, protocol, packet_type):
    """Send a single packet (step mode).

    Useful for debugging and inspecting individual packets.
    """
    config_path = ctx.obj.get("config_path")

    try:
        config_mgr = ConfigManager(config_path)
        if protocol:
            config_mgr.set("protocol.type", protocol)

        _import_protocols()

        engine = PacketStormEngine(config_mgr)
        engine.setup()

        click.echo("Sending single packet...")
        engine.step()

        # Wait briefly for the step to complete
        time.sleep(0.5)
        engine.stop()

        if engine.session:
            stats = engine.session.stats
            click.echo(f"Sent: {stats.packets_sent}, Failed: {stats.packets_failed}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@run_group.command("batch")
@click.argument("batch_file", type=click.Path(exists=True))
@click.pass_context
def batch(ctx, batch_file):
    """Run a batch of test scenarios from a JSON file.

    BATCH_FILE should contain a JSON array of configuration objects,
    each defining a complete test scenario.
    """
    try:
        with open(batch_file, "r") as f:
            scenarios = json.load(f)

        if not isinstance(scenarios, list):
            scenarios = [scenarios]

        click.echo(f"Running {len(scenarios)} test scenarios...")

        _import_protocols()

        for i, scenario in enumerate(scenarios, 1):
            click.echo(f"\n--- Scenario {i}/{len(scenarios)} ---")
            desc = scenario.get("description", f"Scenario {i}")
            click.echo(f"Description: {desc}")

            config_mgr = ConfigManager()
            # Merge scenario config
            for key, value in scenario.items():
                if key != "description":
                    config_mgr.set(key, value)

            engine = PacketStormEngine(config_mgr)
            engine.setup()
            engine.start()

            try:
                while engine.session and engine.session.is_active:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                click.echo("\nStopping batch...")
                engine.stop()
                break

            engine.stop()
            if engine.session:
                _print_stats(engine.session.stats.to_dict())

        click.echo("\nBatch complete.")

    except Exception as e:
        click.echo(f"Batch error: {e}", err=True)
        raise SystemExit(1)


def _import_protocols():
    """Import protocol modules to trigger registration."""
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


def _print_stats(stats: dict) -> None:
    """Print formatted statistics."""
    click.echo("=== Session Statistics ===")
    click.echo(f"  Packets sent:    {stats['packets_sent']}")
    click.echo(f"  Packets failed:  {stats['packets_failed']}")
    click.echo(f"  Anomalies:       {stats['anomalies_applied']}")
    click.echo(f"  Bytes sent:      {stats['bytes_sent']}")
    click.echo(f"  Duration:        {stats['duration_seconds']:.2f}s")
    click.echo(f"  Send rate:       {stats['send_rate_pps']:.0f} pps")
    click.echo(f"  Throughput:      {stats['send_rate_mbps']:.4f} Mbps")
    click.echo(f"  Success rate:    {stats['success_rate']:.2%}")
    if stats.get("errors"):
        click.echo(f"  Recent errors:   {len(stats['errors'])}")
        for err in stats["errors"][-3:]:
            click.echo(f"    - {err}")
