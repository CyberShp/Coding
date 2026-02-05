"""CLI commands for listing available protocols, anomalies, and transports."""

import click

from ...core.registry import protocol_registry, anomaly_registry, transport_registry
from ...utils.logging import get_logger

logger = get_logger("cli.list")


@click.group("list")
def list_group():
    """List available protocols, anomalies, and transports."""
    pass


@list_group.command("protocols")
def list_protocols():
    """List all registered protocol builders."""
    _ensure_imports()

    names = protocol_registry.list_names()
    if not names:
        click.echo("No protocols registered.")
        return

    click.echo("Available protocols:")
    for name in names:
        cls = protocol_registry.get(name)
        proto_name = getattr(cls, "PROTOCOL_NAME", name)
        click.echo(f"  {name:<15s}  {proto_name}")

        # List packet types if available
        try:
            instance = cls.__new__(cls)
            if hasattr(instance, "list_packet_types"):
                # We can't call this without init, just show class info
                pass
        except Exception:
            pass


@list_group.command("anomalies")
@click.option("--category", "-c", default=None,
              help="Filter by category (generic, iscsi, nvmeof, nas).")
def list_anomalies(category):
    """List all registered anomaly types."""
    _ensure_imports()

    from ...anomaly.registry import list_anomalies as _list_anomalies
    anomalies = _list_anomalies(category)

    if not anomalies:
        click.echo("No anomalies registered.")
        return

    click.echo("Available anomaly types:")
    click.echo(f"  {'Name':<25s} {'Category':<12s} Description")
    click.echo(f"  {'-'*25} {'-'*12} {'-'*40}")

    for anom in sorted(anomalies, key=lambda a: (a["category"], a["name"])):
        click.echo(
            f"  {anom['name']:<25s} {anom['category']:<12s} {anom['description']}"
        )


@list_group.command("transports")
def list_transports():
    """List all registered transport backends."""
    _ensure_imports()

    names = transport_registry.list_names()
    if not names:
        click.echo("No transports registered.")
        return

    click.echo("Available transport backends:")
    for name in names:
        cls = transport_registry.get(name)
        click.echo(f"  {name:<15s}  {cls.__name__}")


@list_group.command("packet-types")
@click.option("--protocol", "-p", type=click.Choice(["iscsi", "nvmeof", "nas"]),
              default="iscsi", help="Protocol to list packet types for.")
def list_packet_types(protocol):
    """List supported packet types for a protocol."""
    _ensure_imports()

    cls = protocol_registry.get(protocol)
    if cls is None:
        click.echo(f"Protocol '{protocol}' not registered.")
        return

    try:
        # Create a minimal instance to list packet types
        instance = cls(
            network_config={"src_ip": "0.0.0.0", "dst_ip": "0.0.0.0",
                            "src_mac": "00:00:00:00:00:00", "dst_mac": "00:00:00:00:00:00"},
            protocol_config={},
        )
        types = instance.list_packet_types()
        fields = instance.list_fields()

        click.echo(f"Packet types for {protocol}:")
        for t in types:
            click.echo(f"  - {t}")

        click.echo(f"\nCommon fields:")
        for fname, fdesc in fields.items():
            click.echo(f"  {fname:<30s}  {fdesc}")

    except Exception as e:
        click.echo(f"Error listing packet types: {e}")


@list_group.command("fields")
@click.option("--protocol", "-p", type=click.Choice(["iscsi", "nvmeof", "nas"]),
              default="iscsi", help="Protocol.")
@click.option("--packet-type", "-t", default=None, help="Specific packet type.")
def list_fields(protocol, packet_type):
    """List fields for a specific protocol/packet type."""
    _ensure_imports()

    cls = protocol_registry.get(protocol)
    if cls is None:
        click.echo(f"Protocol '{protocol}' not registered.")
        return

    try:
        instance = cls(
            network_config={"src_ip": "0.0.0.0", "dst_ip": "0.0.0.0",
                            "src_mac": "00:00:00:00:00:00", "dst_mac": "00:00:00:00:00:00"},
            protocol_config={},
        )
        fields = instance.list_fields(packet_type)

        title = f"Fields for {protocol}"
        if packet_type:
            title += f" / {packet_type}"
        click.echo(f"{title}:")

        for fname, fdesc in fields.items():
            click.echo(f"  {fname:<30s}  {fdesc}")

    except Exception as e:
        click.echo(f"Error listing fields: {e}")


def _ensure_imports():
    """Ensure protocol and anomaly modules are imported for registration."""
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
