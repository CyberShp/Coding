"""Small, atomic runtime state store for observer baselines."""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


logger = logging.getLogger(__name__)


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__agent_type__": "datetime", "value": value.isoformat()}
    if isinstance(value, set):
        return {"__agent_type__": "set", "value": [_encode(v) for v in value]}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    value_type = value.get("__agent_type__")
    if value_type == "datetime":
        try:
            return datetime.fromisoformat(value.get("value", ""))
        except (TypeError, ValueError):
            return value.get("value")
    if value_type == "set":
        return set(_decode(v) for v in value.get("value", []))
    return {k: _decode(v) for k, v in value.items()}


class StateStore:
    """Persist all observer state in one atomically replaced JSON file."""

    def __init__(self, path: str, flush_interval: float = 5.0):
        self.path = Path(path)
        self.flush_interval = max(0.1, float(flush_interval))
        self._lock = threading.RLock()
        self._state = {}  # type: Dict[str, Any]
        self._dirty = False
        self._last_flush = 0.0
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._state = _decode(raw)
        except Exception as exc:
            logger.warning("运行状态文件读取失败，将使用空基线: %s", exc)

    def get(self, key: str) -> Dict[str, Any]:
        with self._lock:
            value = self._state.get(key, {})
            return dict(value) if isinstance(value, dict) else {}

    def set(self, key: str, value: Dict[str, Any]):
        with self._lock:
            self._state[key] = value
            self._dirty = True

    def flush(self, force: bool = False):
        with self._lock:
            now = time.monotonic()
            if not self._dirty:
                return
            if not force and now - self._last_flush < self.flush_interval:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
                payload = json.dumps(_encode(self._state), ensure_ascii=False, sort_keys=True)
                with open(tmp_path, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(str(tmp_path), str(self.path))
                self._dirty = False
                self._last_flush = now
            except Exception as exc:
                logger.error("运行状态文件写入失败: %s", exc)
