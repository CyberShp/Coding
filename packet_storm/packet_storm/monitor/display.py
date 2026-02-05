"""Rich terminal dashboard for real-time monitoring."""

import time
import threading
from typing import Any, Optional

from ..utils.logging import get_logger

logger = get_logger("monitor.display")


class TerminalDashboard:
    """Rich-based terminal dashboard for real-time statistics display.

    Shows a live-updating panel with:
    - Session status and protocol info
    - TX/RX packet and byte counters
    - Current and average send rates
    - Anomaly breakdown
    - Recent errors
    """

    def __init__(self, refresh_rate: float = 1.0):
        """Initialize the dashboard.

        Args:
            refresh_rate: Refresh interval in seconds.
        """
        self.refresh_rate = refresh_rate
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stats_func = None  # Function that returns stats dict
        self._live = None  # Rich Live context

    def start(self, stats_func) -> None:
        """Start the dashboard in a background thread.

        Args:
            stats_func: Callable that returns a stats dictionary.
        """
        self._stats_func = stats_func
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._display_loop,
            daemon=True,
            name="dashboard",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the dashboard."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _display_loop(self) -> None:
        """Main display loop using Rich Live."""
        try:
            from rich.live import Live
            from rich.table import Table
            from rich.panel import Panel
            from rich.layout import Layout
            from rich.text import Text
            from rich.console import Console

            console = Console()

            with Live(console=console, refresh_per_second=1.0 / self.refresh_rate) as live:
                self._live = live
                while not self._stop_event.is_set():
                    stats = self._stats_func() if self._stats_func else {}
                    display = self._build_display(stats)
                    live.update(display)
                    self._stop_event.wait(self.refresh_rate)

        except ImportError:
            logger.warning("Rich not available, falling back to basic display")
            self._basic_display_loop()

    def _basic_display_loop(self) -> None:
        """Fallback display loop without Rich."""
        while not self._stop_event.is_set():
            stats = self._stats_func() if self._stats_func else {}
            tx = stats.get("tx", {})
            print(
                f"\r  TX: {tx.get('packets', 0)} pkts | "
                f"{tx.get('current_pps', 0):.0f} pps | "
                f"{tx.get('current_mbps', 0):.4f} Mbps | "
                f"Errors: {tx.get('errors', 0)} | "
                f"Runtime: {stats.get('runtime_seconds', 0):.1f}s  ",
                end="", flush=True,
            )
            self._stop_event.wait(self.refresh_rate)
        print()  # Newline after stop

    def _build_display(self, stats: dict) -> Any:
        """Build the Rich display panel from statistics."""
        from rich.table import Table
        from rich.panel import Panel
        from rich.columns import Columns
        from rich.text import Text

        # Main stats table
        main_table = Table(show_header=True, header_style="bold cyan", expand=True)
        main_table.add_column("Metric", style="bold")
        main_table.add_column("Value", justify="right")
        main_table.add_column("Metric", style="bold")
        main_table.add_column("Value", justify="right")

        tx = stats.get("tx", {})
        rx = stats.get("rx", {})
        anom = stats.get("anomalies", {})

        main_table.add_row(
            "TX Packets", f"{tx.get('packets', 0):,}",
            "RX Packets", f"{rx.get('packets', 0):,}",
        )
        main_table.add_row(
            "TX Bytes", self._format_bytes(tx.get('bytes', 0)),
            "RX Bytes", self._format_bytes(rx.get('bytes', 0)),
        )
        main_table.add_row(
            "Current Rate", f"{tx.get('current_pps', 0):,.0f} pps",
            "Avg Rate", f"{tx.get('avg_pps', 0):,.0f} pps",
        )
        main_table.add_row(
            "Throughput", f"{tx.get('current_mbps', 0):.4f} Mbps",
            "Avg Throughput", f"{tx.get('avg_mbps', 0):.4f} Mbps",
        )
        main_table.add_row(
            "TX Errors", f"[red]{tx.get('errors', 0):,}[/red]",
            "Anomalies", f"{anom.get('total', 0):,}",
        )
        main_table.add_row(
            "Runtime", f"{stats.get('runtime_seconds', 0):.1f}s",
            "", "",
        )

        # Anomaly breakdown
        anomaly_text = ""
        by_type = anom.get("by_type", {})
        if by_type:
            anomaly_text = " | ".join(f"{k}: {v}" for k, v in sorted(by_type.items()))
        else:
            anomaly_text = "No anomalies applied yet"

        # Recent errors
        errors = stats.get("recent_errors", [])
        error_text = ""
        if errors:
            error_text = "\n".join(f"  {e['error']}" for e in errors[-3:])
        else:
            error_text = "  No errors"

        # Build panel
        from rich.console import Group

        content = Group(
            main_table,
            Text(f"\nAnomalies: {anomaly_text}", style="dim"),
            Text(f"\nRecent Errors:\n{error_text}", style="red dim"),
        )

        return Panel(
            content,
            title="[bold green]Packet Storm Monitor[/bold green]",
            border_style="green",
        )

    @staticmethod
    def _format_bytes(n: int) -> str:
        """Format byte count to human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"
