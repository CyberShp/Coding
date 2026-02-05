"""CLI commands for live monitoring of packet sending."""

import click
import time
import json


@click.group("monitor")
def monitor_group():
    """Live monitoring and statistics commands."""
    pass


@monitor_group.command("stats")
@click.option("--refresh", "-r", type=float, default=1.0,
              help="Refresh interval in seconds.")
@click.option("--json-output", is_flag=True, help="Output stats as JSON.")
def stats(refresh, json_output):
    """Display live statistics (placeholder for Phase 4 integration).

    In the full implementation, this connects to the running engine
    via shared memory or a local socket.
    """
    click.echo("Live monitoring will be available after Phase 4 integration.")
    click.echo("Use 'packet-storm run start' with verbose mode for now.")


@monitor_group.command("export")
@click.argument("output_file", type=click.Path())
@click.option("--format", "-f", type=click.Choice(["csv", "json"]),
              default="csv", help="Export format.")
def export(output_file, format):
    """Export collected statistics to a file.

    Examples:

      packet-storm monitor export stats.csv

      packet-storm monitor export stats.json -f json
    """
    click.echo(f"Statistics export to {output_file} ({format} format).")
    click.echo("Full export will be available after Phase 4.")
