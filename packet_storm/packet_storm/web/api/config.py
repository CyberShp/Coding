"""Configuration management API endpoints."""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class ConfigSetRequest(BaseModel):
    """Request body for setting a config value."""
    key: str
    value: Any


class ConfigImportRequest(BaseModel):
    """Request body for importing a full config."""
    config: dict


@router.get("/")
async def get_config(request: Request):
    """Get the full current configuration."""
    cfg = request.app.state.config_manager
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config manager not initialized")
    return cfg.config


@router.get("/get/{key_path:path}")
async def get_config_value(request: Request, key_path: str):
    """Get a specific config value by dot-separated path."""
    cfg = request.app.state.config_manager
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config manager not initialized")

    value = cfg.get(key_path)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Config key '{key_path}' not found")
    return {"key": key_path, "value": value}


@router.post("/set")
async def set_config_value(request: Request, body: ConfigSetRequest):
    """Set a specific config value at runtime."""
    cfg = request.app.state.config_manager
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config manager not initialized")

    try:
        cfg.set(body.key, body.value)
        return {"status": "ok", "key": body.key, "value": body.value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import")
async def import_config(request: Request, body: ConfigImportRequest):
    """Import a full configuration, replacing the current one."""
    cfg = request.app.state.config_manager
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config manager not initialized")

    try:
        from ...utils.validation import validate_config
        validate_config(body.config)
        cfg._config = body.config
        return {"status": "ok", "message": "Configuration imported"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/export")
async def export_config(request: Request):
    """Export the current configuration as JSON."""
    cfg = request.app.state.config_manager
    if cfg is None:
        raise HTTPException(status_code=503, detail="Config manager not initialized")
    return cfg.config


@router.post("/validate")
async def validate_config_endpoint(request: Request, body: ConfigImportRequest):
    """Validate a configuration without applying it."""
    try:
        from ...utils.validation import validate_config
        warnings = validate_config(body.config)
        return {"valid": True, "warnings": warnings}
    except Exception as e:
        return {"valid": False, "error": str(e)}
