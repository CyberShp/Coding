"""DPDK management API endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class BindRequest(BaseModel):
    """Request body for NIC binding."""
    pci_address: str
    driver: str = "vfio-pci"


@router.get("/status")
async def dpdk_status():
    """Get DPDK NIC and hugepage status."""
    from ...transport.dpdk.hugepage import HugepageManager
    from ...transport.dpdk.driver import DriverManager

    hugepage_mgr = HugepageManager()
    driver_mgr = DriverManager()

    return {
        "hugepages": hugepage_mgr.get_status(),
        "nics": driver_mgr.list_dpdk_compatible(),
    }


@router.post("/bind")
async def bind_nic(body: BindRequest):
    """Bind a NIC to a DPDK driver."""
    from ...transport.dpdk.driver import DriverManager

    driver_mgr = DriverManager()
    success = driver_mgr.bind(body.pci_address, body.driver)

    if success:
        return {"status": "ok", "message": f"Bound {body.pci_address} to {body.driver}"}
    else:
        raise HTTPException(status_code=500, detail="Binding failed")


@router.post("/unbind")
async def unbind_nic(body: BindRequest):
    """Unbind a NIC from its current driver."""
    from ...transport.dpdk.driver import DriverManager

    driver_mgr = DriverManager()
    success = driver_mgr.unbind(body.pci_address)

    if success:
        return {"status": "ok", "message": f"Unbound {body.pci_address}"}
    else:
        raise HTTPException(status_code=500, detail="Unbinding failed")


@router.get("/nic/{pci_address}")
async def get_nic_info(pci_address: str):
    """Get information about a specific NIC."""
    from ...transport.dpdk.driver import DriverManager

    driver_mgr = DriverManager()
    info = driver_mgr.get_nic_info(pci_address)
    return info


@router.post("/hugepages/setup")
async def setup_hugepages(size: str = "2M", count: int = 1024):
    """Setup hugepages for DPDK."""
    from ...transport.dpdk.hugepage import HugepageManager

    mgr = HugepageManager()
    success = mgr.setup(size=size, count=count)

    if success:
        return {"status": "ok", "message": f"Configured {count} x {size} hugepages"}
    else:
        raise HTTPException(
            status_code=500,
            detail="Hugepage setup failed. Root privileges required."
        )
