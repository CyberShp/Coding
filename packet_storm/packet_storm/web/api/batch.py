"""Web API endpoints for batch test orchestration."""

import threading
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from ...core.orchestrator import BatchOrchestrator, BatchResult
from ...utils.logging import get_logger

logger = get_logger("web.api.batch")

router = APIRouter()

# Module-level state for tracking batch runs
_current_batch: Optional[BatchResult] = None
_orchestrator: Optional[BatchOrchestrator] = None
_batch_thread: Optional[threading.Thread] = None


class BatchRunRequest(BaseModel):
    """Request body for starting a batch run."""
    scenarios: list[dict]
    stop_on_failure: bool = False
    inter_scenario_delay: float = 2.0
    batch_id: Optional[str] = None


@router.post("/run")
async def start_batch(req: BatchRunRequest, request: Request):
    """Start a batch test run."""
    global _current_batch, _orchestrator, _batch_thread

    if _batch_thread and _batch_thread.is_alive():
        raise HTTPException(400, "A batch is already running")

    config_mgr = request.app.state.config_manager
    config_path = None
    if config_mgr and hasattr(config_mgr, '_config_path') and config_mgr._config_path:
        config_path = str(config_mgr._config_path)

    _orchestrator = BatchOrchestrator(
        base_config_path=config_path,
        stop_on_failure=req.stop_on_failure,
        inter_scenario_delay=req.inter_scenario_delay,
    )

    def run_batch():
        global _current_batch
        _current_batch = _orchestrator.run_batch(
            req.scenarios, batch_id=req.batch_id
        )

    _batch_thread = threading.Thread(target=run_batch, daemon=True, name="web-batch")
    _batch_thread.start()

    return {"status": "started", "batch_id": req.batch_id or "auto"}


@router.post("/stop")
async def stop_batch():
    """Stop the current batch run."""
    if _orchestrator:
        _orchestrator.stop()
        return {"status": "stop_requested"}
    raise HTTPException(404, "No batch running")


@router.get("/status")
async def get_batch_status():
    """Get current batch status."""
    running = _batch_thread is not None and _batch_thread.is_alive()

    if _current_batch:
        return {
            "running": running,
            "result": _current_batch.to_dict(),
        }
    return {
        "running": running,
        "result": None,
    }
