"""Base class for anomaly generators.

All anomaly types (generic and protocol-specific) must implement
the BaseAnomaly interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from scapy.packet import Packet

from ..utils.logging import get_logger

logger = get_logger("anomaly")


class BaseAnomaly(ABC):
    """Abstract base class for anomaly generators.

    An anomaly takes a valid baseline packet and applies a specific
    mutation to create an abnormal/malicious variant.
    """

    # Anomaly metadata (override in subclasses)
    NAME: str = "unknown"
    DESCRIPTION: str = ""
    CATEGORY: str = "generic"  # 'generic' or protocol name like 'iscsi'
    APPLIES_TO: list[str] = ["all"]  # Protocol names this anomaly applies to

    def __init__(self, config: dict):
        """Initialize the anomaly generator.

        Args:
            config: Anomaly configuration dictionary containing at minimum:
                - type: Anomaly type name
                - count: Number of anomalous packets to generate
                May contain anomaly-specific parameters.
        """
        self.config = config
        self._applied_count = 0

    @abstractmethod
    def apply(self, packet: Packet) -> Packet:
        """Apply the anomaly to a packet.

        Args:
            packet: A valid baseline Scapy packet.

        Returns:
            A new packet with the anomaly applied.
            The original packet should not be modified.
        """
        ...

    def validate_config(self) -> list[str]:
        """Validate anomaly-specific configuration.

        Returns:
            List of warning/error messages. Empty if valid.
        """
        return []

    @property
    def applied_count(self) -> int:
        """Number of times this anomaly has been applied."""
        return self._applied_count

    def get_info(self) -> dict[str, Any]:
        """Get anomaly metadata."""
        return {
            "name": self.NAME,
            "description": self.DESCRIPTION,
            "category": self.CATEGORY,
            "applies_to": self.APPLIES_TO,
            "config": self.config,
            "applied_count": self._applied_count,
        }

    def _copy_packet(self, packet: Packet) -> Packet:
        """Create a deep copy of a Scapy packet.

        Args:
            packet: Packet to copy.

        Returns:
            Deep copy of the packet.
        """
        return packet.copy()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.NAME})>"
