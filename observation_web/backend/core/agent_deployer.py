"""
Agent deployment utilities for observation_points.
"""

import logging
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from ..config import AppConfig
from .ssh_pool import SSHConnection

logger = logging.getLogger(__name__)


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
            deploy_parent = str(Path(deploy_path).parent)
            remote_package = f"{deploy_parent}/observation_points.tar.gz"

            ok, error = self.conn.upload_file(local_package, remote_package)
            if not ok:
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
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        deploy_path = self.config.remote.agent_deploy_path
        log_path = self.config.remote.agent_log_path
        python_cmd = self.config.remote.python_cmd

        commands = [
            f"mkdir -p {Path(log_path).parent}",
            f"cd {deploy_path} && nohup {python_cmd} -m observation_points "
            f"-c /etc/observation-points/config.json "
            f"--log-file {log_path} >/dev/null 2>&1 &",
        ]

        ok, error = self._run_commands(commands)
        if not ok:
            return {"ok": False, "error": error}

        return {"ok": True, "message": "Agent started"}

    def stop_agent(self) -> Dict[str, Any]:
        if not self.conn.is_connected():
            return {"ok": False, "error": "Not connected"}

        exit_code, _, err = self.conn.execute("pkill -f 'python.*observation_points'")
        if exit_code not in (0, 1):
            return {"ok": False, "error": err or "Failed to stop agent"}

        return {"ok": True, "message": "Agent stopped"}

    def restart_agent(self) -> Dict[str, Any]:
        stop_result = self.stop_agent()
        if not stop_result["ok"]:
            return stop_result
        return self.start_agent()

    def check_deployed(self) -> bool:
        deploy_path = self.config.remote.agent_deploy_path
        exit_code, out, _ = self.conn.execute(f"test -d {deploy_path} && echo 'deployed'")
        return exit_code == 0 and "deployed" in out

    def check_running(self) -> bool:
        exit_code, out, _ = self.conn.execute("pgrep -f 'python.*observation_points'")
        return exit_code == 0 and out.strip() != ""

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
                return False, err or f"Command failed: {command}"
        return True, ""
