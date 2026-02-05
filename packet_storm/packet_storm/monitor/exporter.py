"""Statistics export to CSV and JSON formats."""

import csv
import json
import time
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import get_logger

logger = get_logger("monitor.exporter")


class StatsExporter:
    """Exports collected statistics to CSV or JSON format.

    Supports both one-shot export and continuous recording
    (appending snapshots over time).
    """

    def __init__(self, output_dir: str = "exports"):
        """Initialize the exporter.

        Args:
            output_dir: Directory for export files.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._csv_writer: Optional[csv.DictWriter] = None
        self._csv_file = None
        self._snapshots: list[dict] = []

    def record_snapshot(self, stats: dict[str, Any]) -> None:
        """Record a statistics snapshot for later export.

        Args:
            stats: Statistics snapshot dictionary.
        """
        snapshot = {
            "timestamp": time.time(),
            "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S"),
            **self._flatten_dict(stats),
        }
        self._snapshots.append(snapshot)

    def export_csv(self, filename: Optional[str] = None) -> str:
        """Export recorded snapshots to a CSV file.

        Args:
            filename: Output filename. Auto-generated if None.

        Returns:
            Path to the exported CSV file.
        """
        if not self._snapshots:
            logger.warning("No snapshots to export")
            return ""

        if filename is None:
            filename = f"stats_{time.strftime('%Y%m%d_%H%M%S')}.csv"

        filepath = self.output_dir / filename

        # Get all field names from snapshots
        fieldnames = set()
        for snap in self._snapshots:
            fieldnames.update(snap.keys())
        fieldnames = sorted(fieldnames)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for snap in self._snapshots:
                writer.writerow(snap)

        logger.info("Exported %d snapshots to %s", len(self._snapshots), filepath)
        return str(filepath)

    def export_json(self, filename: Optional[str] = None) -> str:
        """Export recorded snapshots to a JSON file.

        Args:
            filename: Output filename. Auto-generated if None.

        Returns:
            Path to the exported JSON file.
        """
        if not self._snapshots:
            logger.warning("No snapshots to export")
            return ""

        if filename is None:
            filename = f"stats_{time.strftime('%Y%m%d_%H%M%S')}.json"

        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._snapshots, f, indent=2, ensure_ascii=False)

        logger.info("Exported %d snapshots to %s", len(self._snapshots), filepath)
        return str(filepath)

    def export_packet_log(
        self,
        packets: list[dict],
        filename: Optional[str] = None,
    ) -> str:
        """Export packet details (hex dump + metadata) to a file.

        Args:
            packets: List of packet info dicts with 'hex', 'anomaly', 'timestamp'.
            filename: Output filename.

        Returns:
            Path to the exported file.
        """
        if filename is None:
            filename = f"packets_{time.strftime('%Y%m%d_%H%M%S')}.log"

        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for i, pkt in enumerate(packets):
                f.write(f"=== Packet {i + 1} ===\n")
                f.write(f"Timestamp: {pkt.get('timestamp', 'unknown')}\n")
                f.write(f"Anomaly:   {pkt.get('anomaly', 'none')}\n")
                f.write(f"Protocol:  {pkt.get('protocol', 'unknown')}\n")
                f.write(f"Size:      {pkt.get('size', 0)} bytes\n")
                f.write(f"Hex:\n{pkt.get('hex', '')}\n\n")

        logger.info("Exported %d packets to %s", len(packets), filepath)
        return str(filepath)

    def clear(self) -> None:
        """Clear recorded snapshots."""
        self._snapshots.clear()

    @staticmethod
    def _flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
        """Flatten a nested dictionary.

        Example:
            {'tx': {'packets': 100}} -> {'tx.packets': 100}
        """
        items: list[tuple[str, Any]] = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(StatsExporter._flatten_dict(v, new_key, sep).items())
            elif isinstance(v, list):
                items.append((new_key, str(v)))
            else:
                items.append((new_key, v))
        return dict(items)

    @property
    def snapshot_count(self) -> int:
        """Number of recorded snapshots."""
        return len(self._snapshots)
