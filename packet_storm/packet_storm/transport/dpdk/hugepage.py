"""Hugepage setup helper for DPDK."""

import os
import subprocess
from typing import Optional

from ...utils.logging import get_logger

logger = get_logger("transport.dpdk.hugepage")


class HugepageManager:
    """Helper for configuring hugepages needed by DPDK.

    DPDK requires hugepages for its memory pools. This helper
    provides methods to check and configure hugepages.
    """

    HUGEPAGE_2M_PATH = "/sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"
    HUGEPAGE_1G_PATH = "/sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages"
    MEMINFO_PATH = "/proc/meminfo"
    MOUNT_PATH = "/dev/hugepages"

    def get_status(self) -> dict:
        """Get current hugepage status.

        Returns:
            Dictionary with hugepage information.
        """
        info = {
            "2M": {"total": 0, "free": 0, "configured": 0},
            "1G": {"total": 0, "free": 0, "configured": 0},
            "mounted": False,
        }

        try:
            with open(self.MEMINFO_PATH, "r") as f:
                for line in f:
                    if "HugePages_Total" in line:
                        info["2M"]["total"] = int(line.split(":")[1].strip())
                    elif "HugePages_Free" in line:
                        info["2M"]["free"] = int(line.split(":")[1].strip())
        except (OSError, ValueError):
            pass

        # Check if hugepages are mounted
        try:
            with open("/proc/mounts", "r") as f:
                for line in f:
                    if "hugetlbfs" in line:
                        info["mounted"] = True
                        break
        except OSError:
            pass

        # Check configured count
        for size, path in [("2M", self.HUGEPAGE_2M_PATH), ("1G", self.HUGEPAGE_1G_PATH)]:
            try:
                with open(path, "r") as f:
                    info[size]["configured"] = int(f.read().strip())
            except (OSError, ValueError):
                pass

        return info

    def setup(
        self,
        size: str = "2M",
        count: int = 1024,
        mount: bool = True,
    ) -> bool:
        """Configure hugepages.

        Args:
            size: Hugepage size ('2M' or '1G').
            count: Number of hugepages to allocate.
            mount: Whether to mount the hugetlbfs.

        Returns:
            True if setup was successful.

        Note:
            Requires root privileges.
        """
        path = self.HUGEPAGE_2M_PATH if size == "2M" else self.HUGEPAGE_1G_PATH

        try:
            # Set number of hugepages
            with open(path, "w") as f:
                f.write(str(count))
            logger.info("Set %d x %s hugepages", count, size)

            # Mount hugetlbfs if needed
            if mount and not os.path.ismount(self.MOUNT_PATH):
                os.makedirs(self.MOUNT_PATH, exist_ok=True)
                subprocess.run(
                    ["mount", "-t", "hugetlbfs", "nodev", self.MOUNT_PATH],
                    check=True,
                    timeout=5,
                )
                logger.info("Mounted hugetlbfs at %s", self.MOUNT_PATH)

            return True

        except PermissionError:
            logger.error("Hugepage setup requires root privileges")
            return False
        except (OSError, subprocess.CalledProcessError) as e:
            logger.error("Hugepage setup failed: %s", e)
            return False

    def check_sufficient(self, required_mb: int = 256) -> bool:
        """Check if sufficient hugepages are available.

        Args:
            required_mb: Required memory in megabytes.

        Returns:
            True if sufficient hugepages are available.
        """
        status = self.get_status()
        available_mb = status["2M"]["free"] * 2 + status["1G"]["free"] * 1024
        sufficient = available_mb >= required_mb

        if not sufficient:
            logger.warning(
                "Insufficient hugepages: %d MB available, %d MB required",
                available_mb, required_mb,
            )

        return sufficient
