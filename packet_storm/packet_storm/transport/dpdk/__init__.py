"""DPDK transport backend for Packet Storm.

Provides high-speed packet sending using DPDK's data plane libraries,
bypassing the kernel network stack for line-rate performance.
"""

import ctypes
from ctypes import c_void_p
from typing import Optional

from ..base import TransportBackend, TransportError
from .binding import load_dpdk, DPDKLoadError
from .eal import EALManager, DPDKError
from .mempool import MempoolManager
from .port import PortManager
from .tx_rx import TxRxEngine, RateLimiter
from .hugepage import HugepageManager
from .driver import DriverManager
from ...utils.logging import get_logger

logger = get_logger("transport.dpdk")


class DPDKTransport(TransportBackend):
    """DPDK-based transport backend for line-rate packet sending.

    Uses DPDK's EAL, mempool, and ethdev APIs through ctypes bindings
    to send packets directly through the NIC, bypassing the kernel.
    """

    def __init__(self, transport_config: dict):
        super().__init__(transport_config)
        self._dpdk_config = transport_config.get("dpdk", {})
        self._rate_config = transport_config.get("rate_limit", {})

        self._eal: Optional[EALManager] = None
        self._mempool: Optional[MempoolManager] = None
        self._port_mgr: Optional[PortManager] = None
        self._tx_engine: Optional[TxRxEngine] = None
        self._rate_limiter: Optional[RateLimiter] = None
        self._port_id: int = self._dpdk_config.get("port_id", 0)

    def open(self, network_config: dict) -> None:
        """Initialize DPDK and set up the port for sending.

        Args:
            network_config: Network configuration.
        """
        try:
            # Load DPDK library
            load_dpdk(self._dpdk_config.get("lib_path"))

            # Initialize EAL
            eal_args = self._dpdk_config.get("eal_args", ["-l", "0", "-n", "4"])
            self._eal = EALManager(eal_args)
            self._eal.init()

            # Create memory pool
            self._mempool = MempoolManager()
            self._mempool.create_pool(
                name="storm_pkt_pool",
                num_mbufs=self._dpdk_config.get("num_mbufs", 8191),
            )

            # Configure port
            self._port_mgr = PortManager()

            nb_ports = self._port_mgr.get_available_ports()
            if nb_ports == 0:
                raise TransportError("No DPDK ports available. Check NIC binding.")

            if self._port_id >= nb_ports:
                raise TransportError(
                    f"Port {self._port_id} not available (only {nb_ports} ports found)"
                )

            self._port_mgr.configure_port(
                port_id=self._port_id,
                nb_rx_queues=self._dpdk_config.get("nb_rx_queues", 1),
                nb_tx_queues=self._dpdk_config.get("nb_tx_queues", 1),
                mempool=self._mempool.get_pool(),
            )
            self._port_mgr.start_port(self._port_id)

            # Create TX engine
            self._tx_engine = TxRxEngine(
                port_id=self._port_id,
                mempool=self._mempool,
            )

            # Setup rate limiter
            if self._rate_config.get("enabled", False):
                self._rate_limiter = RateLimiter(
                    mode=self._rate_config.get("mode", "pps"),
                    rate=self._rate_config.get("value", 100000),
                )

            self._is_open = True

            mac = self._port_mgr.get_mac_address(self._port_id)
            logger.info("DPDK transport opened on port %d (MAC: %s)", self._port_id, mac)

        except DPDKLoadError as e:
            raise TransportError(f"DPDK load failed: {e}")
        except DPDKError as e:
            raise TransportError(f"DPDK initialization failed: {e}")

    def send(self, packet_bytes: bytes) -> int:
        """Send a single packet via DPDK.

        Args:
            packet_bytes: Complete Ethernet frame bytes.

        Returns:
            Number of bytes sent.
        """
        if not self._is_open or self._tx_engine is None:
            raise TransportError("DPDK transport is not open")

        # Rate limiting
        if self._rate_limiter:
            self._rate_limiter.wait(len(packet_bytes))

        if self._tx_engine.send_packet(packet_bytes):
            self._stats.record_tx(len(packet_bytes))
            return len(packet_bytes)
        else:
            self._stats.record_tx_error()
            return 0

    def send_batch(self, packets: list[bytes]) -> int:
        """Send a batch of packets via DPDK TX burst.

        Args:
            packets: List of Ethernet frame byte strings.

        Returns:
            Number of packets successfully sent.
        """
        if not self._is_open or self._tx_engine is None:
            raise TransportError("DPDK transport is not open")

        # Rate limiting for batch
        if self._rate_limiter:
            for pkt in packets:
                self._rate_limiter.wait(len(pkt))

        nb_sent = self._tx_engine.send_batch(packets)

        for i in range(nb_sent):
            self._stats.record_tx(len(packets[i]))
        for i in range(nb_sent, len(packets)):
            self._stats.record_tx_error()

        return nb_sent

    def receive(self, timeout: float = 1.0) -> Optional[bytes]:
        """Receive a packet via DPDK RX burst.

        Args:
            timeout: Not directly used (DPDK polling is non-blocking).

        Returns:
            Received packet bytes, or None.
        """
        if not self._is_open or self._tx_engine is None:
            return None

        import time
        deadline = time.time() + timeout

        while time.time() < deadline:
            packets = self._tx_engine.receive_burst(max_pkts=1)
            if packets:
                self._stats.record_rx(len(packets[0]))
                return packets[0]
            time.sleep(0.0001)  # 100us poll interval

        return None

    def close(self) -> None:
        """Shut down DPDK port and clean up resources."""
        if self._port_mgr and self._port_id is not None:
            try:
                self._port_mgr.stop_port(self._port_id)
                self._port_mgr.close_port(self._port_id)
            except Exception as e:
                logger.warning("Error closing DPDK port: %s", e)

        if self._eal:
            self._eal.cleanup()

        self._is_open = False
        logger.info("DPDK transport closed")

    def get_info(self) -> dict:
        """Get DPDK transport information."""
        info = super().get_info()
        info["dpdk"] = {
            "port_id": self._port_id,
            "eal_initialized": EALManager.is_initialized(),
        }
        if self._port_mgr:
            info["dpdk"]["port_stats"] = self._port_mgr.get_stats(self._port_id)
        if self._tx_engine:
            info["dpdk"]["engine_stats"] = self._tx_engine.get_stats()
        return info


# Register DPDK transport
from ...core.registry import transport_registry
transport_registry.register("dpdk", DPDKTransport)

__all__ = [
    "DPDKTransport",
    "EALManager",
    "MempoolManager",
    "PortManager",
    "TxRxEngine",
    "RateLimiter",
    "HugepageManager",
    "DriverManager",
    "DPDKError",
    "DPDKLoadError",
]
