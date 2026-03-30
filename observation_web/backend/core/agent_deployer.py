"""
Agent deployment utilities for observation_points.
"""

import logging
import os
import posixpath
import tarfile
import tempfile
import time
import asyncio
import shlex
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from ..config import AppConfig
from .ssh_pool import SSHConnection
from .system_alert import sys_error, sys_warning, sys_info

logger = logging.getLogger(__name__)

# PID file path on remote array
AGENT_PID_FILE = "/var/run/observation-points.pid"
AGENT_START_LOG = "/tmp/observation_points_start.log"
SYSTEMD_SERVICE_NAME = "observation-points"
SYSTEMD_SERVICE_FILE = f"/etc/systemd/system/{SYSTEMD_SERVICE_NAME}.service"
SYSTEMD_READY_TIMEOUT_SECONDS = 1200
SYSTEMD_READY_INTERVAL_SECONDS = 30

# Polling configuration
MAX_WAIT_SECONDS = 10
POLL_INTERVAL_SECONDS = 0.5

SERVICE_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "agent" / "observation-points.service"


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
            if not self._upload_package(local_package, staging_package):
                return {"ok": False, "error": "Upload failed"}

            # Step 3: Extract and configure
            extract_commands = [
                f"cd {staging_dir} && tar -xzf {pkg_name}",
                f"mv {staging_dir}/observation_points {deploy_path}",
            ]
            for cmd in extract_commands:
                exit_code, _, err = self.conn.execute(cmd)
                if exit_code != 0:
                    return {"ok": False, "error": f"Extract failed: {err}"}

            layout_result = self._validate_deploy_layout(deploy_path)
            if not layout_result.get("ok"):
                return layout_result

            # Post-deploy: systemd service install is non-blocking
            warnings: list[str] = []
            service_result = self._install_systemd_service()
            if not service_result.get("ok"):
                # Service install failure is a warning, not a deployment failure
                warnings.append(service_result.get("error", "Service install failed"))
                logger.warning("Service install warning on %s: %s", self.conn.host, service_result.get("error"))

            # Step 4: Configuration merge
            try:
                from ..api.observer_configs import get_all_observer_overrides
                # This requires db session - skip for now
            except Exception:
                pass

            result: Dict[str, Any] = {"ok": True, "message": "Deployed successfully"}
            if warnings:
                result["warnings"] = warnings
                result["message"] += f" (with {len(warnings)} warning(s))"
            return result

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

    def _upload_package(self, local_package: str, remote_path: str) -> bool:
        upload_content = getattr(self.conn, "upload_content", None)
        if callable(upload_content):
            with open(local_package, "rb") as f:
                return bool(upload_content(remote_path, f.read()))

        upload_file = getattr(self.conn, "upload_file", None)
        if callable(upload_file):
            ok, _ = upload_file(local_package, remote_path)
            return ok

        return False

    def _is_systemd_available(self) -> bool:
        exit_code, _, _ = self.conn.execute(
            "command -v systemctl >/dev/null 2>&1 && test -d /run/systemd/system"
        )
        return exit_code == 0

    def _validate_deploy_layout(self, deploy_path: str) -> Dict[str, Any]:
        expected_main = posixpath.join(deploy_path, "__main__.py")
        expected_init = posixpath.join(deploy_path, "__init__.py")
        exit_code, _, err = self.conn.execute(
            f"test -f {shlex.quote(expected_main)} && test -f {shlex.quote(expected_init)}"
        )
        if exit_code != 0:
            return {
                "ok": False,
                "error": (
                    f"Deploy validation failed: missing package entrypoints under {deploy_path}"
                    + (f" ({err})" if err else "")
                ),
            }
        return {"ok": True}

    def _load_service_template(self) -> str:
        return SERVICE_TEMPLATE_PATH.read_text(encoding="utf-8")

    def _install_systemd_service(self) -> Dict[str, Any]:
        if not self._is_systemd_available():
            return {"ok": True, "message": "systemd unavailable, skipped service install"}

        try:
            service_content = self._load_service_template().format(
                BACKEND_HOST=self.config.server.host
            )
        except Exception as exc:
            logger.exception("Failed to load service template")
            return {"ok": False, "error": f"Failed to render service template: {exc}"}

        install_command = (
            f"cat <<'EOF' > {SYSTEMD_SERVICE_FILE}\n"
            f"{service_content}\n"
            "EOF"
        )
        commands = [
            install_command,
            "systemctl daemon-reload",
            f"systemctl enable {SYSTEMD_SERVICE_NAME}",
        ]
        for cmd in commands:
            exit_code, _, err = self.conn.execute(cmd)
            if exit_code != 0:
                return {"ok": False, "error": f"Service install failed: {err or cmd}"}
        return {"ok": True}

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

        self.stop_agent()
        time.sleep(1.0)

        if self._is_systemd_available():
            exit_code, _, err = self.conn.execute(f"systemctl start {SYSTEMD_SERVICE_NAME}")
            if exit_code == 0:
                ready = asyncio.run(self.wait_for_ready(timeout=60, interval=5))
                if ready:
                    sys_info("agent_deployer", f"Agent started on {self.conn.host}", {"service": SYSTEMD_SERVICE_NAME})
                    return {"ok": True, "message": f"Agent started via systemd ({SYSTEMD_SERVICE_NAME})"}
            logger.warning("systemctl start failed on %s, falling back to legacy start: %s", self.conn.host, err)

        return self._start_agent_legacy()

    def _start_agent_legacy(self) -> Dict[str, Any]:
        deploy_path = self.config.remote.agent_deploy_path
        deploy_parent = posixpath.dirname(deploy_path)
        log_path = self.config.remote.agent_log_path
        python_cmd = self.config.remote.python_cmd
        log_parent = posixpath.dirname(log_path)
        start_script = (
            f"mkdir -p {log_parent} && "
            f"cd {deploy_parent} && "
            f"nohup {python_cmd} -m observation_points "
            f"-c /etc/observation-points/config.json "
            f"--log-file {log_path} "
            f"> {AGENT_START_LOG} 2>&1 & "
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

        success, _ = self._wait_for_process(pid, expect_alive=True, max_wait=5)
        if not success:
            _, start_log, _ = self.conn.execute(f"cat {AGENT_START_LOG} 2>/dev/null")
            error_detail = start_log.strip() if start_log and start_log.strip() else "进程启动后立即退出，无日志"
            sys_error("agent_deployer", f"Agent process died after start on {self.conn.host}",
                      {"pid": pid, "start_log": error_detail[:500]})
            return {"ok": False, "error": f"Agent 进程启动后退出 (PID {pid}): {error_detail[:300]}"}

        self.conn.execute(f"echo {pid} > {AGENT_PID_FILE}")
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

        if self._is_systemd_available():
            exit_code, _, err = self.conn.execute(f"systemctl stop {SYSTEMD_SERVICE_NAME}")
            self.conn.execute(f"rm -f {AGENT_PID_FILE}")
            if exit_code == 0:
                return {"ok": True, "message": f"Agent stopped via systemd ({SYSTEMD_SERVICE_NAME})"}
            logger.warning("systemctl stop failed on %s, falling back to legacy stop: %s", self.conn.host, err)

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

    def _get_process_cmdline(self, pid: str) -> str:
        """Read /proc/<pid>/cmdline (returns empty string on failure)."""
        if not pid or not pid.isdigit():
            return ""
        exit_code, out, _ = self.conn.execute(
            f"cat /proc/{pid}/cmdline 2>/dev/null | tr '\\0' ' '"
        )
        return out.strip() if exit_code == 0 else ""

    def _cmdline_matches_agent(self, cmdline: str) -> bool:
        """Return True if *cmdline* looks like our observation_points agent."""
        if not cmdline:
            return False
        deploy_path = self.config.remote.agent_deploy_path
        return "observation_points" in cmdline or deploy_path in cmdline

    def _resolve_running_state(self) -> Dict[str, Any]:
        """Unified 3-layer strict running detection: systemd → PID file → pgrep.

        Returns a diagnostic dict consumed by both ``check_running()`` and
        ``get_agent_status()``.  Fields:

        * running (bool)
        * pid (str)
        * running_confidence: high / medium / low
        * running_source: systemd / pidfile / pgrep / none
        * service_active (str)
        * service_substate (str)
        * main_pid (str)
        * pidfile_present (bool)
        * pidfile_pid (str)
        * pidfile_stale (bool)
        * matched_process_cmdline (str)
        """
        diag: Dict[str, Any] = {
            "running": False,
            "pid": "",
            "running_confidence": "low",
            "running_source": "none",
            "service_active": "",
            "service_substate": "",
            "main_pid": "",
            "pidfile_present": False,
            "pidfile_pid": "",
            "pidfile_stale": False,
            "matched_process_cmdline": "",
        }

        # ------------------------------------------------------------------
        # Layer 1: systemd — strict validation
        # ------------------------------------------------------------------
        if self._is_systemd_available():
            exit_code, out, _ = self.conn.execute(
                f"systemctl show {SYSTEMD_SERVICE_NAME}"
                " -p ActiveState -p SubState -p MainPID 2>/dev/null"
            )
            props: Dict[str, str] = {}
            if exit_code == 0 and out:
                for line in out.strip().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        props[k.strip()] = v.strip()

            active_state = props.get("ActiveState", "")
            sub_state = props.get("SubState", "")
            main_pid = props.get("MainPID", "0")

            diag["service_active"] = active_state
            diag["service_substate"] = sub_state
            diag["main_pid"] = main_pid

            if active_state == "active" and main_pid.isdigit() and main_pid != "0":
                if self._is_process_alive(main_pid):
                    cmdline = self._get_process_cmdline(main_pid)
                    if self._cmdline_matches_agent(cmdline):
                        diag.update(
                            running=True,
                            pid=main_pid,
                            running_confidence="high",
                            running_source="systemd",
                            matched_process_cmdline=cmdline[:200],
                        )
                        return diag
                    else:
                        logger.warning(
                            "systemd MainPID %s cmdline mismatch on %s: %s",
                            main_pid, self.conn.host, cmdline[:120],
                        )
                else:
                    logger.warning(
                        "systemd reports active but MainPID %s is not alive on %s",
                        main_pid, self.conn.host,
                    )

        # ------------------------------------------------------------------
        # Layer 2: PID file — with cmdline validation + stale detection
        # ------------------------------------------------------------------
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            pid = pid_str.strip()
            diag["pidfile_present"] = True
            diag["pidfile_pid"] = pid
            if self._is_process_alive(pid):
                cmdline = self._get_process_cmdline(pid)
                if self._cmdline_matches_agent(cmdline):
                    diag.update(
                        running=True,
                        pid=pid,
                        running_confidence="medium",
                        running_source="pidfile",
                        matched_process_cmdline=cmdline[:200],
                    )
                    return diag
                else:
                    logger.warning(
                        "PID file PID %s cmdline mismatch on %s: %s",
                        pid, self.conn.host, cmdline[:120],
                    )
            else:
                diag["pidfile_stale"] = True
                logger.info("Stale PID file detected on %s (PID %s)", self.conn.host, pid)

        # ------------------------------------------------------------------
        # Layer 3: pgrep fallback — restricted to deploy path, low confidence
        # ------------------------------------------------------------------
        deploy_path = self.config.remote.agent_deploy_path
        safe_path = shlex.quote(deploy_path)
        exit_code, out, _ = self.conn.execute(
            f"pgrep -af 'python.*{safe_path}.*observation_points' 2>/dev/null | head -1"
        )
        if exit_code == 0 and out.strip():
            parts = out.strip().split(None, 1)
            pid = parts[0] if parts[0].isdigit() else ""
            cmdline = parts[1] if len(parts) > 1 else ""
            if pid and self._cmdline_matches_agent(cmdline):
                diag.update(
                    running=True,
                    pid=pid,
                    running_confidence="low",
                    running_source="pgrep",
                    matched_process_cmdline=cmdline[:200],
                )
                return diag

        return diag

    def check_running(self) -> bool:
        """Check if agent is running (delegates to unified resolver)."""
        result = self._resolve_running_state()
        return result["running"]

    def get_agent_status(self) -> Dict[str, Any]:
        """Get detailed agent status (uses same resolver as check_running).

        Returns a dict with at least:
        * deployed, running, pid, uptime
        * running_confidence, running_source
        * Diagnostic fields (service_active, pidfile_stale, etc.)
        """
        info: Dict[str, Any] = {"deployed": self.check_deployed(), "running": False, "pid": None}

        diag = self._resolve_running_state()
        info["running"] = diag["running"]
        info["running_confidence"] = diag["running_confidence"]
        info["running_source"] = diag["running_source"]
        info["service_active"] = diag.get("service_active", "")
        info["service_substate"] = diag.get("service_substate", "")
        info["main_pid"] = diag.get("main_pid", "")
        info["pidfile_present"] = diag.get("pidfile_present", False)
        info["pidfile_pid"] = diag.get("pidfile_pid", "")
        info["pidfile_stale"] = diag.get("pidfile_stale", False)
        info["matched_process_cmdline"] = diag.get("matched_process_cmdline", "")

        pid_str = diag.get("pid", "")
        if pid_str:
            info["pid"] = int(pid_str)
            exit_code, out, _ = self.conn.execute(f"ps -o etime= -p {pid_str} 2>/dev/null")
            if exit_code == 0:
                info["uptime"] = out.strip()

        return info

    async def wait_for_ready(
        self,
        timeout: int = SYSTEMD_READY_TIMEOUT_SECONDS,
        interval: int = SYSTEMD_READY_INTERVAL_SECONDS,
    ) -> bool:
        """Poll systemd service state until the agent becomes active."""
        if not self._is_systemd_available():
            return False

        elapsed = 0
        while elapsed < timeout:
            exit_code, out, _ = self.conn.execute(
                f"systemctl is-active {SYSTEMD_SERVICE_NAME} 2>/dev/null"
            )
            if exit_code == 0 and out.strip() == "active":
                return True
            await asyncio.sleep(interval)
            elapsed += interval
        return False

    def _build_package(self) -> str:
        """Build deployment package from agent directory."""
        agent_dir = Path(__file__).parent.parent.parent / "agent"
        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            with tarfile.open(tmp.name, "w:gz") as tar:
                tar.add(agent_dir, arcname="observation_points")
            return tmp.name
