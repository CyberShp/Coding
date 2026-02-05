"""DPDK TX/RX burst operations for high-speed packet sending/receiving."""

import ctypes
import time
from ctypes import c_void_p, c_uint16, POINTER
from typing import Optional

from .binding import get_dpdk_lib
from .mempool import MempoolManager
from .eal import DPDKError
from ...utils.logging import get_logger

logger = get_logger("transport.dpdk.tx_rx")


class TxRxEngine:
    """High-speed TX/RX engine using DPDK burst operations.

    Provides methods for sending and receiving packets at line rate
    with support for batching and rate limiting.
    """

    def __init__(
        self,
        port_id: int,
        mempool: MempoolManager,
        max_burst: int = 32,
    ):
        """Initialize TX/RX engine.

        Args:
            port_id: DPDK port ID.
            mempool: Memory pool manager.
            max_burst: Maximum burst size for TX/RX.
        """
        self.port_id = port_id
        self.mempool = mempool
        self.max_burst = max_burst

        # Statistics
        self.tx_packets = 0
        self.tx_bytes = 0
        self.tx_errors = 0
        self.rx_packets = 0
        self.rx_bytes = 0

    def send_packet(self, data: bytes, queue_id: int = 0) -> bool:
        """Send a single packet.

        Args:
            data: Raw packet bytes (complete Ethernet frame).
            queue_id: TX queue ID.

        Returns:
            True if packet was sent successfully.
        """
        lib = get_dpdk_lib()

        try:
            # Allocate mbuf
            mbuf = self.mempool.alloc_mbuf()

            # Write packet data into mbuf
            self.mempool.write_mbuf(mbuf, data)

            # Create array of mbuf pointers for tx_burst
            tx_pkts = (c_void_p * 1)(mbuf)

            # Send
            nb_tx = lib.rte_eth_tx_burst(
                self.port_id, queue_id, tx_pkts, 1
            )

            if nb_tx > 0:
                self.tx_packets += 1
                self.tx_bytes += len(data)
                return True
            else:
                # Free unsent mbuf
                self.mempool.free_mbuf(mbuf)
                self.tx_errors += 1
                return False

        except Exception as e:
            self.tx_errors += 1
            logger.debug("TX error: %s", e)
            return False

    def send_batch(self, packets: list[bytes], queue_id: int = 0) -> int:
        """Send a batch of packets using TX burst.

        Args:
            packets: List of raw packet byte strings.
            queue_id: TX queue ID.

        Returns:
            Number of packets successfully sent.
        """
        lib = get_dpdk_lib()

        if not packets:
            return 0

        nb_pkts = min(len(packets), self.max_burst)

        try:
            # Allocate mbufs for all packets
            mbufs = []
            for i in range(nb_pkts):
                mbuf = self.mempool.alloc_mbuf()
                self.mempool.write_mbuf(mbuf, packets[i])
                mbufs.append(mbuf)

            # Create array of mbuf pointers
            TxArray = c_void_p * nb_pkts
            tx_pkts = TxArray(*mbufs)

            # Burst send
            nb_tx = lib.rte_eth_tx_burst(
                self.port_id, queue_id, tx_pkts, nb_pkts
            )

            # Free unsent mbufs
            for i in range(nb_tx, nb_pkts):
                self.mempool.free_mbuf(mbufs[i])

            self.tx_packets += nb_tx
            self.tx_bytes += sum(len(packets[i]) for i in range(nb_tx))
            self.tx_errors += nb_pkts - nb_tx

            return nb_tx

        except Exception as e:
            self.tx_errors += nb_pkts
            logger.debug("TX batch error: %s", e)
            return 0

    def receive_burst(self, max_pkts: int = 32, queue_id: int = 0) -> list[bytes]:
        """Receive a burst of packets.

        Args:
            max_pkts: Maximum packets to receive.
            queue_id: RX queue ID.

        Returns:
            List of received packet byte strings.
        """
        lib = get_dpdk_lib()

        nb_pkts = min(max_pkts, self.max_burst)
        RxArray = c_void_p * nb_pkts
        rx_pkts = RxArray()

        nb_rx = lib.rte_eth_rx_burst(
            self.port_id, queue_id, rx_pkts, nb_pkts
        )

        packets = []
        for i in range(nb_rx):
            mbuf = rx_pkts[i]
            # Read packet data from mbuf
            # Similar to write_mbuf but in reverse
            try:
                buf_addr = ctypes.cast(mbuf, ctypes.POINTER(ctypes.c_uint64))[0]
                data_off = ctypes.cast(mbuf + 16, ctypes.POINTER(ctypes.c_uint16))[0]
                data_len = ctypes.cast(mbuf + 40, ctypes.POINTER(ctypes.c_uint16))[0]

                data_ptr = buf_addr + data_off
                data = ctypes.string_at(data_ptr, data_len)
                packets.append(data)

                self.rx_packets += 1
                self.rx_bytes += data_len
            finally:
                self.mempool.free_mbuf(mbuf)

        return packets

    def get_stats(self) -> dict:
        """Get TX/RX engine statistics."""
        return {
            "tx_packets": self.tx_packets,
            "tx_bytes": self.tx_bytes,
            "tx_errors": self.tx_errors,
            "rx_packets": self.rx_packets,
            "rx_bytes": self.rx_bytes,
        }

    def reset_stats(self) -> None:
        """Reset TX/RX statistics."""
        self.tx_packets = 0
        self.tx_bytes = 0
        self.tx_errors = 0
        self.rx_packets = 0
        self.rx_bytes = 0


class RateLimiter:
    """Token bucket rate limiter for controlling send rate.

    Supports rate limiting in packets per second (pps) or
    megabits per second (mbps).
    """

    def __init__(self, mode: str = "pps", rate: int = 100000):
        """Initialize rate limiter.

        Args:
            mode: Rate mode ('pps' or 'mbps').
            rate: Rate limit value.
        """
        self.mode = mode
        self.rate = rate

        # Token bucket
        self._tokens: float = 0
        self._max_tokens: float = rate  # Allow burst up to 1 second
        self._last_refill: float = time.time()

        # For mbps mode, convert to bytes per second
        self._bytes_per_second = (rate * 1_000_000) / 8 if mode == "mbps" else 0

    def acquire(self, packet_size: int = 0) -> bool:
        """Try to acquire a send token.

        Args:
            packet_size: Size of packet in bytes (for mbps mode).

        Returns:
            True if sending is allowed, False if rate limit exceeded.
        """
        now = time.time()
        elapsed = now - self._last_refill
        self._last_refill = now

        # Refill tokens
        if self.mode == "pps":
            self._tokens = min(
                self._max_tokens,
                self._tokens + elapsed * self.rate,
            )
            cost = 1.0
        else:  # mbps
            self._tokens = min(
                self._max_tokens * (self._bytes_per_second / self.rate),
                self._tokens + elapsed * self._bytes_per_second,
            )
            cost = float(packet_size)

        # Try to consume
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    def wait(self, packet_size: int = 0) -> None:
        """Wait until a send token is available.

        Args:
            packet_size: Size of packet in bytes (for mbps mode).
        """
        while not self.acquire(packet_size):
            time.sleep(0.000001)  # 1 microsecond

    def set_rate(self, rate: int) -> None:
        """Update the rate limit.

        Args:
            rate: New rate limit value.
        """
        self.rate = rate
        self._max_tokens = rate
        if self.mode == "mbps":
            self._bytes_per_second = (rate * 1_000_000) / 8
