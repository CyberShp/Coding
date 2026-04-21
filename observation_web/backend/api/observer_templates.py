"""
Observer template builder API (Phase 3).

POST /observer-templates/generate     — NL description → template config (AI-assisted)
POST /observer-templates/test-execute — Test a template command on a live array
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.ai_service import nl_to_observer_template, is_ai_available
from ..core.ssh_pool import get_ssh_pool
from .auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/observer-templates", tags=["observer-templates"])

VALID_STRATEGIES = {"pipe", "kv", "json", "table", "lines", "diff", "exit_code"}

# Commands blocked in test-execute (mirrors ai_service._validate_observer_template)
_DANGEROUS_CMD_RE = re.compile(r"\b(rm\s+-[rf]|mkfs|dd\s+if|shutdown|reboot|format|fdisk)\b")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    description: str


class TestExecuteRequest(BaseModel):
    array_id: str
    command: str
    command_type: str = "shell"
    timeout: int = 30
    strategy: str = "lines"
    strategy_config: Dict[str, Any] = {}
    match_condition: str = "found"
    match_threshold: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_observer_template(
    body: GenerateRequest,
    _payload: dict = Depends(require_admin),
):
    """AI-assisted NL → observer template config."""
    if not body.description or not body.description.strip():
        raise HTTPException(status_code=400, detail="description is required")

    if not is_ai_available():
        raise HTTPException(status_code=503, detail="AI 服务未配置或不可用，无法生成模板")

    template = await nl_to_observer_template(body.description.strip())
    if template is None:
        raise HTTPException(status_code=502, detail="AI 生成失败，请检查描述是否清晰或稍后重试")

    return {"template": template, "description": body.description}


@router.post("/test-execute")
async def test_execute_template(
    body: TestExecuteRequest,
    _payload: dict = Depends(require_admin),
):
    """
    Run the command on a connected array and apply lightweight extraction.
    Returns raw output + extracted value so the user can validate the template.
    Full extraction runs on the agent; this endpoint only does best-effort preview.
    """
    if body.strategy not in VALID_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Invalid strategy: {body.strategy!r}")

    ssh_pool = get_ssh_pool()
    conn = ssh_pool.get_connection(body.array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(status_code=400, detail=f"Array {body.array_id!r} not connected")

    cmd = body.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="command is required")
    if _DANGEROUS_CMD_RE.search(cmd):
        raise HTTPException(status_code=400, detail="Command contains disallowed pattern")

    try:
        ret_code, stdout, stderr = conn.execute(cmd, timeout=body.timeout)
        output = stdout or ""
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Command execution failed: {e}")

    # Best-effort extraction preview (mirrors agent logic, no dependency on agent package)
    extracted_value, extraction_note = _preview_extract(
        body.strategy, output, body.strategy_config
    )

    # Evaluate condition
    condition_met = _eval_condition(
        body.match_condition, extracted_value, body.match_threshold,
        body.strategy, ret_code
    )

    return {
        "success": True,
        "value": extracted_value,
        "raw_output": output[:2000],
        "stderr": (stderr or "")[:500],
        "exit_code": ret_code,
        "strategy": body.strategy,
        "extraction_note": extraction_note,
        "condition_met": condition_met,
    }


# ---------------------------------------------------------------------------
# Lightweight extraction preview (backend-side, mirrors agent extraction.py)
# ---------------------------------------------------------------------------

def _preview_extract(strategy: str, output: str, cfg: Dict) -> tuple:
    """Return (value, note) — best-effort extraction for UI preview."""
    try:
        if strategy == "pipe":
            current: Any = output
            for step in cfg.get("steps", []):
                if "grep" in step and isinstance(current, str):
                    lines = [l for l in current.splitlines() if re.search(step["grep"], l)]
                    current = "\n".join(lines)
                elif "split" in step and isinstance(current, str):
                    sep = step["split"] or None
                    first = current.strip().splitlines()[0] if current.strip() else ""
                    current = first.split(sep) if sep else first.split()
                elif "index" in step and isinstance(current, list):
                    idx = int(step["index"])
                    current = current[idx] if -len(current) <= idx < len(current) else None
                elif step.get("strip") and isinstance(current, str):
                    current = current.strip()
                elif "regex" in step:
                    src = current if isinstance(current, str) else str(current)
                    m = re.search(step["regex"], src)
                    current = m.group(1) if m and m.lastindex else (m.group(0) if m else None)
            return current, ""

        if strategy == "kv":
            key = cfg.get("key", "")
            for line in output.splitlines():
                line = line.strip()
                for sep in [cfg.get("sep")] if cfg.get("sep") else ["=", ":"]:
                    if sep and sep in line:
                        k, _, v = line.partition(sep)
                        if k.strip().lower() == key.lower():
                            return v.strip(), ""
            return None, f"Key {key!r} not found"

        if strategy == "json":
            data = json.loads(output.strip())
            path = cfg.get("path", "$")
            parts = [p for p in path.replace("$", "").split(".") if p]
            current = data
            for part in parts:
                current = current.get(part) if isinstance(current, dict) else None
            return current, ""

        if strategy == "table":
            col_name = cfg.get("column", "")
            lines = [l for l in output.splitlines() if l.strip()]
            if len(lines) < 2:
                return None, "Table needs header + data row"
            headers = lines[0].split()
            col_idx = next((i for i, h in enumerate(headers) if col_name.lower() in h.lower()), None)
            if col_idx is None:
                return None, f"Column {col_name!r} not found"
            data_cols = lines[1].split() if len(lines) > 1 else []
            return data_cols[col_idx] if col_idx < len(data_cols) else None, ""

        if strategy == "lines":
            pattern = cfg.get("pattern", "")
            mode = cfg.get("mode", "count")
            matched = [l.strip() for l in output.splitlines() if re.search(pattern, l)]
            if mode == "count":
                return len(matched), ""
            return matched[0] if matched else None, ""

        if strategy == "diff":
            return output.strip(), "(diff: previous value not available in test mode)"

        if strategy == "exit_code":
            return None, "(exit_code strategy evaluated server-side)"

    except Exception as e:
        return None, f"Extraction preview error: {e}"

    return None, "Unknown strategy"


def _eval_condition(cond: str, value: Any, threshold: Optional[str], strategy: str, exit_code: int) -> bool:
    if strategy == "exit_code":
        try:
            expected = int(threshold) if threshold is not None else 0
        except (ValueError, TypeError):
            expected = 0
        return exit_code == expected if cond == "eq" else (exit_code != expected if cond == "ne" else False)

    if cond == "found":
        # lines strategy returns an int count; treat count>0 as "found"
        # all other strategies: any non-None value (including 0) = found
        if strategy == "lines" and isinstance(value, int):
            return value > 0
        return value is not None
    if cond == "not_found":
        if strategy == "lines" and isinstance(value, int):
            return value == 0
        return value is None

    if threshold is None:
        return False
    try:
        v = float(value) if value is not None else 0
        t = float(threshold)
    except (ValueError, TypeError):
        return False
    return {"gt": v > t, "lt": v < t, "eq": v == t, "ne": v != t}.get(cond, False)
