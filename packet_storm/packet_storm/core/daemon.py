"""Process guardian daemon for auto-restart on crashes."""

import os
import sys
import time
import signal
import subprocess
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger("daemon")


class ProcessGuardian:
    """Monitors a child process and restarts it on crashes.

    Implements watchdog functionality to ensure the packet storm engine
    continues running even after unexpected failures.
    """

    def __init__(
        self,
        max_restarts: int = 10,
        restart_delay: float = 3.0,
        restart_window: float = 300.0,
    ):
        """Initialize the process guardian.

        Args:
            max_restarts: Maximum restarts within the window before giving up.
            restart_delay: Seconds to wait before restarting.
            restart_window: Time window (seconds) for counting restarts.
        """
        self.max_restarts = max_restarts
        self.restart_delay = restart_delay
        self.restart_window = restart_window
        self._restart_times: list[float] = []
        self._process: Optional[subprocess.Popen] = None
        self._should_run = True

    def start(self, command: list[str]) -> None:
        """Start and monitor a child process.

        Args:
            command: Command and arguments to run.
        """
        # Handle SIGTERM gracefully
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info("Guardian started, monitoring command: %s", " ".join(command))

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
                break

            # Start the child process
            try:
                logger.info("Starting child process...")
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                self._restart_times.append(time.time())

                # Wait for process to exit
                returncode = self._process.wait()

                if returncode == 0 or not self._should_run:
                    logger.info("Child process exited normally (code %d)", returncode)
                    break
                else:
                    logger.warning(
                        "Child process crashed (code %d). Restarting in %ds...",
                        returncode,
                        self.restart_delay,
                    )
                    time.sleep(self.restart_delay)

            except OSError as e:
                logger.error("Failed to start child process: %s", e)
                break

    def stop(self) -> None:
        """Stop the guardian and child process."""
        self._should_run = False
        if self._process and self._process.poll() is None:
            logger.info("Stopping child process (PID %d)...", self._process.pid)
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Child process did not stop, killing...")
                self._process.kill()

    def _signal_handler(self, signum: int, frame: object) -> None:
        """Handle termination signals."""
        logger.info("Received signal %d, shutting down...", signum)
        self.stop()
