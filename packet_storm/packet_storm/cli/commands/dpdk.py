"""CLI commands for DPDK management."""

import click
import subprocess

from ...utils.logging import get_logger

logger = get_logger("cli.dpdk")


@click.group("dpdk")
def dpdk_group():
    """DPDK network interface management commands."""
    pass


@dpdk_group.command("status")
def status():
    """Show DPDK-compatible network interfaces and their binding status.

    Requires dpdk-devbind.py to be in PATH.
    """
    try:
        result = subprocess.run(
            ["dpdk-devbind.py", "--status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        click.echo(result.stdout)
        if result.stderr:
            click.echo(result.stderr, err=True)
    except FileNotFoundError:
        click.echo("dpdk-devbind.py not found in PATH.")
        click.echo("Install DPDK or add its tools to PATH.")
        click.echo("\nAlternatively, check with:")
        click.echo("  lspci | grep -i ethernet")
    except subprocess.TimeoutExpired:
        click.echo("Command timed out.")


@dpdk_group.command("bind")
@click.argument("pci_address")
@click.option("--driver", "-d", default="vfio-pci",
              type=click.Choice(["vfio-pci", "igb_uio", "uio_pci_generic"]),
              help="DPDK driver to bind.")
def bind(pci_address, driver):
    """Bind a network interface to a DPDK driver.

    PCI_ADDRESS should be in format like 0000:03:00.0

    Examples:

      packet-storm dpdk bind 0000:03:00.0

      packet-storm dpdk bind 0000:03:00.0 -d igb_uio
    """
    click.echo(f"Binding {pci_address} to {driver}...")
    try:
        result = subprocess.run(
            ["dpdk-devbind.py", "--bind", driver, pci_address],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            click.echo(f"Successfully bound {pci_address} to {driver}")
        else:
            click.echo(f"Binding failed: {result.stderr}", err=True)
    except FileNotFoundError:
        click.echo("dpdk-devbind.py not found. Full DPDK binding available after Phase 3.")
    except PermissionError:
        click.echo("Binding requires root privileges. Run with sudo.")


@dpdk_group.command("unbind")
@click.argument("pci_address")
def unbind(pci_address):
    """Unbind a network interface from DPDK driver and restore kernel driver.

    PCI_ADDRESS should be in format like 0000:03:00.0
    """
    click.echo(f"Unbinding {pci_address}...")
    try:
        result = subprocess.run(
            ["dpdk-devbind.py", "--unbind", pci_address],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            click.echo(f"Successfully unbound {pci_address}")
        else:
            click.echo(f"Unbinding failed: {result.stderr}", err=True)
    except FileNotFoundError:
        click.echo("dpdk-devbind.py not found.")


@dpdk_group.command("hugepages")
@click.option("--setup", is_flag=True, help="Setup hugepages (requires root).")
@click.option("--size", type=click.Choice(["2M", "1G"]), default="2M",
              help="Hugepage size.")
@click.option("--count", type=int, default=1024, help="Number of hugepages.")
def hugepages(setup, size, count):
    """Show or setup DPDK hugepage configuration.

    Examples:

      packet-storm dpdk hugepages

      packet-storm dpdk hugepages --setup --size 2M --count 1024
    """
    if setup:
        click.echo(f"Setting up {count} x {size} hugepages...")
        try:
            if size == "2M":
                path = "/sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"
            else:
                path = "/sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages"

            subprocess.run(
                ["sh", "-c", f"echo {count} > {path}"],
                check=True,
                timeout=5,
            )
            click.echo(f"Hugepages configured: {count} x {size}")
        except subprocess.CalledProcessError:
            click.echo("Failed to setup hugepages. Run with sudo.")
        except PermissionError:
            click.echo("Hugepage setup requires root privileges.")
    else:
        # Show current hugepage status
        click.echo("Hugepage status:")
        try:
            result = subprocess.run(
                ["sh", "-c", "cat /proc/meminfo | grep Huge"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            click.echo(result.stdout)
        except Exception:
            click.echo("Cannot read hugepage info (may not be on Linux).")
