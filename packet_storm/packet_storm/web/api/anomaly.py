"""Anomaly type listing and management API endpoints."""

from typing import Optional

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/list")
async def list_anomalies(request: Request, category: Optional[str] = None):
    """List all available anomaly types.

    Query params:
        category: Filter by category (generic, iscsi, nvmeof, nas).
    """
    _ensure_imports()

    from ...anomaly.registry import list_anomalies as _list
    anomalies = _list(category)
    return {"anomalies": anomalies, "total": len(anomalies)}


@router.get("/categories")
async def list_categories(request: Request):
    """List available anomaly categories."""
    _ensure_imports()

    from ...anomaly.registry import list_anomalies as _list
    all_anomalies = _list()
    categories = sorted(set(a["category"] for a in all_anomalies))
    return {"categories": categories}


@router.get("/protocols")
async def list_protocols(request: Request):
    """List registered protocol builders."""
    _ensure_imports()

    from ...core.registry import protocol_registry
    names = protocol_registry.list_names()
    protocols = []
    for name in names:
        cls = protocol_registry.get(name)
        protocols.append({
            "name": name,
            "class": cls.__name__ if cls else "unknown",
        })
    return {"protocols": protocols}


@router.get("/transports")
async def list_transports(request: Request):
    """List registered transport backends."""
    _ensure_imports()

    from ...core.registry import transport_registry
    names = transport_registry.list_names()
    transports = []
    for name in names:
        cls = transport_registry.get(name)
        transports.append({
            "name": name,
            "class": cls.__name__ if cls else "unknown",
        })
    return {"transports": transports}


@router.get("/packet-types/{protocol}")
async def list_packet_types(protocol: str):
    """List packet types for a specific protocol."""
    _ensure_imports()

    from ...core.registry import protocol_registry
    cls = protocol_registry.get(protocol)
    if cls is None:
        return {"error": f"Protocol '{protocol}' not found"}

    try:
        instance = cls(
            network_config={"src_ip": "0.0.0.0", "dst_ip": "0.0.0.0",
                            "src_mac": "00:00:00:00:00:00", "dst_mac": "00:00:00:00:00:00"},
            protocol_config={},
        )
        types = instance.list_packet_types()
        fields = instance.list_fields()
        return {"protocol": protocol, "packet_types": types, "fields": fields}
    except Exception as e:
        return {"error": str(e)}


def _ensure_imports():
    """Import modules for registration."""
    try:
        import packet_storm.protocols.iscsi  # noqa: F401
        import packet_storm.transport  # noqa: F401
        import packet_storm.anomaly  # noqa: F401
    except ImportError:
        pass
