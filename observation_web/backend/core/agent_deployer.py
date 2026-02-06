"""
Agent deployment utilities for observation_points.
"""

import logging
import os
import posixpath
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from ..config import AppConfig
from .ssh_pool import SSHConnection
from .system_alert import sys_error, sys_warning, sys_info

logger = logging.getLogger(__name__)

# PID file path on remote array
AGENT_PID_FILE = "/var/run/observation-points.pid"
AGENT_START_LOG = "/tmp/observation_points_start.log"


class AgentDeployer:
    """Deploy and manage observation_points agent on a remote array."""

    def __init__(self, conn: SSHConnection, config: AppConfig):
        self.conn = conn
        self.config = config

    def deploy(self) -> Dict[str, Any]:
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        local_package = None
        try:
            local_package = self._build_package()
            deploy_path = self.config.remote.agent_deploy_path
            deploy_parent = posixpath.dirname(deploy_path)
            remote_package = posixpath.join(deploy_parent, "observation_points.tar.gz")

            ok, error = self.conn.upload_file(local_package, remote_package)
            if not ok:
                sys_error(
                    "agent_deployer",
                    "Agent package upload failed",
                    {"host": self.conn.host, "remote_path": remote_package, "error": error}
                )
                return {"ok": False, "error": f"Upload failed: {error}"}

            commands = [
                f"mkdir -p {deploy_parent}",
                f"rm -rf {deploy_path}",
                f"tar -xzf {remote_package} -C {deploy_parent}",
                f"mkdir -p /etc/observation-points",
                f"cp {deploy_path}/config.json /etc/observation-points/config.json",
            ]
            ok, error = self._run_commands(commands)
            if not ok:
                return {"ok": False, "error": error}

            start_result = self.start_agent()
            if not start_result["ok"]:
                return start_result

            return {
                "ok": True,
                "message": "Agent deployed and started",
                "deploy_path": deploy_path,
            }
        finally:
            if local_package:
                try:
                    if Path(local_package).exists():
                        Path(local_package).unlink()
                except Exception:
                    pass

    def start_agent(self) -> Dict[str, Any]:
        """Start the agent with PID tracking and startup verification."""
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        deploy_path = self.config.remote.agent_deploy_path
        log_path = self.config.remote.agent_log_path
        python_cmd = self.config.remote.python_cmd
        log_parent = posixpath.dirname(log_path)

        # Step 1: Stop any existing agent first
        self.stop_agent()
        time.sleep(1)

        # Step 2: Start agent with shell wrapper that captures PID and startup errors
        start_script = (
            f"mkdir -p {log_parent} && "
            f"cd {deploy_path} && "
            f"{python_cmd} -m observation_points "
            f"-c /etc/observation-points/config.json "
            f"--log-file {log_path} "
            f"> {AGENT_START_LOG} 2>&1 & "
            f"AGENT_PID=$! && "
            f"echo $AGENT_PID > {AGENT_PID_FILE} && "
            f"echo $AGENT_PID"
        )

        exit_code, pid_str, err = self.conn.execute(start_script, timeout=15)
        if exit_code != 0:
            # Read startup log for details
            _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
            error_detail = start_log.strip() if start_log and start_log.strip() else (err or "Unknown error")
            sys_error("agent_deployer", f"Agent start command failed on {self.conn.host}",
                      {"exit_code": exit_code, "error": error_detail})
            return {"ok": False, "error": f"启动命令失败: {error_detail}"}

        pid = pid_str.strip()
        if not pid or not pid.isdigit():
            return {"ok": False, "error": f"未能获取进程 PID (got: {pid_str.strip()})"}

        # Step 3: Wait and verify process is alive
        time.sleep(2)
        exit_code, out, _ = self.conn.execute(f"kill -0 {pid} 2>/dev/null && echo 'alive'")

        if "alive" not in (out or ""):
            # Process died, read startup log for error details
            _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
            error_detail = start_log.strip() if start_log and start_log.strip() else "进程启动后立即退出，无日志"
            sys_error("agent_deployer", f"Agent process died after start on {self.conn.host}",
                      {"pid": pid, "start_log": error_detail[:500]})
            return {"ok": False, "error": f"Agent 进程启动后退出 (PID {pid}): {error_detail[:300]}"}

        # Step 4: Use disown to detach from SSH session
        self.conn.execute(f"disown {pid} 2>/dev/null || true")

        sys_info("agent_deployer", f"Agent started on {self.conn.host}", {"pid": pid})
        return {"ok": True, "message": f"Agent started (PID: {pid})", "pid": int(pid)}

    def stop_agent(self) -> Dict[str, Any]:
        """Stop agent using PID file, falling back to pkill."""
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        # Try PID file first
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            pid = pid_str.strip()
            self.conn.execute(f"kill {pid} 2>/dev/null")
            time.sleep(0.5)
            # Force kill if still alive
            self.conn.execute(f"kill -9 {pid} 2>/dev/null")
            self.conn.execute(f"rm -f {AGENT_PID_FILE}")
        
        # Also pkill as fallback to catch orphaned processes
        self.conn.execute("pkill -f 'python.*observation_points' 2>/dev/null")
        time.sleep(0.5)
        self.conn.execute("pkill -9 -f 'python.*observation_points' 2>/dev/null")

        return {"ok": True, "message": "Agent stopped"}

    def restart_agent(self) -> Dict[str, Any]:
        self.stop_agent()
        time.sleep(1)
        return self.start_agent()

    def check_deployed(self) -> bool:
        deploy_path = self.config.remote.agent_deploy_path
        exit_code, out, _ = self.conn.execute(f"test -d {deploy_path} && echo 'deployed'")
        return exit_code == 0 and "deployed" in out

    def check_running(self) -> bool:
        """Check if agent is running using PID file, falling back to pgrep."""
        # Try PID file first
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            pid = pid_str.strip()
            exit_code, out, _ = self.conn.execute(f"kill -0 {pid} 2>/dev/null && echo 'running'")
            if "running" in (out or ""):
                return True
        
        # Fallback to pgrep
        exit_code, out, _ = self.conn.execute("pgrep -f 'python.*observation_points' 2>/dev/null")
        return exit_code == 0 and out.strip() != ""

    def get_agent_status(self) -> Dict[str, Any]:
        """Get detailed agent status including PID and uptime."""
        info = {"deployed": self.check_deployed(), "running": False, "pid": None}
        
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            pid = pid_str.strip()
            exit_code, out, _ = self.conn.execute(f"kill -0 {pid} 2>/dev/null && echo 'running'")
            if "running" in (out or ""):
                info["running"] = True
                info["pid"] = int(pid)
                # Get uptime
                _, elapsed, _ = self.conn.execute(f"ps -p {pid} -o etimes= 2>/dev/null")
                if elapsed and elapsed.strip().isdigit():
                    info["uptime_seconds"] = int(elapsed.strip())
        
        return info

    def _build_package(self) -> str:
        base_dir = Path(__file__).resolve().parents[2]
        agent_dir = base_dir.parent / "observation_points"
        if not agent_dir.exists():
            raise FileNotFoundError(f"observation_points not found at {agent_dir}")

        fd, package_path = tempfile.mkstemp(suffix=".tar.gz")
        os.close(fd)
        package_path = Path(package_path)

        with tarfile.open(package_path, "w:gz") as tar:
            tar.add(agent_dir, arcname="observation_points")

        return str(package_path)

    def _run_commands(self, commands: Iterable[str]) -> Tuple[bool, str]:
        for command in commands:
            exit_code, _, err = self.conn.execute(command)
            if exit_code != 0:
                sys_warning(
                    "agent_deployer",
                    f"Remote command failed",
                    {"host": self.conn.host, "command": command, "exit_code": exit_code, "error": err}
                )
                return False, err or f"Command failed: {command}"
        return True, ""
