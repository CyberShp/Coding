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
            staging_dir = getattr(self.config.remote, 'upload_staging_path', '') or '/home/permitdir'
            pkg_name = "observation_points.tar.gz"
            staging_package = posixpath.join(staging_dir, pkg_name)
            final_package = posixpath.join(deploy_parent, pkg_name)

            # Step 1: Clean up old agent folder and old package
            cleanup_commands = [
                f"mkdir -p {deploy_parent}",
                f"mkdir -p {staging_dir}",
                f"rm -f {final_package}",
                f"rm -f {staging_package}",
                f"rm -rf {deploy_path}",
            ]
            ok, error = self._run_commands(cleanup_commands)
            if not ok:
                return {"ok": False, "error": f"Cleanup failed: {error}"}

            # Step 2: Two-step upload — SFTP to staging, then cp to deploy dir
            # This works around permission issues on /OSM/coffer_data
            ok, error = self.conn.upload_file(local_package, staging_package)
            if not ok:
                sys_error(
                    "agent_deployer",
                    "Agent package upload to staging failed",
                    {"host": self.conn.host, "staging_path": staging_package, "error": error}
                )
                return {"ok": False, "error": f"Upload to staging failed: {error}"}

            # Copy from staging to final deploy directory
            ok, error = self._run_commands([
                f"cp {staging_package} {final_package}",
                f"rm -f {staging_package}",  # cleanup staging
            ])
            if not ok:
                return {"ok": False, "error": f"Copy from staging failed: {error}"}

            # Step 3: Extract and configure
            commands = [
                f"tar -xzf {final_package} -C {deploy_parent}",
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
        deploy_parent = posixpath.dirname(deploy_path)
        log_path = self.config.remote.agent_log_path
        python_cmd = self.config.remote.python_cmd
        log_parent = posixpath.dirname(log_path)

        # Step 1: Stop any existing agent first
        self.stop_agent()
        time.sleep(1)

        # Step 2: Start agent — 关键：cd 到 deploy_path 的父目录，
        # 这样 python3 -m observation_points 才能找到 observation_points 包。
        # 例如 deploy_path=/home/permitdir/observation_points
        # 则 cd /home/permitdir && python3 -m observation_points
        start_script = (
            f"mkdir -p {log_parent} && "
            f"cd {deploy_parent} && "
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

        # Step 3: Wait and verify process is alive (3s for reliability)
        time.sleep(3)
        exit_code, out, _ = self.conn.execute(f"kill -0 {pid} 2>/dev/null && echo 'alive'")

        if "alive" not in (out or ""):
            # Process died, read startup log for error details
            _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
            error_detail = start_log.strip() if start_log and start_log.strip() else "进程启动后立即退出，无日志"
            sys_error("agent_deployer", f"Agent process died after start on {self.conn.host}",
                      {"pid": pid, "start_log": error_detail[:500]})
            return {"ok": False, "error": f"Agent 进程启动后退出 (PID {pid}): {error_detail[:300]}"}

        # Step 4: Wait a bit more, then read startup log for warnings
        # (non-critical errors like missing observers should not block success)
        time.sleep(1)
        _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
        startup_warnings = []
        if start_log and start_log.strip():
            for line in start_log.strip().split('\n'):
                line = line.strip()
                # 过滤掉非关键启动警告（缺少 subhealth/performance 观察点、卡件状态非 RUNNING 等）
                if not line:
                    continue
                if any(kw in line.lower() for kw in ['warning', 'not found', 'no module', 'no such']):
                    startup_warnings.append(line)

        # Step 5: Use disown to detach from SSH session
        self.conn.execute(f"disown {pid} 2>/dev/null || true")

        sys_info("agent_deployer", f"Agent started on {self.conn.host}", {"pid": pid})
        result = {"ok": True, "message": f"Agent started (PID: {pid})", "pid": int(pid)}
        if startup_warnings:
            result["warnings"] = startup_warnings[:5]  # 最多返回 5 条警告
            result["message"] += f" (有 {len(startup_warnings)} 条启动警告，不影响运行)"
        return result

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
        """Build agent package from observation_web/agent directory.
        
        The package is created with arcname='observation_points' so that
        when extracted on the array, the Python module can be run as:
            python3 -m observation_points
        """
        base_dir = Path(__file__).resolve().parents[2]  # observation_web/
        agent_dir = base_dir / "agent"  # observation_web/agent/
        
        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found at {agent_dir}")

        fd, package_path = tempfile.mkstemp(suffix=".tar.gz")
        os.close(fd)
        package_path = Path(package_path)

        with tarfile.open(package_path, "w:gz") as tar:
            # Use arcname='observation_points' to maintain Python module compatibility
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
