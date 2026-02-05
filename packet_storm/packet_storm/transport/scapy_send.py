"""Scapy-based transport backend.

Uses Scapy's sendp() for L2 frame sending. More portable than raw sockets
but with higher overhead per packet.
"""

from typing import Optional

from .base import TransportBackend, TransportError
from ..utils.logging import get_logger

logger = get_logger("transport.scapy")


class ScapyTransport(TransportBackend):
    """Transport backend using Scapy's sendp() for packet transmission.

    This backend uses Scapy's L2 sending capabilities, which provides
    broad OS compatibility but lower throughput than raw sockets or DPDK.
    """

    def __init__(self, transport_config: dict):
        super().__init__(transport_config)
        self._interface: str = ""
        self._conf = None  # Scapy's conf object

    def open(self, network_config: dict) -> None:
        """Initialize Scapy for sending on the specified interface.

        Args:
            network_config: Must contain 'interface' key.
        """
        self._interface = network_config.get("interface", "eth0")

        try:
            # Import Scapy (lazy import to avoid import-time overhead)
            from scapy.config import conf as scapy_conf
            from scapy.arch import get_if_hwaddr

            self._conf = scapy_conf

            # Verify interface exists
            try:
                mac = get_if_hwaddr(self._interface)
                logger.info("Scapy transport: interface %s, MAC %s", self._interface, mac)
            except Exception:
                logger.warning(
                    "Could not get MAC for interface %s, proceeding anyway",
                    self._interface,
                )

            self._is_open = True
            logger.info("Scapy transport opened on %s", self._interface)

        except ImportError:
            raise TransportError(
                "Scapy is not installed. Install with: pip install scapy"
            )

    def send(self, packet_bytes: bytes) -> int:
        """Send raw packet bytes using Scapy.

        Args:
            packet_bytes: Complete Ethernet frame bytes.

        Returns:
            Number of bytes sent.
        """
        if not self._is_open:
            raise TransportError("Scapy transport is not open")

        try:
            from scapy.all import Raw, Ether, sendp

            # Wrap raw bytes in an Ether/Raw packet for Scapy
            pkt = Ether(packet_bytes)

            sendp(pkt, iface=self._interface, verbose=False)
            self._stats.record_tx(len(packet_bytes))
            return len(packet_bytes)

        except Exception as e:
            self._stats.record_tx_error()
            raise TransportError(f"Scapy send failed: {e}")

    def send_batch(self, packets: list[bytes]) -> int:
        """Send a batch of packets using Scapy.

        Args:
            packets: List of Ethernet frame byte strings.

        Returns:
            Number of packets successfully sent.
        """
        if not self._is_open:
            raise TransportError("Scapy transport is not open")

        try:
            from scapy.all import Ether, sendp

            scapy_packets = [Ether(pkt_bytes) for pkt_bytes in packets]
            sendp(scapy_packets, iface=self._interface, verbose=False)

            for pkt in packets:
                self._stats.record_tx(len(pkt))

            return len(packets)

        except Exception as e:
            self._stats.record_tx_error()
            raise TransportError(f"Scapy batch send failed: {e}")

    def receive(self, timeout: float = 1.0) -> Optional[bytes]:
        """Receive a packet using Scapy sniff.

        Args:
            timeout: Sniff timeout in seconds.

        Returns:
            Received packet bytes, or None on timeout.
        """
        if not self._is_open:
            return None

        try:
            from scapy.all import sniff

            packets = sniff(
                iface=self._interface,
                count=1,
                timeout=timeout,
            )
            if packets:
                data = bytes(packets[0])
                self._stats.record_rx(len(data))
                return data
            return None

        except Exception:
            return None

    def close(self) -> None:
        """Close the Scapy transport."""
        self._is_open = False
        logger.info("Scapy transport closed")
