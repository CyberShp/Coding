"""Raw socket (AF_PACKET) transport backend for Linux.

Sends raw Ethernet frames directly through a network interface,
bypassing the kernel's TCP/IP stack.
"""

import socket
import struct
from typing import Optional

from .base import TransportBackend, TransportError
from ..utils.logging import get_logger

logger = get_logger("transport.raw_socket")


class RawSocketTransport(TransportBackend):
    """Transport backend using Linux AF_PACKET raw sockets.

    Sends complete Ethernet frames (L2) directly through a specified
    network interface. Requires root/CAP_NET_RAW privileges.
    """

    def __init__(self, transport_config: dict):
        super().__init__(transport_config)
        self._socket: Optional[socket.socket] = None
        self._interface: str = ""
        self._ifindex: int = 0

    def open(self, network_config: dict) -> None:
        """Open a raw socket bound to the specified interface.

        Args:
            network_config: Must contain 'interface' key.

        Raises:
            TransportError: If socket creation or binding fails.
        """
        self._interface = network_config.get("interface", "eth0")

        try:
            # Create raw socket (requires root)
            self._socket = socket.socket(
                socket.AF_PACKET,
                socket.SOCK_RAW,
                socket.htons(0x0003),  # ETH_P_ALL
            )

            # Bind to interface
            self._socket.bind((self._interface, 0))

            # Get interface index
            self._ifindex = self._socket.getsockname()[1] if hasattr(socket, 'AF_PACKET') else 0

            # Set send buffer size (4MB)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)

            self._is_open = True
            logger.info(
                "Raw socket opened on interface %s (ifindex=%d)",
                self._interface,
                self._ifindex,
            )

        except PermissionError:
            raise TransportError(
                "Raw socket requires root privileges or CAP_NET_RAW capability. "
                "Run with sudo or set capabilities."
            )
        except OSError as e:
            raise TransportError(f"Failed to open raw socket on {self._interface}: {e}")

    def send(self, packet_bytes: bytes) -> int:
        """Send a raw Ethernet frame.

        Args:
            packet_bytes: Complete Ethernet frame bytes.

        Returns:
            Number of bytes sent.
        """
        if not self._is_open or self._socket is None:
            raise TransportError("Raw socket is not open")

        try:
            sent = self._socket.send(packet_bytes)
            self._stats.record_tx(sent)
            return sent
        except OSError as e:
            self._stats.record_tx_error()
            raise TransportError(f"Raw socket send failed: {e}")

    def send_batch(self, packets: list[bytes]) -> int:
        """Send a batch of Ethernet frames.

        Args:
            packets: List of Ethernet frame byte strings.

        Returns:
            Number of packets successfully sent.
        """
        if not self._is_open or self._socket is None:
            raise TransportError("Raw socket is not open")

        sent_count = 0
        for pkt in packets:
            try:
                self._socket.send(pkt)
                self._stats.record_tx(len(pkt))
                sent_count += 1
            except OSError as e:
                self._stats.record_tx_error()
                logger.debug("Batch send error: %s", e)
        return sent_count

    def receive(self, timeout: float = 1.0) -> Optional[bytes]:
        """Receive a raw Ethernet frame.

        Args:
            timeout: Receive timeout in seconds.

        Returns:
            Received frame bytes, or None on timeout.
        """
        if not self._is_open or self._socket is None:
            return None

        self._socket.settimeout(timeout)
        try:
            data = self._socket.recv(65536)
            self._stats.record_rx(len(data))
            return data
        except socket.timeout:
            return None
        except OSError:
            return None

    def close(self) -> None:
        """Close the raw socket."""
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        self._is_open = False
        logger.info("Raw socket closed")

    def get_interface_mac(self) -> Optional[str]:
        """Get the MAC address of the bound interface.

        Returns:
            MAC address string, or None if not available.
        """
        if not self._is_open or self._socket is None:
            return None

        try:
            import fcntl
            SIOCGIFHWADDR = 0x8927
            req = struct.pack("256s", self._interface[:15].encode())
            result = fcntl.ioctl(self._socket.fileno(), SIOCGIFHWADDR, req)
            mac_bytes = result[18:24]
            return ":".join(f"{b:02x}" for b in mac_bytes)
        except (ImportError, OSError):
            return None
