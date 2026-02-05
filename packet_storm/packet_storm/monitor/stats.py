"""Thread-safe statistics collection and aggregation."""

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Optional


class AtomicCounter:
    """Thread-safe counter using a lock."""

    def __init__(self, initial: int = 0):
        self._value = initial
        self._lock = threading.Lock()

    def increment(self, amount: int = 1) -> int:
        with self._lock:
            self._value += amount
            return self._value

    def decrement(self, amount: int = 1) -> int:
        with self._lock:
            self._value -= amount
            return self._value

    @property
    def value(self) -> int:
        return self._value

    def reset(self) -> None:
        with self._lock:
            self._value = 0


class StatsCollector:
    """Centralized statistics collector for the packet storm engine.

    Provides thread-safe counters for:
    - Packet send/receive counts and bytes
    - Anomaly application counts
    - Error counts
    - Per-second rate calculations
    """

    def __init__(self):
        # Packet counters
        self.tx_packets = AtomicCounter()
        self.tx_bytes = AtomicCounter()
        self.tx_errors = AtomicCounter()
        self.rx_packets = AtomicCounter()
        self.rx_bytes = AtomicCounter()

        # Anomaly counters
        self.anomalies_applied = AtomicCounter()
        self.anomalies_by_type: dict[str, AtomicCounter] = {}
        self._type_lock = threading.Lock()

        # Rate tracking
        self._start_time = time.time()
        self._last_snapshot_time = time.time()
        self._last_tx_packets = 0
        self._last_tx_bytes = 0
        self._current_pps = 0.0
        self._current_mbps = 0.0

        # Error details
        self._recent_errors: list[tuple[float, str]] = []
        self._error_lock = threading.Lock()
        self._max_errors = 100

    def record_tx(self, byte_count: int) -> None:
        """Record a successful packet transmission."""
        self.tx_packets.increment()
        self.tx_bytes.increment(byte_count)

    def record_tx_error(self, error: str = "") -> None:
        """Record a failed packet transmission."""
        self.tx_errors.increment()
        if error:
            with self._error_lock:
                self._recent_errors.append((time.time(), error))
                if len(self._recent_errors) > self._max_errors:
                    self._recent_errors = self._recent_errors[-self._max_errors:]

    def record_rx(self, byte_count: int) -> None:
        """Record a received packet."""
        self.rx_packets.increment()
        self.rx_bytes.increment(byte_count)

    def record_anomaly(self, anomaly_type: str) -> None:
        """Record an anomaly application."""
        self.anomalies_applied.increment()
        with self._type_lock:
            if anomaly_type not in self.anomalies_by_type:
                self.anomalies_by_type[anomaly_type] = AtomicCounter()
            self.anomalies_by_type[anomaly_type].increment()

    def update_rates(self) -> None:
        """Recalculate current rates (call periodically)."""
        now = time.time()
        elapsed = now - self._last_snapshot_time
        if elapsed < 0.1:
            return

        current_tx = self.tx_packets.value
        current_bytes = self.tx_bytes.value

        delta_pkts = current_tx - self._last_tx_packets
        delta_bytes = current_bytes - self._last_tx_bytes

        self._current_pps = delta_pkts / elapsed
        self._current_mbps = (delta_bytes * 8) / (elapsed * 1_000_000)

        self._last_snapshot_time = now
        self._last_tx_packets = current_tx
        self._last_tx_bytes = current_bytes

    def get_snapshot(self) -> dict[str, Any]:
        """Get a snapshot of all statistics.

        Returns:
            Dictionary with all current statistics.
        """
        self.update_rates()

        elapsed = time.time() - self._start_time
        avg_pps = self.tx_packets.value / elapsed if elapsed > 0 else 0
        avg_mbps = (self.tx_bytes.value * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0

        with self._type_lock:
            anomaly_breakdown = {
                name: counter.value
                for name, counter in self.anomalies_by_type.items()
            }

        with self._error_lock:
            recent_errors = list(self._recent_errors[-5:])

        return {
            "tx": {
                "packets": self.tx_packets.value,
                "bytes": self.tx_bytes.value,
                "errors": self.tx_errors.value,
                "current_pps": round(self._current_pps, 1),
                "current_mbps": round(self._current_mbps, 4),
                "avg_pps": round(avg_pps, 1),
                "avg_mbps": round(avg_mbps, 4),
            },
            "rx": {
                "packets": self.rx_packets.value,
                "bytes": self.rx_bytes.value,
            },
            "anomalies": {
                "total": self.anomalies_applied.value,
                "by_type": anomaly_breakdown,
            },
            "runtime_seconds": round(elapsed, 2),
            "recent_errors": [
                {"time": t, "error": e} for t, e in recent_errors
            ],
        }

    def reset(self) -> None:
        """Reset all counters."""
        self.tx_packets.reset()
        self.tx_bytes.reset()
        self.tx_errors.reset()
        self.rx_packets.reset()
        self.rx_bytes.reset()
        self.anomalies_applied.reset()
        with self._type_lock:
            self.anomalies_by_type.clear()
        with self._error_lock:
            self._recent_errors.clear()
        self._start_time = time.time()
        self._last_snapshot_time = time.time()
        self._last_tx_packets = 0
        self._last_tx_bytes = 0
