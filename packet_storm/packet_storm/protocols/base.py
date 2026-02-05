"""Base protocol builder interface.

All protocol implementations (iSCSI, NVMe-oF, NAS) must implement
the BaseProtocolBuilder to be usable by the engine.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from scapy.packet import Packet

from ..utils.logging import get_logger

logger = get_logger("protocol")


class BaseProtocolBuilder(ABC):
    """Abstract base class for protocol packet builders.

    Each protocol implementation must provide methods to construct
    valid baseline packets of various types and to describe its
    supported packet types and fields.
    """

    # Protocol identifier (override in subclasses)
    PROTOCOL_NAME: str = "unknown"

    def __init__(self, network_config: dict, protocol_config: dict):
        """Initialize the protocol builder.

        Args:
            network_config: Network configuration (interface, MAC, IP, etc.)
            protocol_config: Protocol-specific configuration.
        """
        self.network_config = network_config
        self.protocol_config = protocol_config

    @abstractmethod
    def build_packet(self, packet_type: Optional[str] = None, **kwargs: Any) -> Packet:
        """Build a valid baseline packet.

        Args:
            packet_type: Type of packet to build (protocol-specific).
                If None, builds a default packet type.
            **kwargs: Additional packet parameters.

        Returns:
            A Scapy Packet object.
        """
        ...

    @abstractmethod
    def list_packet_types(self) -> list[str]:
        """List all supported packet types for this protocol.

        Returns:
            List of packet type names.
        """
        ...

    @abstractmethod
    def list_fields(self, packet_type: Optional[str] = None) -> dict[str, str]:
        """List all fields available for a packet type.

        Args:
            packet_type: Specific packet type. If None, lists common fields.

        Returns:
            Dictionary mapping field names to descriptions.
        """
        ...

    def get_protocol_info(self) -> dict[str, Any]:
        """Get information about this protocol builder.

        Returns:
            Dictionary with protocol metadata.
        """
        return {
            "name": self.PROTOCOL_NAME,
            "packet_types": self.list_packet_types(),
            "fields": self.list_fields(),
        }
