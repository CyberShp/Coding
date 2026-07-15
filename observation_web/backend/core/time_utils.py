"""Timestamp normalization shared by push and SSH ingestion paths."""

from datetime import datetime, timezone
from typing import Optional


def parse_event_timestamp(value: Optional[str], fallback: Optional[datetime] = None) -> datetime:
    """Convert ISO input to the backend's existing naive-local database convention."""
    if not value:
        return fallback or datetime.now()
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        return fallback or datetime.now()


def timestamp_epoch(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None
