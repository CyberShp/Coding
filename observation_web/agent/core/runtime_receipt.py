"""Agent-side proof of the exact configuration loaded at runtime."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_RUNTIME_RECEIPT_PATH = Path("/var/run/observation-points-runtime.json")


def build_runtime_receipt(
    config: Dict[str, Any],
    loaded_observers: Iterable[str],
    load_errors: List[Dict[str, str]],
) -> Dict[str, Any]:
    studio = config.get("_observer_studio", {}) or {}
    return {
        "config_fingerprint": studio.get("config_fingerprint", ""),
        "config_revision": studio.get("revision", 0),
        "loaded_observers": sorted(set(loaded_observers)),
        "load_errors": load_errors,
        "loaded_at": datetime.now().isoformat(),
        "pid": os.getpid(),
    }


def write_runtime_receipt(path: Path, receipt: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
