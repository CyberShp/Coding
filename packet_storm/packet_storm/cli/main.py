"""Packet Storm CLI - main entry point using Click.

Provides command-line interface for configuration, running tests,
monitoring, and managing the packet storm tool.
"""

import click
import sys

from ..utils.logging import setup_logging, get_logger


@click.group()
@click.option(
    "--config", "-c",
    type=click.Path(exists=False),
    default=None,
    help="Path to JSON configuration file.",
)
@click.option(
    "--log-level", "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    help="Log level.",
)
@click.option(
    "--log-file",
    type=click.Path(),
    default=None,
    help="Path to log file.",
)
@click.pass_context
def cli(ctx: click.Context, config: str, log_level: str, log_file: str) -> None:
    """Packet Storm - Storage Protocol Abnormal Packet Testing Tool.

    A tool for constructing and sending abnormal iSCSI/NVMe-oF/NAS
    protocol packets to test storage device fault tolerance.
    """
    ctx.ensure_object(dict)

    # Setup logging
    setup_logging(level=log_level, log_file=log_file)
    logger = get_logger("cli")

    # Store config path in context for subcommands
    ctx.obj["config_path"] = config
    ctx.obj["log_level"] = log_level


# Import and register subcommands
from .commands.run import run_group
from .commands.config_cmd import config_group
from .commands.list_cmd import list_group
from .commands.monitor import monitor_group
from .commands.dpdk import dpdk_group
from .commands.batch_cmd import batch_group
from .commands.schedule_cmd import schedule_group
from .commands.stability_cmd import stability_group

cli.add_command(run_group, "run")
cli.add_command(config_group, "config")
cli.add_command(list_group, "list")
cli.add_command(monitor_group, "monitor")
cli.add_command(dpdk_group, "dpdk")
cli.add_command(batch_group, "batch")
cli.add_command(schedule_group, "schedule")
cli.add_command(stability_group, "stability")


if __name__ == "__main__":
    cli()
