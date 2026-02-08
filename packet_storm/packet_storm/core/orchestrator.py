"""Batch test orchestrator for running multiple test scenarios.

Provides structured execution of test scenario sequences with:
- Sequential and parallel scenario execution
- Per-scenario and aggregate result collection
- Configurable stop-on-failure behavior
- Inter-scenario delays and setup hooks
- Progress reporting and result export
"""

import json
import time
import copy
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional, Callable
from enum import Enum

from .config import ConfigManager
from .engine import PacketStormEngine
from .session import SessionState
from ..utils.logging import get_logger

logger = get_logger("orchestrator")


class ScenarioStatus(str, Enum):
    """Execution status of a single scenario."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ScenarioResult:
    """Result of a single test scenario execution."""
    scenario_id: str
    name: str
    status: ScenarioStatus = ScenarioStatus.PENDING
    start_time: float = 0.0
    end_time: float = 0.0
    packets_sent: int = 0
    packets_failed: int = 0
    anomalies_applied: int = 0
    bytes_sent: int = 0
    errors: list[str] = field(default_factory=list)
    config_snapshot: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    @property
    def success_rate(self) -> float:
        total = self.packets_sent + self.packets_failed
        return self.packets_sent / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "status": self.status.value,
            "duration_seconds": round(self.duration, 3),
            "packets_sent": self.packets_sent,
            "packets_failed": self.packets_failed,
            "anomalies_applied": self.anomalies_applied,
            "bytes_sent": self.bytes_sent,
            "success_rate": round(self.success_rate, 4),
            "errors": self.errors[-5:],
        }


@dataclass
class BatchResult:
    """Aggregate result of a batch test run."""
    batch_id: str
    start_time: float = 0.0
    end_time: float = 0.0
    scenarios: list[ScenarioResult] = field(default_factory=list)

    @property
    def total_scenarios(self) -> int:
        return len(self.scenarios)

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.scenarios if s.status == ScenarioStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.scenarios if s.status == ScenarioStatus.FAILED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.scenarios if s.status == ScenarioStatus.SKIPPED)

    @property
    def total_packets(self) -> int:
        return sum(s.packets_sent for s in self.scenarios)

    @property
    def total_bytes(self) -> int:
        return sum(s.bytes_sent for s in self.scenarios)

    @property
    def duration(self) -> float:
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    @property
    def all_passed(self) -> bool:
        return all(
            s.status == ScenarioStatus.COMPLETED
            for s in self.scenarios
            if s.status != ScenarioStatus.SKIPPED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "duration_seconds": round(self.duration, 3),
            "total_scenarios": self.total_scenarios,
            "completed": self.completed_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "all_passed": self.all_passed,
            "total_packets": self.total_packets,
            "total_bytes": self.total_bytes,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }

    def export_json(self, path: str) -> None:
        """Export batch result as JSON.

        Args:
            path: Output file path.
        """
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Batch result exported to %s", output)


class BatchOrchestrator:
    """Orchestrates the execution of multiple test scenarios.

    Supports:
    - Loading scenarios from JSON batch files
    - Sequential execution with configurable delays
    - Stop-on-failure behavior
    - Progress callbacks for UI integration
    - Aggregate result collection and export
    """

    def __init__(
        self,
        base_config_path: Optional[str] = None,
        stop_on_failure: bool = False,
        inter_scenario_delay: float = 2.0,
        on_progress: Optional[Callable[[int, int, ScenarioResult], None]] = None,
        on_scenario_start: Optional[Callable[[int, str], None]] = None,
    ):
        """Initialize the batch orchestrator.

        Args:
            base_config_path: Base configuration file to merge scenario overrides into.
            stop_on_failure: Stop batch execution if any scenario fails.
            inter_scenario_delay: Seconds to wait between scenarios.
            on_progress: Callback(current, total, result) after each scenario.
            on_scenario_start: Callback(index, name) when scenario starts.
        """
        self.base_config_path = base_config_path
        self.stop_on_failure = stop_on_failure
        self.inter_scenario_delay = inter_scenario_delay
        self.on_progress = on_progress
        self.on_scenario_start = on_scenario_start
        self._should_stop = False

    def load_batch_file(self, path: str) -> list[dict]:
        """Load test scenarios from a JSON batch file.

        Expected format:
        ```json
        {
            "batch_name": "iSCSI Comprehensive Test",
            "description": "Full iSCSI protocol anomaly test suite",
            "scenarios": [
                {
                    "name": "Login Opcode Fuzz",
                    "description": "Test invalid login opcodes",
                    "config_overrides": {
                        "protocol.type": "iscsi",
                        "execution.repeat": 100
                    },
                    "anomalies": [...]
                }
            ]
        }
        ```

        Args:
            path: Path to the batch JSON file.

        Returns:
            List of scenario dictionaries.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return data.get("scenarios", [data])
        else:
            raise ValueError(f"Invalid batch file format: {path}")

    def run_batch(
        self,
        scenarios: list[dict],
        batch_id: Optional[str] = None,
    ) -> BatchResult:
        """Execute a batch of test scenarios sequentially.

        Args:
            scenarios: List of scenario configuration dicts.
            batch_id: Optional batch identifier.

        Returns:
            BatchResult with aggregate results.
        """
        if batch_id is None:
            batch_id = f"batch-{int(time.time())}"

        result = BatchResult(batch_id=batch_id)
        result.start_time = time.time()

        self._should_stop = False
        total = len(scenarios)
        logger.info("Starting batch '%s' with %d scenarios", batch_id, total)

        for idx, scenario_cfg in enumerate(scenarios):
            if self._should_stop:
                # Mark remaining as skipped
                for remaining in scenarios[idx:]:
                    skip_result = ScenarioResult(
                        scenario_id=f"{batch_id}-{idx + 1}",
                        name=remaining.get("name", f"Scenario {idx + 1}"),
                        status=ScenarioStatus.SKIPPED,
                    )
                    result.scenarios.append(skip_result)
                break

            name = scenario_cfg.get("name", f"Scenario {idx + 1}")
            scenario_id = f"{batch_id}-{idx + 1}"

            logger.info(
                "Running scenario %d/%d: %s", idx + 1, total, name
            )

            if self.on_scenario_start:
                self.on_scenario_start(idx, name)

            scenario_result = self._run_single_scenario(
                scenario_cfg, scenario_id, name
            )
            result.scenarios.append(scenario_result)

            if self.on_progress:
                self.on_progress(idx + 1, total, scenario_result)

            # Check stop-on-failure
            if (
                scenario_result.status == ScenarioStatus.FAILED
                and self.stop_on_failure
            ):
                logger.warning(
                    "Scenario '%s' failed and stop_on_failure=True. "
                    "Aborting batch.", name
                )
                self._should_stop = True
                continue

            # Inter-scenario delay
            if idx < total - 1 and self.inter_scenario_delay > 0:
                logger.debug(
                    "Waiting %.1fs before next scenario...",
                    self.inter_scenario_delay,
                )
                time.sleep(self.inter_scenario_delay)

        result.end_time = time.time()
        logger.info(
            "Batch '%s' complete: %d/%d passed, %d failed, %d skipped (%.1fs)",
            batch_id,
            result.completed_count,
            result.total_scenarios,
            result.failed_count,
            result.skipped_count,
            result.duration,
        )
        return result

    def _run_single_scenario(
        self,
        scenario_cfg: dict,
        scenario_id: str,
        name: str,
    ) -> ScenarioResult:
        """Execute a single test scenario.

        Args:
            scenario_cfg: Scenario configuration dict.
            scenario_id: Unique scenario identifier.
            name: Human-readable scenario name.

        Returns:
            ScenarioResult for this scenario.
        """
        result = ScenarioResult(
            scenario_id=scenario_id,
            name=name,
            status=ScenarioStatus.RUNNING,
        )
        result.start_time = time.time()

        try:
            # Build configuration
            config_mgr = ConfigManager(self.base_config_path)

            # Apply scenario overrides
            overrides = scenario_cfg.get("config_overrides", {})
            for key_path, value in overrides.items():
                config_mgr.set(key_path, value)

            # Apply anomalies if specified
            if "anomalies" in scenario_cfg:
                config_mgr.set("anomalies", scenario_cfg["anomalies"])

            # Apply execution settings
            if "execution" in scenario_cfg:
                for key, value in scenario_cfg["execution"].items():
                    config_mgr.set(f"execution.{key}", value)

            result.config_snapshot = copy.deepcopy(config_mgr.config)

            # Import protocols for registration
            self._import_protocols()

            # Create and run engine
            engine = PacketStormEngine(config_mgr)
            engine.setup()
            engine.start()

            # Wait for completion
            while engine.session and engine.session.is_active:
                if self._should_stop:
                    engine.stop()
                    break
                time.sleep(0.5)

            # Collect results
            if engine.session:
                stats = engine.session.stats
                result.packets_sent = stats.packets_sent
                result.packets_failed = stats.packets_failed
                result.anomalies_applied = stats.anomalies_applied
                result.bytes_sent = stats.bytes_sent
                result.errors = list(stats.errors[-10:])

                if engine.session.state == SessionState.ERROR:
                    result.status = ScenarioStatus.FAILED
                else:
                    result.status = ScenarioStatus.COMPLETED

            engine.stop()

        except Exception as e:
            logger.error("Scenario '%s' error: %s", name, e, exc_info=True)
            result.status = ScenarioStatus.FAILED
            result.errors.append(str(e))

        result.end_time = time.time()
        logger.info(
            "Scenario '%s' finished: %s (%d packets, %.1fs)",
            name, result.status.value, result.packets_sent, result.duration,
        )
        return result

    def stop(self) -> None:
        """Signal the orchestrator to stop after current scenario."""
        self._should_stop = True
        logger.info("Batch stop requested")

    @staticmethod
    def _import_protocols() -> None:
        """Import protocol modules to trigger registration."""
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
