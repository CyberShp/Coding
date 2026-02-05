"""Monitoring and statistics API endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/stats")
async def get_stats(request: Request):
    """Get current statistics snapshot."""
    stats = request.app.state.stats_collector
    if stats is None:
        return {"message": "Stats collector not initialized", "stats": {}}
    return stats.get_snapshot()


@router.post("/stats/reset")
async def reset_stats(request: Request):
    """Reset all statistics counters."""
    stats = request.app.state.stats_collector
    if stats is None:
        raise HTTPException(status_code=503, detail="Stats collector not initialized")

    stats.reset()
    return {"status": "ok", "message": "Statistics reset"}


@router.get("/flows")
async def list_flows(request: Request, state: Optional[str] = None):
    """List tracked TCP flows.

    Query params:
        state: Filter by flow state (ESTABLISHED, SYN_SENT, etc.)
    """
    # Flow tracker would be attached to app state in full integration
    return {"flows": [], "message": "Flow tracker available via capture module"}


@router.post("/export/csv")
async def export_csv(request: Request):
    """Export statistics to CSV."""
    from ...monitor.exporter import StatsExporter

    stats = request.app.state.stats_collector
    if stats is None:
        raise HTTPException(status_code=503, detail="Stats collector not initialized")

    exporter = StatsExporter()
    exporter.record_snapshot(stats.get_snapshot())
    filepath = exporter.export_csv()

    return {"status": "ok", "file": filepath}


@router.post("/export/json")
async def export_json(request: Request):
    """Export statistics to JSON."""
    from ...monitor.exporter import StatsExporter

    stats = request.app.state.stats_collector
    if stats is None:
        raise HTTPException(status_code=503, detail="Stats collector not initialized")

    exporter = StatsExporter()
    exporter.record_snapshot(stats.get_snapshot())
    filepath = exporter.export_json()

    return {"status": "ok", "file": filepath}
