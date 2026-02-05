"""Session control API endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class StartRequest(BaseModel):
    """Request body for starting a session."""
    protocol: Optional[str] = None
    packet_type: Optional[str] = None
    count: Optional[int] = None
    interval_ms: Optional[float] = None
    duration_seconds: Optional[float] = None
    backend: Optional[str] = None


@router.get("/status")
async def get_session_status(request: Request):
    """Get current session status and statistics."""
    engine = request.app.state.engine
    if engine is None:
        return {"session": None, "message": "Engine not initialized"}
    return engine.get_status()


@router.post("/start")
async def start_session(request: Request, body: StartRequest = StartRequest()):
    """Start a new packet sending session."""
    engine = request.app.state.engine
    cfg = request.app.state.config_manager

    if engine is None or cfg is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        # Apply overrides
        if body.protocol:
            cfg.set("protocol.type", body.protocol)
        if body.count:
            cfg.set("execution.repeat", body.count)
        if body.interval_ms is not None:
            cfg.set("execution.interval_ms", body.interval_ms)
        if body.duration_seconds is not None:
            cfg.set("execution.duration_seconds", body.duration_seconds)
        if body.backend:
            cfg.set("transport.backend", body.backend)

        # Import protocols for registration
        _ensure_imports()

        engine.setup()
        engine.start()

        return {"status": "started", "session": engine.get_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_session(request: Request):
    """Stop the current session."""
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        engine.stop()
        return {"status": "stopped", "session": engine.get_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause")
async def pause_session(request: Request):
    """Pause the current session."""
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        engine.pause()
        return {"status": "paused", "session": engine.get_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume")
async def resume_session(request: Request):
    """Resume a paused session."""
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        engine.resume()
        return {"status": "resumed", "session": engine.get_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/step")
async def step_session(request: Request):
    """Send a single packet (step mode)."""
    engine = request.app.state.engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    try:
        engine.step()
        return {"status": "step", "session": engine.get_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _ensure_imports():
    """Import protocol and anomaly modules for registration."""
    try:
        import packet_storm.protocols.iscsi  # noqa: F401
        import packet_storm.transport  # noqa: F401
        import packet_storm.anomaly  # noqa: F401
    except ImportError:
        pass
