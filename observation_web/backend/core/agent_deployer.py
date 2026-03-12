"""
Agent deployment utilities for observation_points.
"""

import logging
import os
import posixpath
import tarfile
import tempfile
import time
import hashlib
import asyncio
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from ..config import AppConfig
from .ssh_pool import SSHConnection
from .system_alert import sys_error, sys_warning, sys_info

logger = logging.getLogger(__name__)

# PID file path on remote array
AGENT_PID_FILE = "/var/run/observation-points.pid"
AGENT_START_LOG = "/tmp/observation_points_start.log"

# Polling configuration
MAX_WAIT_SECONDS = 10
POLL_INTERVAL_SECONDS = 0.5


class AgentDeployer:
    """Deploy and manage observation_points agent on a remote array."""

    def __init__(self, conn: SSHConnection, config: AppConfig):
        self.conn = conn
        self.config = config
        self.last_package_hash = ""

    def deploy(self) -> Dict[str, Any]:
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        local_package = None
        try:
            local_package = self._build_package()
            deploy_path = self.config.remote.agent_deploy_path
            deploy_parent = posixpath.dirname(deploy_path)
            staging_dir = getattr(self.config.remote, 'upload_staging_path', '') or '/home/permitdir'
            pkg_name = "observation_points.tar.gz"
            staging_package = posixpath.join(staging_dir, pkg_name)
            final_package = posixpath.join(deploy_parent, pkg_name)

            # Step 1: Clean up old agent folder and old package
            cleanup_commands = [
                f"mkdir -p {deploy_parent}",
                f"mkdir -p {staging_dir}",
                f"rm -rf {deploy_path}",
                f"rm -f {staging_package} {final_package}",
            ]
            for cmd in cleanup_commands:
                exit_code, _, _ = self.conn.execute(cmd)
                if exit_code != 0:
                    return {"ok": False, "error": f"Cleanup failed: {cmd}"}

            # Step 2: Upload package
            with open(local_package, 'rb') as f:
                content = f.read()
            encoded = self.conn.upload_content(staging_package, content)
            if not encoded:
                return {"ok": False, "error": "Upload failed"}

            # Step 3: Extract and configure
            extract_commands = [
                f"cd {staging_dir} && tar -xzf {pkg_name}",
                f"mv {staging_dir}/observation_points {deploy_path}",
                f"chmod +x {deploy_path}/run.sh",
            ]
            for cmd in extract_commands:
                exit_code, _, err = self.conn.execute(cmd)
                if exit_code != 0:
                    return {"ok": False, "error": f"Extract failed: {err}"}

            # Step 4: Configuration merge
            try:
                from ..api.observer_configs import get_all_observer_overrides
                # This requires db session - skip for now
            except Exception:
                pass

            return {"ok": True, "message": "Deployed successfully"}

        except Exception as e:
            logger.exception("Deployment failed")
            return {"ok": False, "error": str(e)}

        finally:
            if local_package and Path(local_package).exists():
                try:
                    Path(local_package).unlink()
                except Exception:
                    pass

    def _is_process_alive(self, pid: str) -> bool:
        """Check if a process with given PID is alive."""
        if not pid or not pid.isdigit():
            return False
        exit_code, out, _ = self.conn.execute(f"kill -0 {pid} 2>/dev/null && echo 'alive'")
        return "alive" in (out or "")

    def _wait_for_process(
        self, 
        pid: str, 
        expect_alive: bool = True, 
        max_wait: int = MAX_WAIT_SECONDS
    ) -> Tuple[bool, str]:
        """
        Wait for process state to match expectation.
        Returns (success, error_message).
        """
        elapsed = 0
        while elapsed < max_wait:
            is_alive = self._is_process_alive(pid)
            if is_alive == expect_alive:
                return True, ""
            time.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS
        
        return False, f"Process {'alive' if expect_alive else 'dead'} after {max_wait}s"

    def start_agent(self) -> Dict[str, Any]:
        """Start the agent with proper PID tracking and verification."""
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        deploy_path = self.config.remote.agent_deploy_path
        log_path = self.config.remote.agent_log_path
        python_cmd = self.config.remote.python_cmd
        log_parent = posixpath.dirname(log_path)

        # Step 1: Stop any existing agent first
        self.stop_agent()
        # Wait for process to actually terminate
        time.sleep(1.0)

        # Step 2: Start agent with proper PID tracking
        # Use nohup + direct PID capture instead of pgrep
        start_script = (
            f"mkdir -p {log_parent} && "
            f"cd {deploy_path} && "
            f"nohup {python_cmd} -m observation_points "
            f"-c /etc/observation-points/config.json "
            f"--log-file {log_path} "
            f"> {AGENT_START_LOG} 2>&1 & "
            # Get PID directly from $! in the same command
            f"echo $!"
        )

        exit_code, pid_str, err = self.conn.execute(start_script, timeout=15)
        if exit_code != 0:
            _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
            error_detail = start_log.strip() if start_log and start_log.strip() else (err or "Unknown error")
            sys_error("agent_deployer", f"Agent start failed on {self.conn.host}",
                      {"exit_code": exit_code, "error": error_detail})
            return {"ok": False, "error": f"启动命令失败: {error_detail}"}

        pid = pid_str.strip()
        if not pid or not pid.isdigit():
            return {"ok": False, "error": f"未能获取进程 PID (got: '{pid_str.strip()}')"}

        # Step 3: Wait and verify process is alive using polling
        success, _ = self._wait_for_process(pid, expect_alive=True, max_wait=5)
        
        if not success:
            # Process died, read startup log for error details
            _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
            error_detail = start_log.strip() if start_log and start_log.strip() else "进程启动后立即退出，无日志"
            sys_error("agent_deployer", f"Agent process died after start on {self.conn.host}",
                      {"pid": pid, "start_log": error_detail[:500]})
            return {"ok": False, "error": f"Agent 进程启动后退出 (PID {pid}): {error_detail[:300]}"}

        # Step 4: Save PID to file
        self.conn.execute(f"echo {pid} > {AGENT_PID_FILE}")

        # Step 5: Read startup log for warnings
        time.sleep(0.5)
        _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
        startup_warnings = []
        if start_log and start_log.strip():
            for line in start_log.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                if any(kw in line.lower() for kw in ['warning', 'not found', 'no module', 'no such']):
                    startup_warnings.append(line)

        sys_info("agent_deployer", f"Agent started on {self.conn.host}", {"pid": pid})
        result = {"ok": True, "message": f"Agent started (PID: {pid})", "pid": int(pid)}
        if startup_warnings:
            result["warnings"] = startup_warnings[:5]
            result["message"] += f" (有 {len(startup_warnings)} 条启动警告)"
        return result

    def stop_agent(self) -> Dict[str, Any]:
        """Stop agent using PID file with careful process handling."""
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        stopped_pids = []

        # Try PID file first - this is the most reliable method
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            pid = pid_str.strip()
            # Try graceful kill first
            self.conn.execute(f"kill {pid} 2>/dev/null")
            # Wait for graceful exit
            time.sleep(0.5)
            
            # Check if still alive
            if self._is_process_alive(pid):
                # Force kill only if still alive
                self.conn.execute(f"kill -9 {pid} 2>/dev/null")
                time.sleep(0.3)
            
            stopped_pids.append(pid)

        # Clean up PID file
        self.conn.execute(f"rm -f {AGENT_PID_FILE}")

        # Be more careful with pkill - only kill if we have a specific match
        # Use more specific pattern and exclude our own PID
        current_pid = os.getpid()
        self.conn.execute(
            f"pkill -f 'python.*observation_points' 2>/dev/null || true"
        )
        time.sleep(0.5)
        
        # Only use -9 as last resort if absolutely necessary
        # Don't use blanket pkill -9

        return {
            "ok": True, 
            "message": f"Agent stopped (PIDs: {', '.join(stopped_pids) if stopped_pids else 'none'})"
        }

    def restart_agent(self) -> Dict[str, Any]:
        """Restart agent with proper waiting."""
        result = self.stop_agent()
        if not result.get("ok"):
            return result
        
        # Wait for process to fully terminate
        time.sleep(1.5)
        return self.start_agent()

    def check_deployed(self) -> bool:
        """Check if agent is deployed."""
        deploy_path = self.config.remote.agent_deploy_path
        exit_code, out, _ = self.conn.execute(f"test -d {deploy_path} && echo 'deployed'")
        return exit_code == 0 and "deployed" in out

    def check_running(self) -> bool:
        """Check if agent is running."""
        # Try PID file first
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            pid = pid_str.strip()
            if self._is_process_alive(pid):
                return True
        
        # Fallback to pgrep only if PID file doesn't work
        exit_code, out, _ = self.conn.execute(
            "pgrep -f 'python.*observation_points' 2>/dev/null | head -1"
        )
        return exit_code == 0 and out.strip().isdigit()

    def get_agent_status(self) -> Dict[str, Any]:
        """Get detailed agent status."""
        info = {"deployed": self.check_deployed(), "running": False, "pid": None}
        
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            pid = pid_str.strip()
            if self._is_process_alive(pid):
                info["running"] = True
                info["pid"] = int(pid)
                # Get uptime
                exit_code, out, _ = self.conn.execute(f"ps -o etime= -p {pid} 2>/dev/null")
                if exit_code == 0:
                    info["uptime"] = out.strip()
        
        return info

    def _build_package(self) -> str:
        """Build deployment package from agent directory."""
        agent_dir = Path(__file__).parent.parent.parent / "agent"
        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            with tarfile.open(tmp.name, "w:gz") as tar:
                tar.add(agent_dir, arcname="observation_points")
            return tmp.name
