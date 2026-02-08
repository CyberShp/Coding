"""Process guardian daemon for auto-restart, health checks, and PID management.

Provides production-grade process supervision with:
- Automatic crash detection and restart with exponential backoff
- PID file management for single-instance enforcement
- Health check probes (HTTP, TCP, custom callback)
- Signal-aware graceful shutdown
- Child process stdout/stderr log forwarding
"""

import os
import sys
import time
import signal
import atexit
import threading
import subprocess
from pathlib import Path
from typing import Optional, Callable, Any
from enum import Enum

from ..utils.logging import get_logger

logger = get_logger("daemon")


class HealthStatus(str, Enum):
    """Health check result status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class PidFile:
    """PID file manager for single-instance enforcement.

    Creates a PID file on start and removes it on exit.
    Detects stale PID files from crashed processes.
    """

    def __init__(self, path: str = "/tmp/packet_storm.pid"):
        self.path = Path(path)
        self._locked = False

    def acquire(self) -> bool:
        """Acquire the PID file lock.

        Returns:
            True if acquired, False if another instance is running.
        """
        if self.path.exists():
            try:
                old_pid = int(self.path.read_text().strip())
                # Check if process is still running
                os.kill(old_pid, 0)
                logger.warning(
                    "Another instance is running (PID %d). PID file: %s",
                    old_pid, self.path,
                )
                return False
            except (OSError, ValueError):
                # Process not running or invalid PID - stale file
                logger.info("Removing stale PID file: %s", self.path)
                self.path.unlink(missing_ok=True)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()))
        self._locked = True
        atexit.register(self.release)
        logger.info("PID file created: %s (PID %d)", self.path, os.getpid())
        return True

    def release(self) -> None:
        """Release the PID file lock."""
        if self._locked and self.path.exists():
            try:
                current_pid = int(self.path.read_text().strip())
                if current_pid == os.getpid():
                    self.path.unlink(missing_ok=True)
                    logger.debug("PID file removed: %s", self.path)
            except (OSError, ValueError):
                pass
            self._locked = False

    def __enter__(self) -> "PidFile":
        if not self.acquire():
            raise RuntimeError("Failed to acquire PID file lock")
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


class HealthChecker:
    """Periodic health check runner supporting multiple probe types.

    Supports:
    - HTTP health endpoint checks
    - TCP port connectivity checks
    - Custom callback-based checks
    """

    def __init__(
        self,
        interval: float = 30.0,
        timeout: float = 5.0,
        unhealthy_threshold: int = 3,
    ):
        """Initialize the health checker.

        Args:
            interval: Seconds between health checks.
            timeout: Timeout for each check attempt.
            unhealthy_threshold: Consecutive failures before marking unhealthy.
        """
        self.interval = interval
        self.timeout = timeout
        self.unhealthy_threshold = unhealthy_threshold
        self._probes: list[dict] = []
        self._status = HealthStatus.UNKNOWN
        self._consecutive_failures = 0
        self._last_check_time: float = 0.0
        self._check_history: list[dict] = []
        self._max_history = 100

    def add_http_probe(self, url: str, expected_status: int = 200) -> None:
        """Add an HTTP health probe.

        Args:
            url: URL to check (e.g., http://localhost:8080/api/health).
            expected_status: Expected HTTP status code.
        """
        self._probes.append({
            "type": "http",
            "url": url,
            "expected_status": expected_status,
        })

    def add_tcp_probe(self, host: str, port: int) -> None:
        """Add a TCP connectivity probe.

        Args:
            host: Host to connect to.
            port: Port to connect to.
        """
        self._probes.append({
            "type": "tcp",
            "host": host,
            "port": port,
        })

    def add_callback_probe(
        self, callback: Callable[[], bool], name: str = "custom"
    ) -> None:
        """Add a custom callback health probe.

        Args:
            callback: Function returning True if healthy, False otherwise.
            name: Descriptive name for the probe.
        """
        self._probes.append({
            "type": "callback",
            "callback": callback,
            "name": name,
        })

    def check(self) -> HealthStatus:
        """Run all health probes and update status.

        Returns:
            Current health status.
        """
        if not self._probes:
            return HealthStatus.HEALTHY

        results = []
        for probe in self._probes:
            try:
                if probe["type"] == "http":
                    ok = self._check_http(probe["url"], probe["expected_status"])
                elif probe["type"] == "tcp":
                    ok = self._check_tcp(probe["host"], probe["port"])
                elif probe["type"] == "callback":
                    ok = probe["callback"]()
                else:
                    ok = True
                results.append(ok)
            except Exception as e:
                logger.debug("Health probe failed: %s", e)
                results.append(False)

        all_ok = all(results)
        any_ok = any(results)

        if all_ok:
            self._consecutive_failures = 0
            self._status = HealthStatus.HEALTHY
        elif any_ok:
            self._consecutive_failures += 1
            self._status = HealthStatus.DEGRADED
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.unhealthy_threshold:
                self._status = HealthStatus.UNHEALTHY
            else:
                self._status = HealthStatus.DEGRADED

        self._last_check_time = time.time()
        record = {
            "time": self._last_check_time,
            "status": self._status.value,
            "results": results,
            "consecutive_failures": self._consecutive_failures,
        }
        self._check_history.append(record)
        if len(self._check_history) > self._max_history:
            self._check_history = self._check_history[-self._max_history:]

        return self._status

    def _check_http(self, url: str, expected_status: int) -> bool:
        """Check HTTP health endpoint."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            return resp.status == expected_status
        except (urllib.error.URLError, OSError):
            return False

    def _check_tcp(self, host: str, port: int) -> bool:
        """Check TCP port connectivity."""
        import socket

        try:
            with socket.create_connection((host, port), timeout=self.timeout):
                return True
        except (OSError, ConnectionRefusedError):
            return False

    @property
    def status(self) -> HealthStatus:
        """Get current health status."""
        return self._status

    def get_report(self) -> dict:
        """Get health check report."""
        return {
            "status": self._status.value,
            "consecutive_failures": self._consecutive_failures,
            "last_check_time": self._last_check_time,
            "probe_count": len(self._probes),
            "recent_history": self._check_history[-10:],
        }


class ProcessGuardian:
    """Production-grade process guardian with health checks and auto-restart.

    Monitors a child process and provides:
    - Automatic restart on crash with configurable backoff
    - Health check integration
    - PID file management
    - Signal-aware graceful shutdown
    - Child process log forwarding
    """

    def __init__(
        self,
        max_restarts: int = 10,
        restart_delay: float = 3.0,
        restart_window: float = 300.0,
        backoff_multiplier: float = 1.5,
        max_backoff: float = 60.0,
        pid_file: Optional[str] = None,
        health_checker: Optional[HealthChecker] = None,
        on_restart: Optional[Callable[[int, int], None]] = None,
        on_failure: Optional[Callable[[int], None]] = None,
    ):
        """Initialize the process guardian.

        Args:
            max_restarts: Maximum restarts within the window before giving up.
            restart_delay: Initial seconds to wait before restarting.
            restart_window: Time window (seconds) for counting restarts.
            backoff_multiplier: Multiply delay by this on each consecutive restart.
            max_backoff: Maximum delay between restarts.
            pid_file: Path for PID file. None to disable.
            health_checker: Optional health checker for proactive monitoring.
            on_restart: Callback(restart_count, exit_code) on each restart.
            on_failure: Callback(total_restarts) when max restarts exceeded.
        """
        self.max_restarts = max_restarts
        self.restart_delay = restart_delay
        self.restart_window = restart_window
        self.backoff_multiplier = backoff_multiplier
        self.max_backoff = max_backoff
        self.on_restart = on_restart
        self.on_failure = on_failure

        self._restart_times: list[float] = []
        self._process: Optional[subprocess.Popen] = None
        self._should_run = True
        self._current_delay = restart_delay
        self._total_restarts = 0
        self._start_time: float = 0.0

        # PID file management
        self._pid_file: Optional[PidFile] = None
        if pid_file:
            self._pid_file = PidFile(pid_file)

        # Health checker
        self._health_checker = health_checker
        self._health_thread: Optional[threading.Thread] = None

    def start(self, command: list[str], env: Optional[dict] = None) -> None:
        """Start and monitor a child process.

        Args:
            command: Command and arguments to run.
            env: Optional environment variables for the child process.
        """
        # Acquire PID file
        if self._pid_file and not self._pid_file.acquire():
            raise RuntimeError("Another instance is already running")

        # Handle signals
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self._start_time = time.time()
        logger.info("Guardian started, monitoring command: %s", " ".join(command))

        # Start health check thread
        if self._health_checker:
            self._health_thread = threading.Thread(
                target=self._health_check_loop,
                daemon=True,
                name="guardian-health",
            )
            self._health_thread.start()

        try:
            self._supervision_loop(command, env)
        finally:
            if self._pid_file:
                self._pid_file.release()

    def _supervision_loop(
        self, command: list[str], env: Optional[dict] = None
    ) -> None:
        """Main supervision loop with restart logic."""
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        while self._should_run:
            # Check restart budget
            now = time.time()
            self._restart_times = [
                t for t in self._restart_times if now - t < self.restart_window
            ]
            if len(self._restart_times) >= self.max_restarts:
                logger.error(
                    "Max restarts (%d) reached within %ds window. Giving up.",
                    self.max_restarts,
                    self.restart_window,
                )
                if self.on_failure:
                    self.on_failure(self._total_restarts)
                break

            # Start the child process
            try:
                logger.info("Starting child process (attempt %d)...",
                            self._total_restarts + 1)
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=process_env,
                )
                self._restart_times.append(time.time())

                # Forward child stdout in a thread
                log_thread = threading.Thread(
                    target=self._forward_output,
                    args=(self._process,),
                    daemon=True,
                    name="guardian-log",
                )
                log_thread.start()

                # Wait for process to exit
                returncode = self._process.wait()

                if returncode == 0 or not self._should_run:
                    logger.info(
                        "Child process exited normally (code %d)", returncode
                    )
                    break
                else:
                    self._total_restarts += 1
                    logger.warning(
                        "Child process crashed (code %d, restart #%d). "
                        "Restarting in %.1fs...",
                        returncode,
                        self._total_restarts,
                        self._current_delay,
                    )

                    if self.on_restart:
                        self.on_restart(self._total_restarts, returncode)

                    # Wait with backoff
                    if self._interruptible_sleep(self._current_delay):
                        break  # Interrupted by stop signal

                    # Apply exponential backoff
                    self._current_delay = min(
                        self._current_delay * self.backoff_multiplier,
                        self.max_backoff,
                    )

            except OSError as e:
                logger.error("Failed to start child process: %s", e)
                break

    def _forward_output(self, process: subprocess.Popen) -> None:
        """Forward child process stdout to logger."""
        if process.stdout is None:
            return
        try:
            for line in iter(process.stdout.readline, b""):
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.info("[child] %s", text)
        except (OSError, ValueError):
            pass

    def _health_check_loop(self) -> None:
        """Periodic health check loop."""
        if not self._health_checker:
            return

        while self._should_run:
            time.sleep(self._health_checker.interval)
            if not self._should_run:
                break

            status = self._health_checker.check()
            if status == HealthStatus.UNHEALTHY:
                logger.error(
                    "Health check UNHEALTHY (%d consecutive failures). "
                    "Forcing child restart...",
                    self._health_checker._consecutive_failures,
                )
                self._force_restart()

    def _force_restart(self) -> None:
        """Force restart the child process due to health check failure."""
        if self._process and self._process.poll() is None:
            logger.warning("Sending SIGTERM to child (PID %d)...",
                           self._process.pid)
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Child did not stop, sending SIGKILL...")
                self._process.kill()

    def _interruptible_sleep(self, duration: float) -> bool:
        """Sleep that can be interrupted by stop signal.

        Returns:
            True if interrupted (should stop), False if completed normally.
        """
        end_time = time.time() + duration
        while time.time() < end_time:
            if not self._should_run:
                return True
            time.sleep(min(0.5, end_time - time.time()))
        return False

    def stop(self) -> None:
        """Stop the guardian and child process gracefully."""
        self._should_run = False
        if self._process and self._process.poll() is None:
            logger.info("Stopping child process (PID %d)...", self._process.pid)
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Child process did not stop, killing...")
                self._process.kill()
                self._process.wait(timeout=5)

    def _signal_handler(self, signum: int, frame: object) -> None:
        """Handle termination signals."""
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.info("Received signal %s, shutting down...", sig_name)
        self.stop()

    def get_status(self) -> dict:
        """Get guardian status report."""
        child_pid = self._process.pid if self._process and self._process.poll() is None else None
        uptime = time.time() - self._start_time if self._start_time else 0

        result = {
            "running": self._should_run,
            "child_pid": child_pid,
            "total_restarts": self._total_restarts,
            "uptime_seconds": round(uptime, 1),
            "current_backoff": round(self._current_delay, 1),
            "restarts_in_window": len(self._restart_times),
            "max_restarts": self.max_restarts,
        }

        if self._health_checker:
            result["health"] = self._health_checker.get_report()

        return result
