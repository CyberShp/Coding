"""CLI commands for configuration management."""

import json
import click

from ...core.config import ConfigManager
from ...utils.logging import get_logger

logger = get_logger("cli.config")


@click.group("config")
def config_group():
    """Configuration management commands."""
    pass


@config_group.command("show")
@click.option("--key", "-k", default=None, help="Show specific config key (dot-separated).")
@click.pass_context
def show(ctx, key):
    """Show current configuration.

    Examples:

      packet-storm config show

      packet-storm config show -k network.src_ip

      packet-storm config show -k protocol.iscsi
    """
    config_path = ctx.obj.get("config_path")
    config_mgr = ConfigManager(config_path)

    if key:
        value = config_mgr.get(key)
        if value is None:
            click.echo(f"Key '{key}' not found.")
        else:
            if isinstance(value, (dict, list)):
                click.echo(json.dumps(value, indent=2, ensure_ascii=False))
            else:
                click.echo(f"{key} = {value}")
    else:
        click.echo(json.dumps(config_mgr.config, indent=2, ensure_ascii=False))


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def set_value(ctx, key, value):
    """Set a configuration value at runtime.

    KEY is a dot-separated path (e.g., 'network.src_ip').
    VALUE is the new value (auto-detected type).

    Examples:

      packet-storm config set network.src_ip 192.168.1.100

      packet-storm config set transport.backend scapy

      packet-storm config set execution.repeat 500
    """
    config_path = ctx.obj.get("config_path")
    config_mgr = ConfigManager(config_path)

    # Try to parse value type
    parsed_value = _parse_value(value)
    config_mgr.set(key, parsed_value)
    click.echo(f"Set {key} = {parsed_value}")


@config_group.command("export")
@click.argument("output_file", type=click.Path())
@click.pass_context
def export_config(ctx, output_file):
    """Export current configuration to a JSON file.

    Example:

      packet-storm config export my_scenario.json
    """
    config_path = ctx.obj.get("config_path")
    config_mgr = ConfigManager(config_path)
    config_mgr.export_config(output_file)
    click.echo(f"Configuration exported to {output_file}")


@config_group.command("import")
@click.argument("input_file", type=click.Path(exists=True))
@click.pass_context
def import_config(ctx, input_file):
    """Import configuration from a JSON file.

    Example:

      packet-storm config import saved_scenario.json
    """
    config_path = ctx.obj.get("config_path")
    config_mgr = ConfigManager(config_path)
    config_mgr.import_config(input_file)
    click.echo(f"Configuration imported from {input_file}")


@config_group.command("validate")
@click.pass_context
def validate(ctx):
    """Validate the current configuration."""
    config_path = ctx.obj.get("config_path")
    try:
        config_mgr = ConfigManager(config_path)
        click.echo("Configuration is valid.")
    except Exception as e:
        click.echo(f"Validation failed: {e}", err=True)
        raise SystemExit(1)


def _parse_value(value: str):
    """Try to parse a string value to its appropriate type."""
    # Boolean
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False
    # Integer
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    # JSON (for complex values)
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        pass
    # String
    return value
