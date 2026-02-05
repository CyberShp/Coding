"""Main packet sending engine - orchestrates the full send pipeline.

The engine coordinates between:
- ConfigManager: provides configuration
- Protocol builders: construct base packets
- Anomaly generators: apply anomalies to packets
- Transport backends: send packets out the wire
- Session: tracks state and statistics
"""

import time
import threading
from typing import Any, Optional

from ..utils.logging import get_logger
from .config import ConfigManager
from .session import Session, SessionState
from .registry import protocol_registry, anomaly_registry, transport_registry

logger = get_logger("engine")


class PacketStormEngine:
    """Core engine that orchestrates packet construction, anomaly injection, and sending.

    The engine runs in a dedicated thread and supports start/stop/pause/resume
    and single-step operations.
    """

    def __init__(self, config_manager: ConfigManager):
        """Initialize the engine.

        Args:
            config_manager: Configuration manager instance.
        """
        self.config_manager = config_manager
        self.session: Optional[Session] = None
        self._protocol_builder: Any = None
        self._anomaly_generators: list[Any] = []
        self._transport: Any = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Start unpaused
        self._step_event = threading.Event()
        self._step_mode = False

    def setup(self) -> None:
        """Set up the engine: create session, initialize components.

        Raises:
            RuntimeError: If setup fails.
        """
        config = self.config_manager.config

        # Create new session
        self.session = Session(config)
        self.session.transition(SessionState.CONFIGURING)

        try:
            # Initialize protocol builder
            proto_type = self.config_manager.get_protocol_type()
            builder_cls = protocol_registry.get(proto_type)
            if builder_cls is None:
                raise RuntimeError(
                    f"No protocol builder registered for '{proto_type}'. "
                    f"Available: {protocol_registry.list_names()}"
                )
            self._protocol_builder = builder_cls(
                network_config=self.config_manager.get_network_config(),
                protocol_config=self.config_manager.get_protocol_config(),
            )
            logger.info("Protocol builder initialized: %s", proto_type)

            # Initialize anomaly generators
            self._anomaly_generators = []
            for anomaly_cfg in self.config_manager.get_anomalies_config():
                if not anomaly_cfg.get("enabled", True):
                    continue
                anom_type = anomaly_cfg["type"]
                anom_cls = anomaly_registry.get(anom_type)
                if anom_cls is None:
                    logger.warning("Unknown anomaly type: %s, skipping", anom_type)
                    continue
                anom = anom_cls(anomaly_cfg)
                self._anomaly_generators.append(anom)
                logger.info("Anomaly generator loaded: %s", anom_type)

            # Initialize transport backend
            backend_name = self.config_manager.get_transport_config().get("backend", "scapy")
            transport_cls = transport_registry.get(backend_name)
            if transport_cls is None:
                raise RuntimeError(
                    f"No transport backend registered for '{backend_name}'. "
                    f"Available: {transport_registry.list_names()}"
                )
            self._transport = transport_cls(self.config_manager.get_transport_config())
            self._transport.open(self.config_manager.get_network_config())
            logger.info("Transport backend initialized: %s", backend_name)

            self.session.transition(SessionState.READY)
            logger.info("Engine setup complete")

        except Exception as e:
            if self.session:
                self.session.transition(SessionState.ERROR)
            raise RuntimeError(f"Engine setup failed: {e}") from e

    def start(self) -> None:
        """Start the packet sending loop in a background thread."""
        if self.session is None or self.session.state != SessionState.READY:
            raise RuntimeError("Engine not ready. Call setup() first.")

        self._stop_event.clear()
        self._pause_event.set()
        self._step_mode = False

        self.session.transition(SessionState.RUNNING)

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="storm-engine")
        self._thread.start()
        logger.info("Engine started")

    def stop(self) -> None:
        """Stop the packet sending loop."""
        if self.session and self.session.is_active:
            self._stop_event.set()
            self._pause_event.set()  # Unblock if paused
            self._step_event.set()  # Unblock if in step mode

            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5.0)

            if self.session.state != SessionState.ERROR:
                self.session.transition(SessionState.STOPPING)
                self.session.transition(SessionState.COMPLETED)

            self._cleanup()
            logger.info("Engine stopped")

    def pause(self) -> None:
        """Pause the packet sending loop."""
        if self.session and self.session.state == SessionState.RUNNING:
            self._pause_event.clear()
            self.session.transition(SessionState.PAUSED)
            logger.info("Engine paused")

    def resume(self) -> None:
        """Resume the packet sending loop."""
        if self.session and self.session.state == SessionState.PAUSED:
            self._step_mode = False
            self._pause_event.set()
            self.session.transition(SessionState.RUNNING)
            logger.info("Engine resumed")

    def step(self) -> None:
        """Send a single packet (step mode)."""
        if self.session is None:
            raise RuntimeError("Engine not ready. Call setup() first.")

        if self.session.state == SessionState.READY:
            # Start in step mode
            self._stop_event.clear()
            self._pause_event.set()
            self._step_mode = True
            self.session.transition(SessionState.RUNNING)
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name="storm-engine-step"
            )
            self._thread.start()
        elif self.session.state in (SessionState.RUNNING, SessionState.PAUSED):
            self._step_mode = True
            self._step_event.set()
            self._pause_event.set()

    def _run_loop(self) -> None:
        """Main send loop running in a background thread."""
        exec_config = self.config_manager.get_execution_config()
        interval_s = exec_config.get("interval_ms", 100) / 1000.0
        repeat = exec_config.get("repeat", 1)
        duration = exec_config.get("duration_seconds", 0)
        start_delay = exec_config.get("start_delay_seconds", 0)

        if start_delay > 0:
            logger.info("Waiting %s seconds before starting...", start_delay)
            if self._stop_event.wait(start_delay):
                return

        iteration = 0
        start_time = time.time()

        try:
            while not self._stop_event.is_set():
                # Check duration limit
                if duration > 0 and (time.time() - start_time) >= duration:
                    logger.info("Duration limit reached (%s seconds)", duration)
                    break

                # Check repeat limit
                if repeat > 0 and iteration >= repeat:
                    logger.info("Repeat limit reached (%s iterations)", repeat)
                    break

                # Handle pause
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                # Handle step mode
                if self._step_mode:
                    self._step_event.wait()
                    self._step_event.clear()
                    if self._stop_event.is_set():
                        break

                # Generate and send packets for each anomaly
                for anomaly_gen in self._anomaly_generators:
                    if self._stop_event.is_set():
                        break

                    count = anomaly_gen.config.get("count", 1)
                    for _ in range(count):
                        if self._stop_event.is_set():
                            break
                        self._send_one(anomaly_gen)

                        if interval_s > 0:
                            time.sleep(interval_s)

                iteration += 1

                # In step mode, pause after one iteration
                if self._step_mode:
                    self._step_mode = False

        except Exception as e:
            logger.error("Engine error: %s", e, exc_info=True)
            if self.session:
                self.session.stats.errors.append(str(e))
                self.session.transition(SessionState.ERROR)
        else:
            if self.session and self.session.state == SessionState.RUNNING:
                self.session.transition(SessionState.STOPPING)
                self.session.transition(SessionState.COMPLETED)
        finally:
            self._cleanup()

    def _send_one(self, anomaly_gen: Any) -> None:
        """Construct one packet with anomaly and send it.

        Args:
            anomaly_gen: The anomaly generator to apply.
        """
        try:
            # Build base packet
            base_packet = self._protocol_builder.build_packet()

            # Apply anomaly
            anomalous_packet = anomaly_gen.apply(base_packet)
            if self.session:
                self.session.record_anomaly()

            # Serialize to bytes
            packet_bytes = bytes(anomalous_packet)

            # Send
            self._transport.send(packet_bytes)

            if self.session:
                self.session.record_send(len(packet_bytes))

        except Exception as e:
            logger.debug("Send failed: %s", e)
            if self.session:
                self.session.record_failure(str(e))

    def _cleanup(self) -> None:
        """Clean up transport resources."""
        if self._transport:
            try:
                self._transport.close()
            except Exception as e:
                logger.warning("Transport cleanup error: %s", e)

    def get_status(self) -> dict:
        """Get current engine status."""
        return {
            "session": self.session.to_dict() if self.session else None,
            "protocol": self.config_manager.get_protocol_type(),
            "transport": self.config_manager.get_transport_config().get("backend", "unknown"),
            "anomaly_count": len(self._anomaly_generators),
        }
