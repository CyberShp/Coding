"""Auto-reconnecting transport wrapper with retry policies.

Wraps any TransportBackend with automatic reconnection logic:
- Configurable retry policies (fixed, exponential, linear backoff)
- Connection health monitoring
- Seamless reconnection on send failures
- Statistics tracking for reconnection events
"""

import time
import threading
from typing import Any, Optional
from enum import Enum

from .base import TransportBackend, TransportError
from ..utils.logging import get_logger

logger = get_logger("transport.reconnect")


class RetryPolicy(str, Enum):
    """Retry backoff strategy."""
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


class ReconnectConfig:
    """Configuration for auto-reconnect behavior."""

    def __init__(
        self,
        enabled: bool = True,
        max_retries: int = 10,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        policy: RetryPolicy = RetryPolicy.EXPONENTIAL,
        backoff_multiplier: float = 2.0,
        linear_increment: float = 2.0,
        health_check_interval: float = 30.0,
        reconnect_on_send_error: bool = True,
        max_consecutive_failures: int = 5,
    ):
        self.enabled = enabled
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.policy = policy
        self.backoff_multiplier = backoff_multiplier
        self.linear_increment = linear_increment
        self.health_check_interval = health_check_interval
        self.reconnect_on_send_error = reconnect_on_send_error
        self.max_consecutive_failures = max_consecutive_failures

    @classmethod
    def from_dict(cls, data: dict) -> "ReconnectConfig":
        """Create from configuration dictionary."""
        policy_str = data.get("policy", "exponential")
        try:
            policy = RetryPolicy(policy_str)
        except ValueError:
            policy = RetryPolicy.EXPONENTIAL

        return cls(
            enabled=data.get("enabled", True),
            max_retries=data.get("max_retries", 10),
            initial_delay=data.get("initial_delay", 1.0),
            max_delay=data.get("max_delay", 60.0),
            policy=policy,
            backoff_multiplier=data.get("backoff_multiplier", 2.0),
            linear_increment=data.get("linear_increment", 2.0),
            health_check_interval=data.get("health_check_interval", 30.0),
            reconnect_on_send_error=data.get("reconnect_on_send_error", True),
            max_consecutive_failures=data.get("max_consecutive_failures", 5),
        )


class ReconnectStats:
    """Statistics for reconnection events."""

    def __init__(self):
        self.reconnect_attempts: int = 0
        self.reconnect_successes: int = 0
        self.reconnect_failures: int = 0
        self.total_downtime: float = 0.0
        self.last_reconnect_time: float = 0.0
        self.consecutive_failures: int = 0
        self._lock = threading.Lock()

    def record_attempt(self) -> None:
        with self._lock:
            self.reconnect_attempts += 1

    def record_success(self, downtime: float) -> None:
        with self._lock:
            self.reconnect_successes += 1
            self.total_downtime += downtime
            self.last_reconnect_time = time.time()
            self.consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self.reconnect_failures += 1
            self.consecutive_failures += 1

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "reconnect_attempts": self.reconnect_attempts,
                "reconnect_successes": self.reconnect_successes,
                "reconnect_failures": self.reconnect_failures,
                "total_downtime_seconds": round(self.total_downtime, 2),
                "last_reconnect_time": self.last_reconnect_time,
                "consecutive_failures": self.consecutive_failures,
            }


class ReconnectingTransport(TransportBackend):
    """Transport wrapper that adds automatic reconnection.

    Wraps an existing TransportBackend and intercepts failures to
    trigger automatic reconnection with configurable retry logic.
    """

    def __init__(
        self,
        inner: TransportBackend,
        config: Optional[ReconnectConfig] = None,
    ):
        """Initialize the reconnecting transport.

        Args:
            inner: The underlying transport backend to wrap.
            config: Reconnection configuration. Uses defaults if None.
        """
        # Initialize with the inner transport's config
        super().__init__(inner.transport_config)
        self._inner = inner
        self._config = config or ReconnectConfig()
        self._network_config: dict = {}
        self._reconnect_stats = ReconnectStats()
        self._lock = threading.Lock()
        self._consecutive_send_failures = 0

    def open(self, network_config: dict) -> None:
        """Open the transport with reconnect tracking.

        Args:
            network_config: Network configuration.
        """
        self._network_config = network_config
        self._inner.open(network_config)
        self._is_open = True

    def send(self, packet_bytes: bytes) -> int:
        """Send with automatic retry on failure.

        Args:
            packet_bytes: Packet data to send.

        Returns:
            Bytes sent.
        """
        try:
            result = self._inner.send(packet_bytes)
            self._consecutive_send_failures = 0
            return result
        except (TransportError, OSError) as e:
            self._consecutive_send_failures += 1
            logger.debug(
                "Send failed (%d consecutive): %s",
                self._consecutive_send_failures, e,
            )

            if (
                self._config.enabled
                and self._config.reconnect_on_send_error
                and self._consecutive_send_failures
                >= self._config.max_consecutive_failures
            ):
                logger.warning(
                    "Max consecutive send failures (%d) reached. "
                    "Attempting reconnect...",
                    self._consecutive_send_failures,
                )
                if self._reconnect():
                    self._consecutive_send_failures = 0
                    return self._inner.send(packet_bytes)

            raise

    def send_batch(self, packets: list[bytes]) -> int:
        """Send batch with automatic retry on failure.

        Args:
            packets: List of packet data.

        Returns:
            Number of packets sent.
        """
        try:
            result = self._inner.send_batch(packets)
            self._consecutive_send_failures = 0
            return result
        except (TransportError, OSError) as e:
            self._consecutive_send_failures += 1

            if (
                self._config.enabled
                and self._config.reconnect_on_send_error
                and self._consecutive_send_failures
                >= self._config.max_consecutive_failures
            ):
                if self._reconnect():
                    self._consecutive_send_failures = 0
                    return self._inner.send_batch(packets)

            raise

    def receive(self, timeout: float = 1.0) -> Optional[bytes]:
        """Receive with reconnect awareness."""
        return self._inner.receive(timeout)

    def close(self) -> None:
        """Close the underlying transport."""
        self._inner.close()
        self._is_open = False

    def _reconnect(self) -> bool:
        """Attempt to reconnect the underlying transport.

        Returns:
            True if reconnection succeeded, False otherwise.
        """
        with self._lock:
            disconnect_time = time.time()
            delay = self._config.initial_delay

            for attempt in range(1, self._config.max_retries + 1):
                self._reconnect_stats.record_attempt()
                logger.info(
                    "Reconnect attempt %d/%d...",
                    attempt, self._config.max_retries,
                )

                try:
                    # Close existing connection
                    try:
                        self._inner.close()
                    except Exception:
                        pass

                    # Re-open
                    self._inner.open(self._network_config)
                    self._is_open = True

                    downtime = time.time() - disconnect_time
                    self._reconnect_stats.record_success(downtime)
                    logger.info(
                        "Reconnect successful after %.1fs downtime "
                        "(attempt %d)",
                        downtime, attempt,
                    )
                    return True

                except Exception as e:
                    self._reconnect_stats.record_failure()
                    logger.warning(
                        "Reconnect attempt %d failed: %s. "
                        "Retrying in %.1fs...",
                        attempt, e, delay,
                    )
                    time.sleep(delay)

                    # Calculate next delay based on policy
                    delay = self._next_delay(delay, attempt)

            logger.error(
                "Reconnect failed after %d attempts",
                self._config.max_retries,
            )
            return False

    def _next_delay(self, current_delay: float, attempt: int) -> float:
        """Calculate the next retry delay based on policy.

        Args:
            current_delay: Current delay value.
            attempt: Current attempt number.

        Returns:
            Next delay in seconds.
        """
        if self._config.policy == RetryPolicy.FIXED:
            return self._config.initial_delay
        elif self._config.policy == RetryPolicy.LINEAR:
            delay = self._config.initial_delay + (
                attempt * self._config.linear_increment
            )
        else:  # EXPONENTIAL
            delay = current_delay * self._config.backoff_multiplier

        return min(delay, self._config.max_delay)

    @property
    def reconnect_stats(self) -> dict[str, Any]:
        """Get reconnection statistics."""
        return self._reconnect_stats.to_dict()

    def get_info(self) -> dict[str, Any]:
        """Get transport info including reconnect stats."""
        info = self._inner.get_info()
        info["reconnect"] = {
            "enabled": self._config.enabled,
            "policy": self._config.policy.value,
            "stats": self._reconnect_stats.to_dict(),
        }
        return info
