"""Async packet sniffer for capturing live traffic.

Used to capture packets on the wire for TCP flow tracking and
seq/ack number extraction for injection into live sessions.
"""

import threading
import time
from typing import Callable, Optional
from collections import deque

from ..utils.logging import get_logger

logger = get_logger("capture.sniffer")


class PacketSniffer:
    """Captures packets from a network interface using Scapy or AF_PACKET.

    Runs in a background thread and provides captured packets to
    registered callbacks and the flow tracker.
    """

    def __init__(
        self,
        interface: str,
        bpf_filter: str = "",
        max_buffer: int = 10000,
    ):
        """Initialize the packet sniffer.

        Args:
            interface: Network interface to capture on.
            bpf_filter: BPF filter expression (e.g., 'tcp port 3260').
            max_buffer: Maximum number of packets to buffer.
        """
        self.interface = interface
        self.bpf_filter = bpf_filter
        self.max_buffer = max_buffer

        self._buffer: deque = deque(maxlen=max_buffer)
        self._callbacks: list[Callable] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._packet_count = 0

    def add_callback(self, callback: Callable) -> None:
        """Register a callback for captured packets.

        The callback will be called with each captured Scapy packet.

        Args:
            callback: Function taking a Scapy Packet argument.
        """
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start capturing packets in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Sniffer already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="packet-sniffer",
        )
        self._thread.start()
        logger.info(
            "Sniffer started on %s (filter: %s)",
            self.interface, self.bpf_filter or "none",
        )

    def stop(self) -> None:
        """Stop the capture thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("Sniffer stopped (%d packets captured)", self._packet_count)

    def _capture_loop(self) -> None:
        """Main capture loop running in background thread."""
        try:
            from scapy.all import sniff

            def packet_handler(pkt):
                """Process each captured packet."""
                self._packet_count += 1
                self._buffer.append(pkt)

                # Notify callbacks
                for cb in self._callbacks:
                    try:
                        cb(pkt)
                    except Exception as e:
                        logger.debug("Callback error: %s", e)

            # Scapy sniff with stop condition
            sniff(
                iface=self.interface,
                filter=self.bpf_filter,
                prn=packet_handler,
                store=False,
                stop_filter=lambda _: self._stop_event.is_set(),
            )

        except ImportError:
            logger.error("Scapy not available for packet capture")
        except Exception as e:
            logger.error("Sniffer error: %s", e)

    def get_recent_packets(self, count: int = 10) -> list:
        """Get the most recent captured packets.

        Args:
            count: Number of recent packets to return.

        Returns:
            List of recent Scapy packets.
        """
        return list(self._buffer)[-count:]

    @property
    def packet_count(self) -> int:
        """Total number of captured packets."""
        return self._packet_count

    @property
    def is_running(self) -> bool:
        """Check if sniffer is currently running."""
        return self._thread is not None and self._thread.is_alive()
