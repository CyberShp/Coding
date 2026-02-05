"""DPDK memory pool and mbuf management."""

import ctypes
from ctypes import c_void_p, c_uint, c_uint16, c_int, c_char_p
from typing import Optional

from .binding import get_dpdk_lib, NUM_MBUFS, MBUF_CACHE_SIZE, MBUF_SIZE, SOCKET_ID_ANY
from .eal import DPDKError
from ...utils.logging import get_logger

logger = get_logger("transport.dpdk.mempool")


class MempoolManager:
    """Manages DPDK memory pools for packet buffer (mbuf) allocation.

    Each mempool is a pre-allocated pool of fixed-size packet buffers
    backed by hugepages for zero-copy, NUMA-aware performance.
    """

    def __init__(self):
        self._pools: dict[str, c_void_p] = {}
        self._default_pool: Optional[c_void_p] = None

    def create_pool(
        self,
        name: str = "pkt_pool",
        num_mbufs: int = NUM_MBUFS,
        cache_size: int = MBUF_CACHE_SIZE,
        data_room_size: int = MBUF_SIZE,
        socket_id: int = SOCKET_ID_ANY,
    ) -> c_void_p:
        """Create a packet buffer memory pool.

        Args:
            name: Pool name (must be unique).
            num_mbufs: Number of mbufs in the pool.
            cache_size: Per-core cache size.
            data_room_size: Size of data room in each mbuf.
            socket_id: NUMA socket ID (-1 for any).

        Returns:
            Pointer to the created mempool.

        Raises:
            DPDKError: If pool creation fails.
        """
        lib = get_dpdk_lib()

        pool = lib.rte_pktmbuf_pool_create(
            name.encode("utf-8"),
            num_mbufs,
            cache_size,
            0,                  # priv_size
            data_room_size,
            socket_id,
        )

        if pool is None or pool == 0:
            raise DPDKError(
                f"Failed to create mempool '{name}' "
                f"(num_mbufs={num_mbufs}, size={data_room_size}). "
                f"Check hugepage allocation."
            )

        self._pools[name] = pool
        if self._default_pool is None:
            self._default_pool = pool

        logger.info(
            "Created mempool '%s': %d mbufs, %d bytes each, socket %d",
            name, num_mbufs, data_room_size, socket_id,
        )
        return pool

    def get_pool(self, name: Optional[str] = None) -> c_void_p:
        """Get a mempool by name.

        Args:
            name: Pool name. If None, returns the default pool.

        Returns:
            Pointer to the mempool.

        Raises:
            DPDKError: If pool not found.
        """
        if name is None:
            if self._default_pool is None:
                raise DPDKError("No default mempool created")
            return self._default_pool

        pool = self._pools.get(name)
        if pool is None:
            raise DPDKError(f"Mempool '{name}' not found")
        return pool

    def alloc_mbuf(self, pool_name: Optional[str] = None) -> c_void_p:
        """Allocate a single mbuf from a pool.

        Args:
            pool_name: Pool to allocate from (None for default).

        Returns:
            Pointer to allocated mbuf.

        Raises:
            DPDKError: If allocation fails.
        """
        lib = get_dpdk_lib()
        pool = self.get_pool(pool_name)

        mbuf = lib.rte_pktmbuf_alloc(pool)
        if mbuf is None or mbuf == 0:
            raise DPDKError("Failed to allocate mbuf (pool may be exhausted)")
        return mbuf

    def free_mbuf(self, mbuf: c_void_p) -> None:
        """Free a single mbuf back to its pool.

        Args:
            mbuf: Pointer to mbuf to free.
        """
        if mbuf and mbuf != 0:
            lib = get_dpdk_lib()
            lib.rte_pktmbuf_free(mbuf)

    def write_mbuf(self, mbuf: c_void_p, data: bytes) -> int:
        """Write packet data into an mbuf.

        Uses rte_pktmbuf_mtod to get the data pointer and copies
        the packet bytes into the mbuf.

        Args:
            mbuf: Pointer to allocated mbuf.
            data: Packet bytes to write.

        Returns:
            Number of bytes written.
        """
        # mbuf structure layout (simplified):
        # The data pointer is at a known offset in the rte_mbuf struct.
        # We use a simpler approach: cast mbuf to get buf_addr + data_off
        # then memcpy the data.

        # rte_mbuf offsets (DPDK 23.11):
        # buf_addr is at offset 0
        # data_off is at offset 16 (uint16_t)
        # pkt_len is at offset 36 (uint32_t)
        # data_len is at offset 40 (uint16_t)

        buf_addr = ctypes.cast(mbuf, ctypes.POINTER(ctypes.c_uint64))[0]
        data_off_ptr = ctypes.cast(
            mbuf + 16, ctypes.POINTER(ctypes.c_uint16)
        )
        data_off = data_off_ptr[0]

        # Calculate data pointer
        data_ptr = buf_addr + data_off

        # Copy data
        data_len = len(data)
        ctypes.memmove(data_ptr, data, data_len)

        # Update mbuf pkt_len and data_len
        pkt_len_ptr = ctypes.cast(mbuf + 36, ctypes.POINTER(ctypes.c_uint32))
        data_len_ptr = ctypes.cast(mbuf + 40, ctypes.POINTER(ctypes.c_uint16))
        pkt_len_ptr[0] = data_len
        data_len_ptr[0] = data_len

        return data_len

    @property
    def pool_names(self) -> list[str]:
        """List all created pool names."""
        return list(self._pools.keys())
