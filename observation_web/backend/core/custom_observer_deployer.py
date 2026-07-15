"""Atomic custom-observer config deployment and Agent receipt verification."""

import base64
import hashlib
import json
import shlex
import time
from typing import Any, Callable, Dict, List


AGENT_CONFIG_PATH = "/etc/observation-points/config.json"
AGENT_RUNTIME_RECEIPT_PATH = "/var/run/observation-points-runtime.json"


def fingerprint_custom_monitors(monitors: List[Dict[str, Any]]) -> str:
    canonical = json.dumps(monitors, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_agent_config(existing: str, monitors: List[Dict[str, Any]]) -> tuple[dict, str]:
    try:
        config = json.loads(existing) if existing else {}
    except (json.JSONDecodeError, TypeError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    fingerprint = fingerprint_custom_monitors(monitors)
    config["custom_monitors"] = monitors
    config["_observer_studio"] = {
        "config_fingerprint": fingerprint,
        "revision": max((int(item.get("template_version", 0)) for item in monitors), default=0),
    }
    return config, fingerprint


def deploy_agent_config(
    conn,
    monitors: List[Dict[str, Any]],
    restart: Callable[[], Dict[str, Any]],
    receipt_attempts: int = 1,
    receipt_delay: float = 0,
) -> Dict[str, Any]:
    if not conn or not conn.is_connected():
        return {"ok": False, "status": "failed", "error": "Array not connected"}

    existing = conn.read_file(AGENT_CONFIG_PATH) or "{}"
    config, desired_hash = build_agent_config(existing, monitors)
    content = json.dumps(config, indent=2, ensure_ascii=False)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    tmp_path = f"{AGENT_CONFIG_PATH}.tmp"
    commands = [
        f"mkdir -p {shlex.quote(AGENT_CONFIG_PATH.rsplit('/', 1)[0])}",
        f"echo {shlex.quote(encoded)} | base64 -d > {shlex.quote(tmp_path)}",
        f"python3 -c {shlex.quote(f'import json; json.load(open({tmp_path!r}))')}",
        f"cp {shlex.quote(AGENT_CONFIG_PATH)} {shlex.quote(AGENT_CONFIG_PATH + '.bak')} 2>/dev/null || true",
        f"mv {shlex.quote(tmp_path)} {shlex.quote(AGENT_CONFIG_PATH)}",
    ]
    for command in commands:
        code, _, stderr = conn.execute(command)
        if code != 0:
            conn.execute(f"rm -f {shlex.quote(tmp_path)}")
            return {
                "ok": False,
                "status": "failed",
                "desired_hash": desired_hash,
                "error": stderr or f"Config write failed: {command}",
            }

    restart_result = restart() or {}
    if not restart_result.get("ok"):
        return {
            "ok": False,
            "status": "failed",
            "desired_hash": desired_hash,
            "error": restart_result.get("error") or "Agent restart failed",
        }

    receipt = {}
    for attempt in range(max(1, receipt_attempts)):
        raw = conn.read_file(AGENT_RUNTIME_RECEIPT_PATH)
        try:
            receipt = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            receipt = {}
        if receipt.get("config_fingerprint") == desired_hash:
            break
        if attempt + 1 < receipt_attempts and receipt_delay:
            time.sleep(receipt_delay)

    loaded_hash = receipt.get("config_fingerprint", "")
    load_errors = receipt.get("load_errors") or []
    if loaded_hash == desired_hash and not load_errors:
        return {
            "ok": True,
            "status": "active",
            "desired_hash": desired_hash,
            "loaded_hash": loaded_hash,
            "loaded_observers": receipt.get("loaded_observers") or [],
        }
    message = "Agent 未回执目标配置"
    if load_errors:
        message = "; ".join(str(item.get("error") or item) for item in load_errors)
    return {
        "ok": False,
        "status": "degraded",
        "desired_hash": desired_hash,
        "loaded_hash": loaded_hash,
        "error": message,
        "load_errors": load_errors,
    }
