"""DPDK EAL (Environment Abstraction Layer) initialization and cleanup."""

import ctypes
from ctypes import c_char_p, c_int, POINTER
from typing import Optional

from .binding import get_dpdk_lib, DPDKLoadError
from ...utils.logging import get_logger

logger = get_logger("transport.dpdk.eal")


class EALManager:
    """Manages DPDK EAL initialization and cleanup.

    EAL must be initialized exactly once before any DPDK operations.
    This class provides a safe initialization interface with
    argument building from configuration.
    """

    _initialized = False

    def __init__(self, eal_args: Optional[list[str]] = None):
        """Initialize EAL manager.

        Args:
            eal_args: EAL arguments (e.g., ['-l', '0-3', '-n', '4']).
                If None, uses minimal defaults.
        """
        self._args = eal_args or ["-l", "0", "-n", "1", "--no-huge", "--no-pci"]

    def init(self) -> int:
        """Initialize DPDK EAL.

        Returns:
            Number of parsed arguments on success.

        Raises:
            DPDKError: If initialization fails.
        """
        if EALManager._initialized:
            logger.warning("EAL already initialized, skipping")
            return 0

        lib = get_dpdk_lib()

        # Build argv in C format
        # First arg is program name
        full_args = ["packet_storm"] + self._args
        argc = len(full_args)

        # Create C string array
        ArgvType = c_char_p * (argc + 1)
        argv = ArgvType()
        for i, arg in enumerate(full_args):
            argv[i] = arg.encode("utf-8")
        argv[argc] = None  # NULL terminator

        logger.info("Initializing DPDK EAL with args: %s", " ".join(full_args))

        ret = lib.rte_eal_init(argc, argv)
        if ret < 0:
            raise DPDKError(f"rte_eal_init failed with return code {ret}")

        EALManager._initialized = True
        logger.info("DPDK EAL initialized successfully (parsed %d args)", ret)
        return ret

    def cleanup(self) -> None:
        """Clean up DPDK EAL resources."""
        if not EALManager._initialized:
            return

        try:
            lib = get_dpdk_lib()
            ret = lib.rte_eal_cleanup()
            if ret < 0:
                logger.warning("rte_eal_cleanup returned %d", ret)
            else:
                logger.info("DPDK EAL cleaned up")
        except Exception as e:
            logger.warning("EAL cleanup error: %s", e)
        finally:
            EALManager._initialized = False

    @staticmethod
    def is_initialized() -> bool:
        """Check if EAL has been initialized."""
        return EALManager._initialized

    @staticmethod
    def build_eal_args(
        cores: str = "0",
        memory_channels: int = 4,
        hugepage_size: str = "2M",
        extra_args: Optional[list[str]] = None,
    ) -> list[str]:
        """Build EAL arguments from configuration.

        Args:
            cores: Core list (e.g., '0-3', '0,2,4').
            memory_channels: Number of memory channels.
            hugepage_size: Hugepage size ('2M' or '1G').
            extra_args: Additional EAL arguments.

        Returns:
            List of EAL argument strings.
        """
        args = [
            "-l", cores,
            "-n", str(memory_channels),
        ]

        if hugepage_size == "1G":
            args.extend(["--huge-dir", "/dev/hugepages1G"])

        if extra_args:
            args.extend(extra_args)

        return args


class DPDKError(Exception):
    """Raised when a DPDK operation fails."""
    pass
