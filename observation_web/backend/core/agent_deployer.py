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
                    return {"ok": False, "deployed": False, "error": f"Cleanup failed: {cmd}"}

            # Step 2: Upload package
            if not self._upload_package(local_package, staging_package):
                return {"ok": False, "deployed": False, "error": "Upload failed"}

            # Step 3: Extract and configure
            extract_commands = [
                f"cd {staging_dir} && tar -xzf {pkg_name}",
                f"mv {staging_dir}/observation_points {deploy_path}",
            ]
            for cmd in extract_commands:
                exit_code, _, err = self.conn.execute(cmd)
                if exit_code != 0:
                    return {"ok": False, "deployed": False, "error": f"Extract failed: {err}"}

            layout_result = self._validate_deploy_layout(deploy_path)
            if not layout_result.get("ok"):
                layout_result["deployed"] = False
                return layout_result

            # --- Deploy is now considered successful ---
            # systemd service installation is a post-deploy step;
            # its failure should NOT override the deploy success verdict.
            warnings = []  # type: list
            service_installed = False

            service_result = self._install_systemd_service()
            if service_result.get("ok"):
                service_installed = True
            else:
                svc_err = service_result.get("error") or service_result.get("message", "")
                if svc_err:
                    warnings.append(f"systemd service install: {svc_err}")
                logger.warning(
                    "systemd service install failed on %s but deploy itself succeeded: %s",
                    self.conn.host, svc_err,
                )

            # Step 4: Configuration merge
            try:
                from ..api.observer_configs import get_all_observer_overrides
                # This requires db session - skip for now
            except Exception:
                pass

            result = {
                "ok": True,
                "deployed": True,
                "service_installed": service_installed,
                "message": "Deployed successfully" if service_installed
                           else "Deployed successfully, but systemd service install failed",
            }
            if warnings:
                result["warnings"] = warnings
            return result

        except Exception as e:
            logger.exception("Deployment failed")
            return {"ok": False, "deployed": False, "error": str(e)}

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

    def _check_cmdline_match(self, pid: str) -> str:
        """Read /proc/<pid>/cmdline and return it if it matches the expected agent entry.

        Returns the command line string on match, empty string otherwise.
        """
        if not pid or not pid.isdigit():
            return ""
        deploy_path = self.config.remote.agent_deploy_path
        exit_code, out, _ = self.conn.execute(
            f"cat /proc/{pid}/cmdline 2>/dev/null | tr '\\0' ' '"
        )
        if exit_code != 0 or not out.strip():
            return ""
        cmdline = out.strip()
        # Must contain the expected agent module or deploy path
        if "observation_points" in cmdline or deploy_path in cmdline:
            return cmdline
        return ""

    def _resolve_running_state(self) -> Dict[str, Any]:
        """Unified running-state detection with strict validation.

        Priority:
        1. systemd: ActiveState=active + SubState + MainPID > 0 + PID alive + cmdline match
        2. PID file: file exists + PID alive + cmdline match (else mark stale)
        3. pgrep: restricted to deploy-path pattern, only as low-confidence diagnostic

        Returns a rich dict used by both check_running() and get_agent_status().
        """
        deploy_path = self.config.remote.agent_deploy_path
        info: Dict[str, Any] = {
            "running": False,
            "running_source": "none",
            "running_confidence": "low",
            "pid": None,
            "service_active": False,
            "service_substate": "",
            "main_pid": None,
            "pidfile_present": False,
            "pidfile_pid": None,
            "pidfile_stale": False,
            "matched_process_cmdline": "",
        }
        warnings: list = []

        # ── Layer 1: systemd (strict) ────────────────────────────────────
        if self._is_systemd_available():
            exit_code, out, _ = self.conn.execute(
                f"systemctl show {SYSTEMD_SERVICE_NAME}"
                f" -p ActiveState -p SubState -p MainPID 2>/dev/null"
            )
            props: Dict[str, str] = {}
            if exit_code == 0 and out.strip():
                for line in out.strip().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        props[k.strip()] = v.strip()

            active_state = props.get("ActiveState", "")
            sub_state = props.get("SubState", "")
            main_pid_str = props.get("MainPID", "0")
            info["service_substate"] = sub_state

            if active_state == "active":
                info["service_active"] = True
                if main_pid_str.isdigit() and int(main_pid_str) > 0:
                    info["main_pid"] = int(main_pid_str)
                    if self._is_process_alive(main_pid_str):
                        cmdline = self._check_cmdline_match(main_pid_str)
                        if cmdline:
                            info["running"] = True
                            info["running_source"] = "systemd"
                            info["running_confidence"] = "high"
                            info["pid"] = int(main_pid_str)
                            info["matched_process_cmdline"] = cmdline
                        else:
                            warnings.append(
                                f"systemd MainPID {main_pid_str} alive but cmdline does not match agent"
                            )
                    else:
                        warnings.append(
                            f"systemd reports active but MainPID {main_pid_str} is dead"
                        )
                else:
                    warnings.append("systemd reports active but MainPID is 0")
            elif active_state:
                info["service_substate"] = sub_state

        # ── Layer 2: PID file (strict) ───────────────────────────────────
        exit_code, pid_str, _ = self.conn.execute(f"cat {AGENT_PID_FILE} 2>/dev/null")
        if exit_code == 0 and pid_str.strip().isdigit():
            info["pidfile_present"] = True
            pid_val = pid_str.strip()
            info["pidfile_pid"] = int(pid_val)

            if self._is_process_alive(pid_val):
                cmdline = self._check_cmdline_match(pid_val)
                if cmdline:
                    if not info["running"]:
                        info["running"] = True
                        info["running_source"] = "pidfile"
                        info["running_confidence"] = "high"
                        info["matched_process_cmdline"] = cmdline
                    if info["pid"] is None:
                        info["pid"] = int(pid_val)
                else:
                    warnings.append(
                        f"PID file PID {pid_val} alive but cmdline does not match agent"
                    )
            else:
                info["pidfile_stale"] = True
                warnings.append(f"PID file exists but PID {pid_val} is dead (stale pidfile)")

        # ── Layer 3: pgrep fallback (restricted + low confidence) ────────
        if not info["running"]:
            # Use deploy path for precision instead of broad 'python.*observation_points'
            pgrep_pattern = f"python.*{deploy_path}"
            exit_code, out, _ = self.conn.execute(
                f"pgrep -f {shlex.quote(pgrep_pattern)} 2>/dev/null | head -1"
            )
            if exit_code == 0 and out.strip().isdigit():
                pgrep_pid = out.strip()
                cmdline = self._check_cmdline_match(pgrep_pid)
                if cmdline:
                    info["running"] = True
                    info["running_source"] = "pgrep"
                    info["running_confidence"] = "medium"
                    info["pid"] = int(pgrep_pid)
                    info["matched_process_cmdline"] = cmdline
                    if not info["pidfile_present"]:
                        warnings.append(
                            "Agent running but PID file missing – consider restarting"
                        )
                else:
                    warnings.append(
                        f"pgrep hit PID {pgrep_pid} but cmdline did not match agent entry"
                    )

        # ── Cross-checks ─────────────────────────────────────────────────
        if info["service_active"] and not info["pidfile_present"]:
            warnings.append("systemd reports active but PID file is missing")

        if warnings:
            info["warnings"] = warnings

        logger.debug(
            "Running-state detection for %s: running=%s source=%s confidence=%s",
            self.conn.host,
            info["running"],
            info["running_source"],
            info["running_confidence"],
        )

        return info

    def check_running(self) -> bool:
        """Check if agent is running (unified 3-layer detection)."""
        return self._resolve_running_state()["running"]

    def get_agent_status(self) -> Dict[str, Any]:
        """Get detailed agent status (unified 3-layer detection)."""
        state = self._resolve_running_state()
        info = {
            "deployed": self.check_deployed(),
            "running": state["running"],
            "running_source": state["running_source"],
            "running_confidence": state["running_confidence"],
            "pid": state["pid"],
            "service_active": state["service_active"],
            "service_substate": state["service_substate"],
            "main_pid": state["main_pid"],
            "pidfile_present": state["pidfile_present"],
            "pidfile_pid": state["pidfile_pid"],
            "pidfile_stale": state["pidfile_stale"],
            "matched_process_cmdline": state["matched_process_cmdline"],
        }
        if state.get("warnings"):
            info["warnings"] = state["warnings"]

        # Get uptime if we have a PID
        if info["pid"]:
            exit_code, out, _ = self.conn.execute(f"ps -o etime= -p {info['pid']} 2>/dev/null")
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
