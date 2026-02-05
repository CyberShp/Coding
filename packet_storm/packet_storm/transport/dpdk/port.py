"""DPDK Ethernet port configuration and management."""

import ctypes
from ctypes import c_uint16, c_uint, c_void_p, POINTER
from typing import Optional

from .binding import (
    get_dpdk_lib,
    rte_eth_conf,
    rte_eth_stats,
    rte_ether_addr,
)
from .eal import DPDKError
from ...utils.logging import get_logger

logger = get_logger("transport.dpdk.port")


class PortManager:
    """Manages DPDK Ethernet port lifecycle: configure, start, stop, close.

    Handles port discovery, queue setup, and statistics collection.
    """

    def __init__(self):
        self._configured_ports: dict[int, dict] = {}

    def get_available_ports(self) -> int:
        """Get number of available DPDK Ethernet ports.

        Returns:
            Number of available ports.
        """
        lib = get_dpdk_lib()
        count = lib.rte_eth_dev_count_avail()
        logger.info("Available DPDK ports: %d", count)
        return count

    def configure_port(
        self,
        port_id: int,
        nb_rx_queues: int = 1,
        nb_tx_queues: int = 1,
        mempool: Optional[c_void_p] = None,
        rx_ring_size: int = 1024,
        tx_ring_size: int = 1024,
    ) -> None:
        """Configure an Ethernet port with RX/TX queues.

        Args:
            port_id: DPDK port ID.
            nb_rx_queues: Number of RX queues.
            nb_tx_queues: Number of TX queues.
            mempool: Memory pool for RX buffers.
            rx_ring_size: Size of each RX ring.
            tx_ring_size: Size of each TX ring.

        Raises:
            DPDKError: If configuration fails.
        """
        lib = get_dpdk_lib()

        # Port configuration
        port_conf = rte_eth_conf()
        ctypes.memset(ctypes.byref(port_conf), 0, ctypes.sizeof(port_conf))

        ret = lib.rte_eth_dev_configure(port_id, nb_rx_queues, nb_tx_queues,
                                         ctypes.byref(port_conf))
        if ret != 0:
            raise DPDKError(f"rte_eth_dev_configure failed for port {port_id}: {ret}")

        # Setup TX queues
        for q in range(nb_tx_queues):
            ret = lib.rte_eth_tx_queue_setup(
                port_id, q, tx_ring_size, 0, None  # socket_id=0, default tx_conf
            )
            if ret != 0:
                raise DPDKError(f"TX queue {q} setup failed for port {port_id}: {ret}")

        # Setup RX queues (if mempool provided)
        if mempool:
            for q in range(nb_rx_queues):
                ret = lib.rte_eth_rx_queue_setup(
                    port_id, q, rx_ring_size, 0, None, mempool
                )
                if ret != 0:
                    raise DPDKError(f"RX queue {q} setup failed for port {port_id}: {ret}")

        self._configured_ports[port_id] = {
            "nb_rx_queues": nb_rx_queues,
            "nb_tx_queues": nb_tx_queues,
            "rx_ring_size": rx_ring_size,
            "tx_ring_size": tx_ring_size,
        }

        logger.info(
            "Port %d configured: %d RX queues, %d TX queues",
            port_id, nb_rx_queues, nb_tx_queues,
        )

    def start_port(self, port_id: int) -> None:
        """Start an Ethernet port.

        Args:
            port_id: DPDK port ID.

        Raises:
            DPDKError: If start fails.
        """
        lib = get_dpdk_lib()

        ret = lib.rte_eth_dev_start(port_id)
        if ret != 0:
            raise DPDKError(f"rte_eth_dev_start failed for port {port_id}: {ret}")

        # Enable promiscuous mode
        lib.rte_eth_promiscuous_enable(port_id)

        logger.info("Port %d started (promiscuous mode)", port_id)

    def stop_port(self, port_id: int) -> None:
        """Stop an Ethernet port.

        Args:
            port_id: DPDK port ID.
        """
        lib = get_dpdk_lib()

        try:
            lib.rte_eth_dev_stop(port_id)
            logger.info("Port %d stopped", port_id)
        except Exception as e:
            logger.warning("Error stopping port %d: %s", port_id, e)

    def close_port(self, port_id: int) -> None:
        """Close an Ethernet port and release resources.

        Args:
            port_id: DPDK port ID.
        """
        lib = get_dpdk_lib()

        try:
            lib.rte_eth_dev_close(port_id)
            self._configured_ports.pop(port_id, None)
            logger.info("Port %d closed", port_id)
        except Exception as e:
            logger.warning("Error closing port %d: %s", port_id, e)

    def get_mac_address(self, port_id: int) -> str:
        """Get the MAC address of a port.

        Args:
            port_id: DPDK port ID.

        Returns:
            MAC address string.
        """
        lib = get_dpdk_lib()

        mac = rte_ether_addr()
        ret = lib.rte_eth_macaddr_get(port_id, ctypes.byref(mac))
        if ret != 0:
            return "00:00:00:00:00:00"

        return ":".join(f"{b:02x}" for b in mac.addr_bytes)

    def get_stats(self, port_id: int) -> dict:
        """Get port statistics.

        Args:
            port_id: DPDK port ID.

        Returns:
            Dictionary of port statistics.
        """
        lib = get_dpdk_lib()

        stats = rte_eth_stats()
        ret = lib.rte_eth_stats_get(port_id, ctypes.byref(stats))
        if ret != 0:
            return {}

        return {
            "rx_packets": stats.ipackets,
            "tx_packets": stats.opackets,
            "rx_bytes": stats.ibytes,
            "tx_bytes": stats.obytes,
            "rx_missed": stats.imissed,
            "rx_errors": stats.ierrors,
            "tx_errors": stats.oerrors,
            "rx_no_mbuf": stats.rx_nombuf,
        }

    def reset_stats(self, port_id: int) -> None:
        """Reset port statistics.

        Args:
            port_id: DPDK port ID.
        """
        lib = get_dpdk_lib()
        lib.rte_eth_stats_reset(port_id)
