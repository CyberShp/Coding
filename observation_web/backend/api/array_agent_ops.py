"""
Agent operations endpoints (deploy, start, stop, restart, logs, agent-config).

Owns:
- POST /arrays/{array_id}/deploy-agent
- POST /arrays/{array_id}/start-agent
- POST /arrays/{array_id}/stop-agent
- POST /arrays/{array_id}/restart-agent
- GET  /arrays/{array_id}/logs
- GET  /arrays/{array_id}/log-files
- GET  /arrays/{array_id}/agent-config
- PUT  /arrays/{array_id}/agent-config
- POST /arrays/{array_id}/agent-config/restore
"""
import asyncio
import json
import logging
import shlex
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.agent_deployer import AgentDeployer
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..core.system_alert import sys_error, sys_info, sys_warning
from ..db.database import get_db

from .array_status import _get_array_status, _get_array_or_404

logger = logging.getLogger(__name__)
agent_router = APIRouter()


# ---------------------------------------------------------------------------
# Shared async helper (local copy to avoid circular import)
# ---------------------------------------------------------------------------

async def _run_blocking(func, _timeout: float, *args, **kwargs):
    """Run sync I/O in threadpool to avoid blocking event loop."""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
        timeout=_timeout,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _apply_observer_overrides(conn, config, db: AsyncSession):
    """After deploy, merge observer_configs overrides into remote config.json."""
    try:
        from .observer_configs import get_all_observer_overrides
        overrides = await get_all_observer_overrides(db)
        if not overrides:
            return
        config_path = "/etc/observation-points/config.json"
        content = await _run_blocking(conn.read_file, 10, config_path)
        if not content:
            return
        config_data = json.loads(content)
        observers = config_data.setdefault("observers", {})
        for obs_name, ov in overrides.items():
            obs = observers.setdefault(obs_name, {})
            obs.update(ov)
        import base64
        config_json = json.dumps(config_data, indent=2, ensure_ascii=False)
        encoded = base64.b64encode(config_json.encode("utf-8")).decode("ascii")
        await _run_blocking(conn.execute, 10, f"echo '{encoded}' | base64 -d > {config_path}")
    except Exception as e:
        logger.warning(f"Failed to apply observer overrides: {e}")


ALLOWED_LOG_PREFIXES = ("/var/log", "/OSM/log")

COMMON_LOG_PATHS = [
    "/var/log/messages",
    "/var/log/syslog",
    "/var/log/dmesg",
    "/var/log/auth.log",
    "/var/log/secure",
    "/var/log/kern.log",
]


def _format_bytes(size: int) -> str:
    """Format bytes to human readable string"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _compute_config_hash(content: str) -> str:
    """Compute MD5 hash of config content for optimistic locking."""
    import hashlib
    return hashlib.md5(content.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# Agent control endpoints
# ---------------------------------------------------------------------------

@agent_router.post("/{array_id}/deploy-agent")
async def deploy_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Deploy observation_points agent to array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.deploy), timeout=120)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Deploy timed out (120s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent deploy failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")},
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Deploy failed"),
        )

    if result.get("warnings"):
        sys_warning(
            "arrays",
            f"Agent deployed for array {array_id} with warnings",
            {"array_id": array_id, "warnings": result["warnings"]},
        )

    await _apply_observer_overrides(conn, config, db)

    status_obj = _get_array_status(array_id)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    sys_info("arrays", f"Agent deployed for array {array_id}", {"array_id": array_id})
    from .websocket import broadcast_status_update
    await broadcast_status_update(array_id, {
        "array_id": array_id,
        "state": status_obj.state.value,
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "event": "agent_deployed",
    })

    return result


@agent_router.post("/{array_id}/start-agent")
async def start_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Start observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.start_agent), timeout=60)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Start agent timed out (60s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent start failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")},
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Start failed"),
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    sys_info("arrays", f"Agent started for array {array_id}", {"array_id": array_id})
    from .websocket import broadcast_status_update
    await broadcast_status_update(array_id, {
        "array_id": array_id,
        "state": status_obj.state.value,
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "event": "agent_started",
    })

    return result


@agent_router.post("/{array_id}/stop-agent")
async def stop_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Stop observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.stop_agent), timeout=30)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Stop agent timed out (30s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent stop failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")},
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Stop failed"),
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    sys_info("arrays", f"Agent stopped for array {array_id}", {"array_id": array_id})
    from .websocket import broadcast_status_update
    await broadcast_status_update(array_id, {
        "array_id": array_id,
        "state": status_obj.state.value,
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "event": "agent_stopped",
    })

    return result


@agent_router.post("/{array_id}/restart-agent")
async def restart_agent(
    array_id: str,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Restart observation_points agent on array"""
    await _get_array_or_404(array_id, db)
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    config = get_config()
    deployer = AgentDeployer(conn, config)
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, deployer.restart_agent), timeout=60)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Restart agent timed out (60s)")
    if not result.get("ok"):
        sys_error(
            "arrays",
            f"Agent restart failed for array {array_id}",
            {"array_id": array_id, "error": result.get("error")},
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Restart failed"),
        )

    status_obj = _get_array_status(array_id)
    status_obj.agent_running = await _run_blocking(deployer.check_running, 10)
    status_obj.agent_deployed = await _run_blocking(deployer.check_deployed, 10)
    sys_info("arrays", f"Agent restarted for array {array_id}", {"array_id": array_id})
    from .websocket import broadcast_status_update
    await broadcast_status_update(array_id, {
        "array_id": array_id,
        "state": status_obj.state.value,
        "agent_deployed": status_obj.agent_deployed,
        "agent_running": status_obj.agent_running,
        "event": "agent_restarted",
    })

    return result


# ---------------------------------------------------------------------------
# Log endpoints
# ---------------------------------------------------------------------------

@agent_router.get("/{array_id}/logs")
async def get_logs(
    array_id: str,
    file_path: str = "/var/log/messages",
    lines: int = 100,
    keyword: Optional[str] = None,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get log content from remote array."""
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    if ".." in file_path or not any(file_path.startswith(p) for p in ALLOWED_LOG_PREFIXES):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file_path: must start with {ALLOWED_LOG_PREFIXES}",
        )

    safe_path = shlex.quote(file_path)
    safe_keyword = shlex.quote(keyword) if keyword else None

    if safe_keyword:
        cmd = f"sudo tail -n {lines * 3} {safe_path} 2>/dev/null | grep -i -e {safe_keyword} | tail -n {lines}"
    else:
        cmd = f"sudo tail -n {lines} {safe_path} 2>/dev/null"

    try:
        exit_code, output, error = await _run_blocking(conn.execute, 12, cmd, timeout=10)
        if error and "permission denied" in error.lower():
            if safe_keyword:
                cmd = f"tail -n {lines * 3} {safe_path} 2>/dev/null | grep -i -e {safe_keyword} | tail -n {lines}"
            else:
                cmd = f"tail -n {lines} {safe_path} 2>/dev/null"
            exit_code, output, error = await _run_blocking(conn.execute, 12, cmd, timeout=10)

        stat_cmd = f"stat --format='%s %Y' {safe_path} 2>/dev/null || stat -f '%z %m' {safe_path} 2>/dev/null"
        _, stat_output, _ = await _run_blocking(conn.execute, 7, stat_cmd, timeout=5)

        file_size = 0
        modified_at = None
        if stat_output and stat_output.strip():
            parts = stat_output.strip().split()
            if len(parts) >= 2:
                try:
                    file_size = int(parts[0])
                    modified_at = datetime.fromtimestamp(int(parts[1])).isoformat()
                except (ValueError, TypeError):
                    pass

        return {
            "content": output or "",
            "file_path": file_path,
            "lines_returned": len((output or "").strip().split("\n")) if output else 0,
            "file_size": file_size,
            "modified_at": modified_at,
            "keyword": keyword,
        }

    except Exception as e:
        sys_error("logs", f"Failed to read logs from {array_id}", {"file": file_path, "error": str(e)})
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read log file: {str(e)}",
        )


@agent_router.get("/{array_id}/log-files")
async def list_log_files(
    array_id: str,
    directory: str = "/var/log",
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """List available log files on remote array."""
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    cmd = f"find {directory} -maxdepth 2 -type f \\( -name '*.log' -o -name 'messages*' -o -name 'syslog*' \\) 2>/dev/null | head -50"
    _, output, _ = await _run_blocking(conn.execute, 12, cmd, timeout=10)

    files = []
    if output:
        for path in output.strip().split("\n"):
            path = path.strip()
            if not path:
                continue
            stat_cmd = f"stat --format='%s %Y' {path} 2>/dev/null || stat -f '%z %m' {path} 2>/dev/null"
            _, stat_output, _ = await _run_blocking(conn.execute, 7, stat_cmd, timeout=5)
            size = 0
            modified = None
            if stat_output and stat_output.strip():
                parts = stat_output.strip().split()
                if len(parts) >= 2:
                    try:
                        size = int(parts[0])
                        modified = datetime.fromtimestamp(int(parts[1])).isoformat()
                    except (ValueError, TypeError):
                        pass
            files.append({
                "path": path,
                "name": path.split("/")[-1],
                "size": size,
                "size_human": _format_bytes(size),
                "modified": modified,
            })

    files.sort(key=lambda x: x.get("modified") or "", reverse=True)

    return {
        "directory": directory,
        "files": files,
        "common_paths": COMMON_LOG_PATHS,
    }


# ---------------------------------------------------------------------------
# Agent-config endpoints
# ---------------------------------------------------------------------------

@agent_router.get("/{array_id}/agent-config")
async def get_agent_config(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Get Agent configuration from remote array."""
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"

    try:
        content = await _run_blocking(conn.read_file, 10, config_path)
        if not content:
            return {
                "exists": False,
                "config": None,
                "config_path": config_path,
                "config_hash": None,
                "error": "Config file not found or empty",
            }
        config_hash = _compute_config_hash(content)
        try:
            config_data = json.loads(content)
            return {
                "exists": True,
                "config": config_data,
                "config_path": config_path,
                "config_hash": config_hash,
                "raw": content,
            }
        except json.JSONDecodeError as e:
            return {
                "exists": True,
                "config": None,
                "config_path": config_path,
                "config_hash": config_hash,
                "raw": content,
                "error": f"Invalid JSON: {str(e)}",
            }

    except Exception as e:
        sys_error("agent-config", f"Failed to read agent config from {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read config: {str(e)}",
        )


@agent_router.put("/{array_id}/agent-config")
async def update_agent_config(
    array_id: str,
    body: Dict[str, Any] = Body(...),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Update Agent configuration on remote array."""
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    restart_agent_flag = body.pop("restart_agent", False)
    config_hash = body.pop("config_hash", None)
    config_data = body

    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"

    try:
        if config_hash:
            current_content = await _run_blocking(conn.read_file, 10, config_path)
            if current_content:
                current_hash = _compute_config_hash(current_content)
                if current_hash != config_hash:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail="配置已被其他人修改，请刷新后重试",
                    )

        config_json = json.dumps(config_data, indent=2, ensure_ascii=False)
        backup_cmd = f"cp {config_path} {config_path}.bak 2>/dev/null || true"
        await _run_blocking(conn.execute, 10, backup_cmd)

        import base64
        encoded = base64.b64encode(config_json.encode('utf-8')).decode('ascii')
        write_cmd = f"echo '{encoded}' | base64 -d > {config_path}"
        exit_code, output, error = await _run_blocking(conn.execute, 15, write_cmd)
        if exit_code != 0:
            raise Exception(f"Write failed: {error}")

        verify_content = await _run_blocking(conn.read_file, 10, config_path)
        if not verify_content:
            raise Exception("Failed to verify config write")

        new_hash = _compute_config_hash(verify_content)
        result = {
            "success": True,
            "config_path": config_path,
            "config_hash": new_hash,
            "message": "Configuration updated successfully",
        }

        if restart_agent_flag:
            deployer = AgentDeployer(conn, config)
            loop = asyncio.get_running_loop()
            try:
                restart_result = await asyncio.wait_for(
                    loop.run_in_executor(None, deployer.restart_agent), timeout=60
                )
            except asyncio.TimeoutError:
                restart_result = {"ok": False, "error": "restart timed out (60s)"}
            result["agent_restarted"] = restart_result.get("ok", False)
            if not restart_result.get("ok"):
                result["restart_error"] = restart_result.get("error")

        sys_info("agent-config", f"Updated agent config for {array_id}", {"restart": restart_agent_flag})
        return result

    except HTTPException:
        raise
    except Exception as e:
        sys_error("agent-config", f"Failed to update agent config for {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update config: {str(e)}",
        )


@agent_router.post("/{array_id}/agent-config/restore")
async def restore_agent_config(
    array_id: str,
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """Restore Agent configuration from backup."""
    conn = ssh_pool.get_connection(array_id)
    if not conn or not conn.is_connected():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Array not connected",
        )

    config = get_config()
    agent_path = config.remote.agent_deploy_path
    config_path = f"{agent_path}/config.json"
    backup_path = f"{config_path}.bak"

    try:
        check_cmd = f"test -f {backup_path} && echo 'exists'"
        _, output, _ = await _run_blocking(conn.execute, 10, check_cmd)
        if "exists" not in (output or ""):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="No backup file found",
            )

        restore_cmd = f"cp {backup_path} {config_path}"
        exit_code, output, error = await _run_blocking(conn.execute, 10, restore_cmd)
        if exit_code != 0:
            raise Exception(f"Restore failed: {error}")

        sys_info("agent-config", f"Restored agent config for {array_id}")
        return {"success": True, "message": "Configuration restored from backup"}

    except HTTPException:
        raise
    except Exception as e:
        sys_error("agent-config", f"Failed to restore agent config for {array_id}", {"error": str(e)})
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore config: {str(e)}",
        )
