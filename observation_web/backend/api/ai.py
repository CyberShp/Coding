"""
AI API endpoints for alert interpretation and configuration.
"""

import json
import logging
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.ai_service import interpret_alert, is_ai_available, _get_httpx_client_kwargs
from ..api.auth import require_admin
from ..db.database import get_db
from ..models.alert import AlertModel
from ..models.ai_interpretation import AIInterpretationModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])


class InterpretAlertRequest(BaseModel):
    """Request body for interpret-alert endpoint."""
    alert_id: int


class InterpretAlertResponse(BaseModel):
    """Response for interpret-alert endpoint."""
    interpretation: str
    cached: bool = False
    model_name: Optional[str] = None


class AIStatusResponse(BaseModel):
    """Response for AI status endpoint."""
    available: bool
    enabled: bool


class AIConfigResponse(BaseModel):
    """Response for AI config (admin only)."""
    enabled: bool
    api_url: str
    api_key: str
    model: str
    timeout: int
    max_tokens: int
    proxy_mode: str


class AIConfigUpdateRequest(BaseModel):
    """Request to update AI config (admin only)."""
    enabled: Optional[bool] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    timeout: Optional[int] = None
    max_tokens: Optional[int] = None
    proxy_mode: Optional[str] = None


class AIModelInfo(BaseModel):
    """Single model info."""
    id: str
    name: str


@router.get("/status", response_model=AIStatusResponse)
async def get_ai_status():
    """
    Check if AI service is available.
    Frontend uses this to decide whether to show AI interpretation UI.
    """
    config = get_config()
    return AIStatusResponse(
        available=is_ai_available(),
        enabled=config.ai.enabled,
    )


@router.get("/config", response_model=AIConfigResponse)
async def get_ai_config(admin: dict = Depends(require_admin)):
    """Get current AI configuration. Admin only."""
    config = get_config()
    return AIConfigResponse(
        enabled=config.ai.enabled,
        api_url=config.ai.api_url,
        api_key=config.ai.api_key,
        model=config.ai.model,
        timeout=config.ai.timeout,
        max_tokens=config.ai.max_tokens,
        proxy_mode=getattr(config.ai, "proxy_mode", "system"),
    )


@router.put("/config", response_model=AIConfigResponse)
async def update_ai_config(
    body: AIConfigUpdateRequest,
    admin: dict = Depends(require_admin),
):
    """
    Update AI configuration. Admin only.
    Only provided fields are updated; omitted fields keep current values.
    Persists to config.json.
    """
    config = get_config()

    if body.enabled is not None:
        config.ai.enabled = body.enabled
    if body.api_url is not None:
        config.ai.api_url = body.api_url.rstrip("/")
    if body.api_key is not None:
        config.ai.api_key = body.api_key
    if body.model is not None:
        config.ai.model = body.model
    if body.timeout is not None:
        config.ai.timeout = max(5, min(body.timeout, 120))
    if body.max_tokens is not None:
        config.ai.max_tokens = max(100, min(body.max_tokens, 4096))
    if body.proxy_mode is not None:
        mode = body.proxy_mode.lower()
        config.ai.proxy_mode = mode if mode in ("system", "none") else "system"

    try:
        config.save()
    except Exception as e:
        logger.error("Failed to save AI config: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")

    return AIConfigResponse(
        enabled=config.ai.enabled,
        api_url=config.ai.api_url,
        api_key=config.ai.api_key,
        model=config.ai.model,
        timeout=config.ai.timeout,
        max_tokens=config.ai.max_tokens,
        proxy_mode=getattr(config.ai, "proxy_mode", "system"),
    )


@router.get("/models", response_model=List[AIModelInfo])
async def list_ai_models(admin: dict = Depends(require_admin)):
    """
    Fetch available models from the AI API.
    Uses the configured base_url and api_key. Admin only.
    Supports OpenAI-compatible /v1/models endpoint.
    """
    config = get_config()
    api_url = config.ai.api_url
    api_key = config.ai.api_key

    if not api_url:
        raise HTTPException(status_code=400, detail="AI API URL is not configured")

    base_url = api_url.split("/v1/chat")[0] if "/v1/chat" in api_url else api_url.rstrip("/")
    models_url = f"{base_url}/v1/models"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10, **_get_httpx_client_kwargs()) as client:
            resp = await client.get(models_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models = data.get("data", [])
        return [
            AIModelInfo(id=m.get("id", ""), name=m.get("id", ""))
            for m in models
            if m.get("id")
        ]
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI API timeout when fetching models")
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"AI API returned {e.response.status_code}: {e.response.text[:200]}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {e}")


@router.post("/interpret-alert", response_model=InterpretAlertResponse)
async def interpret_alert_endpoint(
    body: InterpretAlertRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Get AI interpretation for an alert.
    Returns cached result if available; otherwise calls AI API and caches.
    Returns 404 if alert not found. Returns 503 if AI unavailable and no cache.
    """
    alert_id = body.alert_id

    # 1. Check cache first
    result = await db.execute(
        select(AIInterpretationModel).where(AIInterpretationModel.alert_id == alert_id)
    )
    cached = result.scalar_one_or_none()
    if cached:
        return InterpretAlertResponse(
            interpretation=cached.interpretation,
            cached=True,
            model_name=cached.model_name or None,
        )

    # 2. Fetch alert
    alert_result = await db.execute(select(AlertModel).where(AlertModel.id == alert_id))
    alert = alert_result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    # 3. AI not available -> return 503 (graceful: frontend shows "暂不可用")
    if not is_ai_available():
        raise HTTPException(
            status_code=503,
            detail="AI service is not available. Enable it in config and ensure API is reachable.",
        )

    # 4. Call AI
    details = {}
    if alert.details:
        try:
            details = json.loads(alert.details) if isinstance(alert.details, str) else alert.details
        except (json.JSONDecodeError, TypeError):
            pass

    interpretation = await interpret_alert(
        observer_name=alert.observer_name,
        level=alert.level,
        message=alert.message or "",
        details=details,
    )

    if not interpretation:
        raise HTTPException(
            status_code=503,
            detail="AI interpretation failed. API may be unreachable or returned an error.",
        )

    # 5. Cache result
    config = get_config()
    ai_record = AIInterpretationModel(
        alert_id=alert_id,
        interpretation=interpretation,
        model_name=config.ai.model,
    )
    db.add(ai_record)
    await db.commit()

    return InterpretAlertResponse(
        interpretation=interpretation,
        cached=False,
        model_name=config.ai.model,
    )
