"""Stable identity helpers for alerts arriving through push or pull."""

import hashlib
import json
from typing import Any, Mapping


def build_source_event_id(array_id: str, payload: Mapping[str, Any]) -> str:
    """Return the agent event id, or a deterministic id for legacy agents."""
    explicit_id = payload.get("event_id") or payload.get("source_event_id")
    if explicit_id:
        return str(explicit_id)

    canonical = {
        "array_id": array_id,
        "observer_name": payload.get("observer_name", "unknown"),
        "level": str(payload.get("level", "info")).lower(),
        "message": payload.get("message", ""),
        "timestamp": payload.get("timestamp", ""),
        "details": payload.get("details") or {},
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"legacy-{hashlib.sha256(encoded).hexdigest()}"
