"""ctypes/cffi bindings to DPDK shared libraries.

Declares C structures, function prototypes, and constants needed
to interact with libdpdk from Python.
"""

import ctypes
import ctypes.util
from ctypes import (
    c_int, c_uint, c_uint8, c_uint16, c_uint32, c_uint64,
    c_char_p, c_void_p, c_size_t, c_bool,
    POINTER, Structure, Union, CFUNCTYPE,
)
from typing import Optional

from ...utils.logging import get_logger

logger = get_logger("transport.dpdk.binding")


# =============================================================================
# DPDK Library Loading
# =============================================================================

_dpdk_lib: Optional[ctypes.CDLL] = None


def load_dpdk(lib_path: Optional[str] = None) -> ctypes.CDLL:
    """Load the DPDK shared library.

    Args:
        lib_path: Explicit path to librte_eal.so. If None, searches
            standard paths.

    Returns:
        Loaded CDLL object.

    Raises:
        DPDKLoadError: If the library cannot be loaded.
    """
    global _dpdk_lib

    if _dpdk_lib is not None:
        return _dpdk_lib

    search_paths = [
        lib_path,
        "librte_eal.so",
        "/usr/local/lib/librte_eal.so",
        "/usr/local/lib64/librte_eal.so",
        "/usr/lib/x86_64-linux-gnu/librte_eal.so",
    ]

    # Also try versioned names
    for ver in ["23.11", "23", "22.11", "22", "21.11", "21", "20.11", "20"]:
        search_paths.append(f"librte_eal.so.{ver}")

    for path in search_paths:
        if path is None:
            continue
        try:
            _dpdk_lib = ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            logger.info("Loaded DPDK library from: %s", path)

            # Also load ethdev and mbuf libraries
            _load_companion_libs(path)

            _declare_functions(_dpdk_lib)
            return _dpdk_lib
        except OSError:
            continue

    # Try ctypes.util.find_library
    lib_name = ctypes.util.find_library("rte_eal")
    if lib_name:
        try:
            _dpdk_lib = ctypes.CDLL(lib_name, mode=ctypes.RTLD_GLOBAL)
            logger.info("Loaded DPDK library: %s", lib_name)
            _declare_functions(_dpdk_lib)
            return _dpdk_lib
        except OSError:
            pass

    raise DPDKLoadError(
        "Cannot load DPDK library. Ensure DPDK is installed and "
        "librte_eal.so is in the library path. "
        "Set LD_LIBRARY_PATH or use --dpdk-lib-path."
    )


def _load_companion_libs(eal_path: str) -> None:
    """Load companion DPDK libraries (ethdev, mbuf, mempool, ring)."""
    import os
    lib_dir = os.path.dirname(eal_path) if "/" in eal_path else ""

    companion_libs = [
        "librte_mempool.so",
        "librte_ring.so",
        "librte_mbuf.so",
        "librte_ethdev.so",
        "librte_net.so",
    ]

    for lib_name in companion_libs:
        path = os.path.join(lib_dir, lib_name) if lib_dir else lib_name
        try:
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
        except OSError:
            logger.debug("Could not load companion lib: %s", lib_name)


# =============================================================================
# C Structure Definitions
# =============================================================================

class rte_eth_conf(Structure):
    """Simplified rte_eth_conf for port configuration."""
    _fields_ = [
        ("link_speeds", c_uint32),
        ("rxmode_mq_mode", c_uint32),
        ("rxmode_mtu", c_uint32),
        ("rxmode_offloads", c_uint64),
        ("_rxmode_reserved", c_uint64 * 4),
        ("txmode_mq_mode", c_uint32),
        ("txmode_offloads", c_uint64),
        ("_txmode_reserved", c_uint64 * 4),
        ("_reserved", c_uint8 * 256),  # Pad to cover full struct
    ]


class rte_eth_rxconf(Structure):
    """Simplified RX queue configuration."""
    _fields_ = [
        ("rx_thresh_pthresh", c_uint8),
        ("rx_thresh_hthresh", c_uint8),
        ("rx_thresh_wthresh", c_uint8),
        ("rx_free_thresh", c_uint16),
        ("rx_drop_en", c_uint8),
        ("rx_deferred_start", c_uint8),
        ("offloads", c_uint64),
        ("_reserved", c_uint8 * 64),
    ]


class rte_eth_txconf(Structure):
    """Simplified TX queue configuration."""
    _fields_ = [
        ("tx_thresh_pthresh", c_uint8),
        ("tx_thresh_hthresh", c_uint8),
        ("tx_thresh_wthresh", c_uint8),
        ("tx_free_thresh", c_uint16),
        ("tx_rs_thresh", c_uint16),
        ("tx_deferred_start", c_uint8),
        ("offloads", c_uint64),
        ("_reserved", c_uint8 * 64),
    ]


class rte_ether_addr(Structure):
    """Ethernet MAC address."""
    _fields_ = [
        ("addr_bytes", c_uint8 * 6),
    ]


class rte_eth_stats(Structure):
    """Basic port statistics."""
    _fields_ = [
        ("ipackets", c_uint64),
        ("opackets", c_uint64),
        ("ibytes", c_uint64),
        ("obytes", c_uint64),
        ("imissed", c_uint64),
        ("ierrors", c_uint64),
        ("oerrors", c_uint64),
        ("rx_nombuf", c_uint64),
    ]


# =============================================================================
# Constants
# =============================================================================

# EAL constants
RTE_MAX_ETHPORTS = 32
RTE_MAX_QUEUES_PER_PORT = 1024

# mbuf pool defaults
MBUF_CACHE_SIZE = 250
NUM_MBUFS = 8191
MBUF_SIZE = 2048 + 128  # RTE_PKTMBUF_HEADROOM + max packet size

# Socket
SOCKET_ID_ANY = -1


# =============================================================================
# Function Declarations
# =============================================================================

def _declare_functions(lib: ctypes.CDLL) -> None:
    """Declare DPDK function prototypes for type safety.

    This sets argtypes and restype for all DPDK functions we use.
    """
    try:
        # --- EAL ---
        lib.rte_eal_init.argtypes = [c_int, POINTER(c_char_p)]
        lib.rte_eal_init.restype = c_int

        lib.rte_eal_cleanup.argtypes = []
        lib.rte_eal_cleanup.restype = c_int

        # --- Mempool ---
        lib.rte_pktmbuf_pool_create.argtypes = [
            c_char_p,   # name
            c_uint,     # n (number of elements)
            c_uint,     # cache_size
            c_uint16,   # priv_size
            c_uint16,   # data_room_size
            c_int,      # socket_id
        ]
        lib.rte_pktmbuf_pool_create.restype = c_void_p

        lib.rte_pktmbuf_alloc.argtypes = [c_void_p]  # mempool
        lib.rte_pktmbuf_alloc.restype = c_void_p  # mbuf pointer

        lib.rte_pktmbuf_free.argtypes = [c_void_p]  # mbuf
        lib.rte_pktmbuf_free.restype = None

        # --- Ethernet Device ---
        lib.rte_eth_dev_count_avail.argtypes = []
        lib.rte_eth_dev_count_avail.restype = c_uint16

        lib.rte_eth_dev_configure.argtypes = [
            c_uint16,                    # port_id
            c_uint16,                    # nb_rx_queue
            c_uint16,                    # nb_tx_queue
            POINTER(rte_eth_conf),       # eth_conf
        ]
        lib.rte_eth_dev_configure.restype = c_int

        lib.rte_eth_rx_queue_setup.argtypes = [
            c_uint16,                    # port_id
            c_uint16,                    # queue_id
            c_uint16,                    # nb_rx_desc
            c_uint,                      # socket_id
            POINTER(rte_eth_rxconf),     # rx_conf (can be NULL)
            c_void_p,                    # mempool
        ]
        lib.rte_eth_rx_queue_setup.restype = c_int

        lib.rte_eth_tx_queue_setup.argtypes = [
            c_uint16,                    # port_id
            c_uint16,                    # queue_id
            c_uint16,                    # nb_tx_desc
            c_uint,                      # socket_id
            POINTER(rte_eth_txconf),     # tx_conf (can be NULL)
        ]
        lib.rte_eth_tx_queue_setup.restype = c_int

        lib.rte_eth_dev_start.argtypes = [c_uint16]
        lib.rte_eth_dev_start.restype = c_int

        lib.rte_eth_dev_stop.argtypes = [c_uint16]
        lib.rte_eth_dev_stop.restype = c_int

        lib.rte_eth_dev_close.argtypes = [c_uint16]
        lib.rte_eth_dev_close.restype = c_int

        lib.rte_eth_promiscuous_enable.argtypes = [c_uint16]
        lib.rte_eth_promiscuous_enable.restype = c_int

        lib.rte_eth_macaddr_get.argtypes = [c_uint16, POINTER(rte_ether_addr)]
        lib.rte_eth_macaddr_get.restype = c_int

        lib.rte_eth_stats_get.argtypes = [c_uint16, POINTER(rte_eth_stats)]
        lib.rte_eth_stats_get.restype = c_int

        lib.rte_eth_stats_reset.argtypes = [c_uint16]
        lib.rte_eth_stats_reset.restype = c_int

        # --- TX/RX Burst ---
        lib.rte_eth_tx_burst.argtypes = [
            c_uint16,            # port_id
            c_uint16,            # queue_id
            POINTER(c_void_p),   # tx_pkts (array of mbuf pointers)
            c_uint16,            # nb_pkts
        ]
        lib.rte_eth_tx_burst.restype = c_uint16

        lib.rte_eth_rx_burst.argtypes = [
            c_uint16,            # port_id
            c_uint16,            # queue_id
            POINTER(c_void_p),   # rx_pkts (array of mbuf pointers)
            c_uint16,            # nb_pkts
        ]
        lib.rte_eth_rx_burst.restype = c_uint16

        logger.debug("DPDK function declarations set up successfully")

    except AttributeError as e:
        logger.warning("Some DPDK functions not found: %s", e)


def get_dpdk_lib() -> ctypes.CDLL:
    """Get the loaded DPDK library, loading it if necessary."""
    if _dpdk_lib is None:
        return load_dpdk()
    return _dpdk_lib


class DPDKLoadError(Exception):
    """Raised when DPDK library cannot be loaded."""
    pass
