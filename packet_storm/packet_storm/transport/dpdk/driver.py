"""DPDK NIC driver bind/unbind utilities.

Handles binding network interfaces to DPDK-compatible drivers
(vfio-pci, igb_uio, uio_pci_generic) and restoring kernel drivers.
"""

import os
import subprocess
from typing import Optional

from ...utils.logging import get_logger

logger = get_logger("transport.dpdk.driver")


class DriverManager:
    """Manages NIC driver binding for DPDK.

    DPDK requires NICs to be bound to specific userspace drivers
    (vfio-pci, igb_uio, or uio_pci_generic) instead of kernel drivers.
    """

    DPDK_DRIVERS = {"vfio-pci", "igb_uio", "uio_pci_generic"}
    SYSFS_PCI = "/sys/bus/pci/devices"
    SYSFS_DRIVERS = "/sys/bus/pci/drivers"

    def get_nic_info(self, pci_address: str) -> dict:
        """Get information about a NIC by PCI address.

        Args:
            pci_address: PCI address (e.g., '0000:03:00.0').

        Returns:
            Dictionary with NIC information.
        """
        info = {
            "pci_address": pci_address,
            "driver": self._get_current_driver(pci_address),
            "interface": self._get_interface_name(pci_address),
            "is_dpdk_bound": False,
        }
        info["is_dpdk_bound"] = info["driver"] in self.DPDK_DRIVERS
        return info

    def bind(self, pci_address: str, driver: str = "vfio-pci") -> bool:
        """Bind a NIC to a DPDK-compatible driver.

        Args:
            pci_address: PCI address.
            driver: Target driver name.

        Returns:
            True if binding was successful.
        """
        if driver not in self.DPDK_DRIVERS:
            logger.error("Invalid DPDK driver: %s", driver)
            return False

        # Ensure driver module is loaded
        self._load_driver_module(driver)

        # Unbind from current driver
        current_driver = self._get_current_driver(pci_address)
        if current_driver:
            self._unbind_device(pci_address, current_driver)

        # Bind to new driver
        try:
            bind_path = os.path.join(self.SYSFS_DRIVERS, driver, "bind")
            with open(bind_path, "w") as f:
                f.write(pci_address)
            logger.info("Bound %s to %s", pci_address, driver)
            return True
        except (OSError, PermissionError) as e:
            logger.error("Failed to bind %s to %s: %s", pci_address, driver, e)
            return False

    def unbind(self, pci_address: str) -> bool:
        """Unbind a NIC from its current driver.

        Args:
            pci_address: PCI address.

        Returns:
            True if unbinding was successful.
        """
        current_driver = self._get_current_driver(pci_address)
        if not current_driver:
            logger.warning("Device %s has no driver bound", pci_address)
            return True

        return self._unbind_device(pci_address, current_driver)

    def restore_kernel_driver(self, pci_address: str) -> bool:
        """Restore the kernel driver for a NIC.

        Uses the 'driver_override' and 'probe' mechanism.

        Args:
            pci_address: PCI address.

        Returns:
            True if restoration was successful.
        """
        # Unbind from DPDK driver
        self.unbind(pci_address)

        try:
            # Clear driver override
            override_path = os.path.join(self.SYSFS_PCI, pci_address, "driver_override")
            with open(override_path, "w") as f:
                f.write("")

            # Trigger kernel driver probe
            probe_path = "/sys/bus/pci/drivers_probe"
            with open(probe_path, "w") as f:
                f.write(pci_address)

            logger.info("Restored kernel driver for %s", pci_address)
            return True
        except (OSError, PermissionError) as e:
            logger.error("Failed to restore kernel driver for %s: %s", pci_address, e)
            return False

    def list_dpdk_compatible(self) -> list[dict]:
        """List all DPDK-compatible NICs in the system.

        Returns:
            List of NIC info dictionaries.
        """
        nics = []
        try:
            result = subprocess.run(
                ["lspci", "-Dvmmn"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            current_device: dict = {}
            for line in result.stdout.split("\n"):
                line = line.strip()
                if not line:
                    if current_device and current_device.get("class", "").startswith("02"):
                        # Class 02 = Network controller
                        nics.append(current_device)
                    current_device = {}
                    continue

                if ":" in line:
                    key, _, value = line.partition(":")
                    current_device[key.strip().lower()] = value.strip()

            # Don't forget the last device
            if current_device and current_device.get("class", "").startswith("02"):
                nics.append(current_device)

        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("lspci not available")

        return nics

    def _get_current_driver(self, pci_address: str) -> Optional[str]:
        """Get the current driver bound to a PCI device."""
        driver_link = os.path.join(self.SYSFS_PCI, pci_address, "driver")
        if os.path.islink(driver_link):
            return os.path.basename(os.readlink(driver_link))
        return None

    def _get_interface_name(self, pci_address: str) -> Optional[str]:
        """Get the network interface name for a PCI device."""
        net_path = os.path.join(self.SYSFS_PCI, pci_address, "net")
        if os.path.isdir(net_path):
            interfaces = os.listdir(net_path)
            return interfaces[0] if interfaces else None
        return None

    def _unbind_device(self, pci_address: str, driver: str) -> bool:
        """Unbind a device from a specific driver."""
        try:
            unbind_path = os.path.join(self.SYSFS_DRIVERS, driver, "unbind")
            with open(unbind_path, "w") as f:
                f.write(pci_address)
            logger.info("Unbound %s from %s", pci_address, driver)
            return True
        except (OSError, PermissionError) as e:
            logger.error("Failed to unbind %s from %s: %s", pci_address, driver, e)
            return False

    def _load_driver_module(self, driver: str) -> None:
        """Load the kernel module for a DPDK driver."""
        try:
            subprocess.run(
                ["modprobe", driver],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.debug("Could not modprobe %s", driver)
