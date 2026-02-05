"""Abstract base class for packet transport backends."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..utils.logging import get_logger

logger = get_logger("transport")


class TransportBackend(ABC):
    """Abstract interface for packet transport backends.

    All transport implementations (raw socket, Scapy, DPDK) must implement
    this interface to be used by the engine.
    """

    def __init__(self, transport_config: dict):
        """Initialize the transport backend.

        Args:
            transport_config: Transport section of the configuration.
        """
        self.transport_config = transport_config
        self._is_open = False
        self._stats = TransportStats()

    @abstractmethod
    def open(self, network_config: dict) -> None:
        """Open the transport for sending.

        Args:
            network_config: Network configuration (interface, MAC, IP, etc.)

        Raises:
            TransportError: If the transport cannot be opened.
        """
        ...

    @abstractmethod
    def send(self, packet_bytes: bytes) -> int:
        """Send raw packet bytes.

        Args:
            packet_bytes: Complete packet bytes (L2 frame) to send.

        Returns:
            Number of bytes actually sent.

        Raises:
            TransportError: If sending fails.
        """
        ...

    @abstractmethod
    def send_batch(self, packets: list[bytes]) -> int:
        """Send a batch of packets for higher throughput.

        Args:
            packets: List of complete packet byte strings.

        Returns:
            Number of packets successfully sent.

        Raises:
            TransportError: If sending fails.
        """
        ...

    def receive(self, timeout: float = 1.0) -> Optional[bytes]:
        """Receive a packet (optional, not all backends support this).

        Args:
            timeout: Receive timeout in seconds.

        Returns:
            Received packet bytes, or None if timeout.
        """
        return None

    @abstractmethod
    def close(self) -> None:
        """Close the transport and release resources."""
        ...

    @property
    def is_open(self) -> bool:
        """Check if the transport is currently open."""
        return self._is_open

    @property
    def stats(self) -> "TransportStats":
        """Get transport statistics."""
        return self._stats

    def get_info(self) -> dict[str, Any]:
        """Get transport backend information."""
        return {
            "type": self.__class__.__name__,
            "is_open": self._is_open,
            "stats": self._stats.to_dict(),
        }


class TransportStats:
    """Statistics for a transport backend."""

    def __init__(self):
        self.tx_packets: int = 0
        self.tx_bytes: int = 0
        self.tx_errors: int = 0
        self.rx_packets: int = 0
        self.rx_bytes: int = 0

    def record_tx(self, byte_count: int) -> None:
        """Record a successful transmission."""
        self.tx_packets += 1
        self.tx_bytes += byte_count

    def record_tx_error(self) -> None:
        """Record a transmission error."""
        self.tx_errors += 1

    def record_rx(self, byte_count: int) -> None:
        """Record a successful receive."""
        self.rx_packets += 1
        self.rx_bytes += byte_count

    def to_dict(self) -> dict[str, int]:
        return {
            "tx_packets": self.tx_packets,
            "tx_bytes": self.tx_bytes,
            "tx_errors": self.tx_errors,
            "rx_packets": self.rx_packets,
            "rx_bytes": self.rx_bytes,
        }

    def reset(self) -> None:
        """Reset all counters."""
        self.tx_packets = 0
        self.tx_bytes = 0
        self.tx_errors = 0
        self.rx_packets = 0
        self.rx_bytes = 0


class TransportError(Exception):
    """Raised when a transport operation fails."""
    pass
