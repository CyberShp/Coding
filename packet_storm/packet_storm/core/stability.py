"""Long-running stability test framework.

Provides infrastructure for extended stability/endurance testing with:
- Configurable test duration (hours/days)
- Periodic health checks and status reporting
- Memory leak detection (process RSS monitoring)
- Automatic report generation at intervals
- Graceful handling of system resource limits
"""

import os
import time
import json
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional, Callable
from dataclasses import dataclass, field

from .engine import PacketStormEngine
from .config import ConfigManager
from .session import SessionState
from ..utils.logging import get_logger

logger = get_logger("stability")


@dataclass
class StabilityCheckpoint:
    """A snapshot of system state at a specific time."""
    timestamp: float
    elapsed_seconds: float
    packets_sent: int
    packets_failed: int
    anomalies_applied: int
    bytes_sent: int
    send_rate_pps: float
    success_rate: float
    memory_rss_mb: float
    error_count: int
    session_state: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "elapsed_hours": round(self.elapsed_seconds / 3600, 2),
            "packets_sent": self.packets_sent,
            "packets_failed": self.packets_failed,
            "anomalies_applied": self.anomalies_applied,
            "bytes_sent": self.bytes_sent,
            "send_rate_pps": round(self.send_rate_pps, 1),
            "success_rate": round(self.success_rate, 4),
            "memory_rss_mb": round(self.memory_rss_mb, 2),
            "error_count": self.error_count,
            "session_state": self.session_state,
        }


@dataclass
class StabilityReport:
    """Complete stability test report."""
    test_name: str
    start_time: float
    end_time: float = 0.0
    target_duration_hours: float = 0.0
    completed: bool = False
    checkpoints: list[StabilityCheckpoint] = field(default_factory=list)
    anomalies_detected: list[str] = field(default_factory=list)
    final_stats: dict = field(default_factory=dict)

    @property
    def duration_hours(self) -> float:
        end = self.end_time if self.end_time > 0 else time.time()
        return (end - self.start_time) / 3600

    @property
    def memory_trend(self) -> str:
        """Analyze memory usage trend."""
        if len(self.checkpoints) < 3:
            return "insufficient_data"

        mem_values = [cp.memory_rss_mb for cp in self.checkpoints]
        first_third = sum(mem_values[:len(mem_values) // 3]) / (len(mem_values) // 3)
        last_third = sum(mem_values[-len(mem_values) // 3:]) / (len(mem_values) // 3)

        growth = (last_third - first_third) / first_third if first_third > 0 else 0

        if growth > 0.5:
            return "memory_leak_suspected"
        elif growth > 0.2:
            return "gradual_increase"
        elif growth < -0.1:
            return "decreasing"
        else:
            return "stable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_name": self.test_name,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time).isoformat()
            if self.end_time > 0 else None,
            "duration_hours": round(self.duration_hours, 2),
            "target_duration_hours": self.target_duration_hours,
            "completed": self.completed,
            "memory_trend": self.memory_trend,
            "anomalies_detected": self.anomalies_detected,
            "checkpoint_count": len(self.checkpoints),
            "checkpoints": [cp.to_dict() for cp in self.checkpoints],
            "final_stats": self.final_stats,
        }

    def export_json(self, path: str) -> None:
        """Export report as JSON."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Stability report exported to %s", output)


class StabilityRunner:
    """Long-running stability test runner.

    Runs the packet storm engine for an extended duration while
    periodically collecting health metrics and generating reports.

    Usage:
        runner = StabilityRunner(
            config_path="config.json",
            duration_hours=72,
            report_interval_minutes=30,
        )
        report = runner.run()
        report.export_json("stability_report.json")
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        duration_hours: float = 72.0,
        checkpoint_interval_minutes: float = 15.0,
        report_interval_minutes: float = 60.0,
        report_dir: str = "reports/stability",
        memory_limit_mb: float = 0,
        on_checkpoint: Optional[Callable[[StabilityCheckpoint], None]] = None,
        on_anomaly: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the stability runner.

        Args:
            config_path: Path to test configuration file.
            duration_hours: Target test duration in hours.
            checkpoint_interval_minutes: Minutes between health checkpoints.
            report_interval_minutes: Minutes between periodic report exports.
            report_dir: Directory for periodic report files.
            memory_limit_mb: Memory limit in MB (0=unlimited). Test stops if exceeded.
            on_checkpoint: Callback when a checkpoint is recorded.
            on_anomaly: Callback when an anomaly is detected.
        """
        self.config_path = config_path
        self.duration_hours = duration_hours
        self.checkpoint_interval = checkpoint_interval_minutes * 60
        self.report_interval = report_interval_minutes * 60
        self.report_dir = report_dir
        self.memory_limit_mb = memory_limit_mb
        self.on_checkpoint = on_checkpoint
        self.on_anomaly = on_anomaly

        self._engine: Optional[PacketStormEngine] = None
        self._should_stop = False
        self._report: Optional[StabilityReport] = None

    def run(self, test_name: str = "stability_test") -> StabilityReport:
        """Execute the stability test.

        Args:
            test_name: Name for this test run.

        Returns:
            StabilityReport with all checkpoints and findings.
        """
        self._report = StabilityReport(
            test_name=test_name,
            start_time=time.time(),
            target_duration_hours=self.duration_hours,
        )

        target_end = time.time() + (self.duration_hours * 3600)
        self._should_stop = False

        logger.info(
            "Starting stability test '%s' for %.1f hours",
            test_name, self.duration_hours,
        )

        try:
            # Setup engine
            config_mgr = ConfigManager(self.config_path)
            # Set duration to unlimited for stability test
            config_mgr.set("execution.duration_seconds", 0)
            config_mgr.set("execution.repeat", 0)

            self._import_protocols()

            self._engine = PacketStormEngine(config_mgr)
            self._engine.setup()
            self._engine.start()

            # Monitoring loop
            last_checkpoint = 0.0
            last_report = 0.0
            prev_error_count = 0

            while not self._should_stop and time.time() < target_end:
                now = time.time()

                # Check engine health
                if self._engine.session and not self._engine.session.is_active:
                    if self._engine.session.state == SessionState.ERROR:
                        self._record_anomaly(
                            f"Engine entered ERROR state at "
                            f"{self._elapsed_str()}"
                        )
                        # Attempt restart
                        logger.warning("Engine stopped, attempting restart...")
                        try:
                            self._engine.setup()
                            self._engine.start()
                            self._record_anomaly(
                                f"Engine restarted at {self._elapsed_str()}"
                            )
                        except Exception as e:
                            self._record_anomaly(
                                f"Engine restart failed: {e}"
                            )
                            break
                    elif self._engine.session.state == SessionState.COMPLETED:
                        # Restart engine for continuous operation
                        try:
                            self._engine.setup()
                            self._engine.start()
                        except Exception as e:
                            self._record_anomaly(
                                f"Engine cycle restart failed: {e}"
                            )
                            break

                # Periodic checkpoint
                if now - last_checkpoint >= self.checkpoint_interval:
                    cp = self._take_checkpoint()
                    self._report.checkpoints.append(cp)
                    last_checkpoint = now

                    if self.on_checkpoint:
                        self.on_checkpoint(cp)

                    # Check for anomalies in checkpoint
                    if self._engine.session:
                        current_errors = len(self._engine.session.stats.errors)
                        if current_errors > prev_error_count + 10:
                            self._record_anomaly(
                                f"Error spike: {current_errors - prev_error_count} "
                                f"new errors at {self._elapsed_str()}"
                            )
                        prev_error_count = current_errors

                    # Memory check
                    if self.memory_limit_mb > 0 and cp.memory_rss_mb > self.memory_limit_mb:
                        self._record_anomaly(
                            f"Memory limit exceeded: {cp.memory_rss_mb:.1f}MB "
                            f"> {self.memory_limit_mb:.1f}MB"
                        )
                        logger.error("Memory limit exceeded, stopping test")
                        break

                # Periodic report export
                if now - last_report >= self.report_interval:
                    self._export_periodic_report()
                    last_report = now

                # Sleep between checks
                time.sleep(min(10.0, self.checkpoint_interval / 2))

            # Finalize
            self._report.completed = time.time() >= target_end
            self._finalize()

        except Exception as e:
            logger.error("Stability test error: %s", e, exc_info=True)
            self._record_anomaly(f"Fatal error: {e}")
            self._report.completed = False
        finally:
            if self._engine:
                self._engine.stop()

        self._report.end_time = time.time()

        logger.info(
            "Stability test '%s' %s after %.1f hours (%d checkpoints, %d anomalies)",
            test_name,
            "completed" if self._report.completed else "stopped early",
            self._report.duration_hours,
            len(self._report.checkpoints),
            len(self._report.anomalies_detected),
        )

        return self._report

    def stop(self) -> None:
        """Signal the stability test to stop."""
        self._should_stop = True
        logger.info("Stability test stop requested")

    def _take_checkpoint(self) -> StabilityCheckpoint:
        """Capture current system state as a checkpoint."""
        elapsed = time.time() - self._report.start_time

        # Get engine stats
        packets_sent = 0
        packets_failed = 0
        anomalies_applied = 0
        bytes_sent = 0
        send_rate = 0.0
        success_rate = 0.0
        error_count = 0
        session_state = "unknown"

        if self._engine and self._engine.session:
            stats = self._engine.session.stats
            packets_sent = stats.packets_sent
            packets_failed = stats.packets_failed
            anomalies_applied = stats.anomalies_applied
            bytes_sent = stats.bytes_sent
            send_rate = stats.send_rate_pps
            success_rate = stats.success_rate
            error_count = len(stats.errors)
            session_state = self._engine.session.state.value

        # Get memory usage
        memory_mb = self._get_memory_rss_mb()

        cp = StabilityCheckpoint(
            timestamp=time.time(),
            elapsed_seconds=elapsed,
            packets_sent=packets_sent,
            packets_failed=packets_failed,
            anomalies_applied=anomalies_applied,
            bytes_sent=bytes_sent,
            send_rate_pps=send_rate,
            success_rate=success_rate,
            memory_rss_mb=memory_mb,
            error_count=error_count,
            session_state=session_state,
        )

        logger.info(
            "Checkpoint [%.1fh]: %d pkts, %.0f pps, %.1f MB RSS, %s",
            elapsed / 3600,
            packets_sent,
            send_rate,
            memory_mb,
            session_state,
        )

        return cp

    def _record_anomaly(self, message: str) -> None:
        """Record a detected anomaly."""
        stamped = f"[{datetime.now().isoformat()}] {message}"
        self._report.anomalies_detected.append(stamped)
        logger.warning("Stability anomaly: %s", message)
        if self.on_anomaly:
            self.on_anomaly(stamped)

    def _export_periodic_report(self) -> None:
        """Export intermediate report."""
        if not self._report:
            return
        report_path = Path(self.report_dir)
        report_path.mkdir(parents=True, exist_ok=True)
        filename = (
            f"{self._report.test_name}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        self._report.export_json(str(report_path / filename))

    def _finalize(self) -> None:
        """Collect final statistics."""
        if self._engine and self._engine.session:
            self._report.final_stats = self._engine.session.stats.to_dict()

        # Memory trend analysis
        trend = self._report.memory_trend
        if trend == "memory_leak_suspected":
            self._record_anomaly(
                "Memory trend analysis suggests potential memory leak"
            )

    def _elapsed_str(self) -> str:
        """Get human-readable elapsed time string."""
        if not self._report:
            return "N/A"
        elapsed = time.time() - self._report.start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        return f"{hours}h{minutes:02d}m"

    @staticmethod
    def _get_memory_rss_mb() -> float:
        """Get current process RSS memory in MB."""
        try:
            # Linux: read from /proc/self/status
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # Value is in kB
                        kb = int(line.split()[1])
                        return kb / 1024.0
        except (OSError, IndexError, ValueError):
            pass

        try:
            # macOS/BSD: use resource module
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            # ru_maxrss is in bytes on macOS, KB on Linux
            import sys
            if sys.platform == "darwin":
                return usage.ru_maxrss / (1024 * 1024)
            else:
                return usage.ru_maxrss / 1024
        except (ImportError, AttributeError):
            pass

        return 0.0

    @staticmethod
    def _import_protocols() -> None:
        """Import protocol modules for registration."""
        try:
            import packet_storm.protocols.iscsi  # noqa: F401
        except ImportError:
            pass
        try:
            import packet_storm.transport  # noqa: F401
        except ImportError:
            pass
        try:
            import packet_storm.anomaly  # noqa: F401
        except ImportError:
            pass
