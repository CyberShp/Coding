"""Test session lifecycle management.

A Session encapsulates a complete test run: configuration, packet generation,
sending, and result collection.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from ..utils.logging import get_logger

logger = get_logger("session")


class SessionState(str, Enum):
    """Session lifecycle states."""
    CREATED = "created"
    CONFIGURING = "configuring"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class SessionStats:
    """Statistics collected during a test session."""
    packets_sent: int = 0
    packets_failed: int = 0
    anomalies_applied: int = 0
    bytes_sent: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Session duration in seconds."""
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    @property
    def send_rate_pps(self) -> float:
        """Average send rate in packets per second."""
        d = self.duration
        return self.packets_sent / d if d > 0 else 0.0

    @property
    def send_rate_mbps(self) -> float:
        """Average send rate in megabits per second."""
        d = self.duration
        return (self.bytes_sent * 8 / 1_000_000) / d if d > 0 else 0.0

    @property
    def success_rate(self) -> float:
        """Packet send success rate (0.0 - 1.0)."""
        total = self.packets_sent + self.packets_failed
        return self.packets_sent / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to a dictionary."""
        return {
            "packets_sent": self.packets_sent,
            "packets_failed": self.packets_failed,
            "anomalies_applied": self.anomalies_applied,
            "bytes_sent": self.bytes_sent,
            "duration_seconds": round(self.duration, 3),
            "send_rate_pps": round(self.send_rate_pps, 2),
            "send_rate_mbps": round(self.send_rate_mbps, 4),
            "success_rate": round(self.success_rate, 4),
            "errors": self.errors[-10:],  # Last 10 errors
        }


class Session:
    """Manages the lifecycle of a single test session.

    A session coordinates between the config, anomaly engine, protocol builder,
    and transport backend to execute a test scenario.
    """

    _next_id: int = 0

    def __init__(self, config: dict, session_id: Optional[str] = None):
        """Initialize a test session.

        Args:
            config: Full configuration dictionary for this session.
            session_id: Optional custom session ID. Auto-generated if None.
        """
        Session._next_id += 1
        self.session_id = session_id or f"session-{Session._next_id:04d}"
        self.config = config
        self.state = SessionState.CREATED
        self.stats = SessionStats()
        self._created_at = time.time()

        logger.info("Session created: %s", self.session_id)

    def transition(self, new_state: SessionState) -> None:
        """Transition to a new session state.

        Args:
            new_state: The target state.

        Raises:
            StateTransitionError: If the transition is not valid.
        """
        valid_transitions = {
            SessionState.CREATED: {SessionState.CONFIGURING, SessionState.READY},
            SessionState.CONFIGURING: {SessionState.READY, SessionState.ERROR},
            SessionState.READY: {SessionState.RUNNING, SessionState.ERROR},
            SessionState.RUNNING: {
                SessionState.PAUSED,
                SessionState.STOPPING,
                SessionState.COMPLETED,
                SessionState.ERROR,
            },
            SessionState.PAUSED: {
                SessionState.RUNNING,
                SessionState.STOPPING,
                SessionState.ERROR,
            },
            SessionState.STOPPING: {SessionState.COMPLETED, SessionState.ERROR},
            SessionState.COMPLETED: set(),
            SessionState.ERROR: {SessionState.READY},  # Allow retry
        }

        allowed = valid_transitions.get(self.state, set())
        if new_state not in allowed:
            raise StateTransitionError(
                f"Cannot transition from {self.state.value} to {new_state.value}. "
                f"Allowed: {', '.join(s.value for s in allowed)}"
            )

        old_state = self.state
        self.state = new_state

        if new_state == SessionState.RUNNING and self.stats.start_time == 0:
            self.stats.start_time = time.time()
        elif new_state in (SessionState.COMPLETED, SessionState.ERROR):
            self.stats.end_time = time.time()

        logger.info(
            "Session %s: %s -> %s", self.session_id, old_state.value, new_state.value
        )

    def record_send(self, packet_size: int) -> None:
        """Record a successful packet send."""
        self.stats.packets_sent += 1
        self.stats.bytes_sent += packet_size

    def record_failure(self, error: str = "") -> None:
        """Record a failed packet send."""
        self.stats.packets_failed += 1
        if error:
            self.stats.errors.append(error)

    def record_anomaly(self) -> None:
        """Record an anomaly application."""
        self.stats.anomalies_applied += 1

    @property
    def is_active(self) -> bool:
        """Check if the session is in an active state."""
        return self.state in (SessionState.RUNNING, SessionState.PAUSED)

    def to_dict(self) -> dict[str, Any]:
        """Serialize session state to a dictionary."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "protocol": self.config.get("protocol", {}).get("type", "unknown"),
            "created_at": self._created_at,
            "stats": self.stats.to_dict(),
        }


class StateTransitionError(Exception):
    """Raised when an invalid session state transition is attempted."""
    pass
