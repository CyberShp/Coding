"""TCP flow tracker for extracting seq/ack numbers from live sessions.

Monitors TCP traffic to maintain a table of active flows with their
current sequence and acknowledgment numbers, enabling injection of
anomalous packets into existing TCP sessions.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger("capture.flow_tracker")


@dataclass
class TCPFlow:
    """Represents a tracked TCP connection flow."""

    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int

    # Current sequence/ack state
    client_seq: int = 0      # Next expected seq from client (initiator)
    client_ack: int = 0      # Last ack sent by client
    server_seq: int = 0      # Next expected seq from server (target)
    server_ack: int = 0      # Last ack sent by server

    # Statistics
    packets_seen: int = 0
    bytes_transferred: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0

    # State
    state: str = "unknown"   # SYN_SENT, ESTABLISHED, FIN_WAIT, etc.

    @property
    def flow_key(self) -> tuple:
        """Canonical flow key (sorted by IP:port to combine both directions)."""
        a = (self.src_ip, self.src_port)
        b = (self.dst_ip, self.dst_port)
        return tuple(sorted([a, b]))

    @property
    def age(self) -> float:
        """Age of this flow in seconds."""
        return time.time() - self.first_seen if self.first_seen > 0 else 0

    def to_dict(self) -> dict:
        """Serialize flow to dictionary."""
        return {
            "src": f"{self.src_ip}:{self.src_port}",
            "dst": f"{self.dst_ip}:{self.dst_port}",
            "client_seq": self.client_seq,
            "client_ack": self.client_ack,
            "server_seq": self.server_seq,
            "server_ack": self.server_ack,
            "packets": self.packets_seen,
            "bytes": self.bytes_transferred,
            "state": self.state,
            "age_seconds": round(self.age, 2),
        }


class FlowTracker:
    """Tracks TCP flows and their sequence/acknowledgment numbers.

    Maintains a flow table updated by packet capture, enabling
    injection of packets with correct seq/ack values into live sessions.
    """

    def __init__(self, max_flows: int = 10000, flow_timeout: float = 300.0):
        """Initialize the flow tracker.

        Args:
            max_flows: Maximum number of tracked flows.
            flow_timeout: Seconds before an idle flow is expired.
        """
        self.max_flows = max_flows
        self.flow_timeout = flow_timeout
        self._flows: dict[tuple, TCPFlow] = {}
        self._lock = threading.Lock()

    def process_packet(self, packet) -> None:
        """Process a captured packet and update flow state.

        This method is designed to be used as a callback for PacketSniffer.

        Args:
            packet: Scapy packet to process.
        """
        try:
            from scapy.layers.inet import IP, TCP

            if not packet.haslayer(TCP) or not packet.haslayer(IP):
                return

            ip = packet[IP]
            tcp = packet[TCP]

            src_ip = ip.src
            dst_ip = ip.dst
            src_port = tcp.sport
            dst_port = tcp.dport
            seq = tcp.seq
            ack = tcp.ack
            flags = tcp.flags
            payload_len = len(bytes(tcp.payload)) if tcp.payload else 0

            # Create canonical flow key
            a = (src_ip, src_port)
            b = (dst_ip, dst_port)
            flow_key = tuple(sorted([a, b]))

            with self._lock:
                now = time.time()

                if flow_key not in self._flows:
                    # New flow
                    if len(self._flows) >= self.max_flows:
                        self._expire_oldest()

                    flow = TCPFlow(
                        src_ip=src_ip,
                        dst_ip=dst_ip,
                        src_port=src_port,
                        dst_port=dst_port,
                        first_seen=now,
                        last_seen=now,
                    )
                    self._flows[flow_key] = flow
                else:
                    flow = self._flows[flow_key]

                flow.last_seen = now
                flow.packets_seen += 1
                flow.bytes_transferred += payload_len

                # Determine direction and update seq/ack
                is_client = (src_ip == flow.src_ip and src_port == flow.src_port)

                if is_client:
                    flow.client_seq = seq + max(payload_len, 1)
                    flow.client_ack = ack
                else:
                    flow.server_seq = seq + max(payload_len, 1)
                    flow.server_ack = ack

                # Update state based on TCP flags
                flags_str = str(flags)
                if "S" in flags_str and "A" not in flags_str:
                    flow.state = "SYN_SENT"
                elif "S" in flags_str and "A" in flags_str:
                    flow.state = "SYN_RECEIVED"
                elif "F" in flags_str:
                    flow.state = "FIN_WAIT"
                elif "R" in flags_str:
                    flow.state = "RESET"
                elif "A" in flags_str and flow.state in ("SYN_SENT", "SYN_RECEIVED"):
                    flow.state = "ESTABLISHED"
                elif "A" in flags_str and flow.state == "unknown":
                    flow.state = "ESTABLISHED"

        except Exception as e:
            logger.debug("Flow tracking error: %s", e)

    def get_flow(
        self,
        src_ip: str,
        dst_ip: str,
        src_port: int,
        dst_port: int,
    ) -> Optional[TCPFlow]:
        """Look up a specific flow.

        Args:
            src_ip: Source IP.
            dst_ip: Destination IP.
            src_port: Source port.
            dst_port: Destination port.

        Returns:
            TCPFlow if found, None otherwise.
        """
        a = (src_ip, src_port)
        b = (dst_ip, dst_port)
        flow_key = tuple(sorted([a, b]))

        with self._lock:
            return self._flows.get(flow_key)

    def get_injection_params(
        self,
        target_ip: str,
        target_port: int,
    ) -> Optional[dict]:
        """Get TCP seq/ack values for injecting into a live session.

        Finds any flow involving the target IP/port and returns
        the current sequence numbers needed for injection.

        Args:
            target_ip: Target IP address.
            target_port: Target port number.

        Returns:
            Dictionary with 'seq', 'ack', 'src_ip', 'src_port' for injection,
            or None if no matching flow found.
        """
        with self._lock:
            for flow in self._flows.values():
                if flow.state != "ESTABLISHED":
                    continue

                # Check if target is the server
                if flow.dst_ip == target_ip and flow.dst_port == target_port:
                    return {
                        "seq": flow.client_seq,
                        "ack": flow.server_seq,
                        "src_ip": flow.src_ip,
                        "src_port": flow.src_port,
                        "dst_ip": flow.dst_ip,
                        "dst_port": flow.dst_port,
                    }
                # Check if target is the client (reverse direction)
                if flow.src_ip == target_ip and flow.src_port == target_port:
                    return {
                        "seq": flow.server_seq,
                        "ack": flow.client_seq,
                        "src_ip": flow.dst_ip,
                        "src_port": flow.dst_port,
                        "dst_ip": flow.src_ip,
                        "dst_port": flow.src_port,
                    }

        return None

    def list_flows(self, state: Optional[str] = None) -> list[dict]:
        """List all tracked flows.

        Args:
            state: Filter by state (e.g., 'ESTABLISHED').

        Returns:
            List of flow dictionaries.
        """
        with self._lock:
            flows = list(self._flows.values())

        if state:
            flows = [f for f in flows if f.state == state]

        return [f.to_dict() for f in sorted(flows, key=lambda f: f.last_seen, reverse=True)]

    def _expire_oldest(self) -> None:
        """Remove the oldest flow to make room for new ones."""
        if not self._flows:
            return

        now = time.time()
        # First try to expire timed-out flows
        expired_keys = [
            k for k, v in self._flows.items()
            if now - v.last_seen > self.flow_timeout
        ]
        for key in expired_keys:
            del self._flows[key]

        # If still too many, remove oldest
        if len(self._flows) >= self.max_flows:
            oldest_key = min(self._flows.keys(), key=lambda k: self._flows[k].last_seen)
            del self._flows[oldest_key]

    def clear(self) -> None:
        """Clear all tracked flows."""
        with self._lock:
            self._flows.clear()

    @property
    def flow_count(self) -> int:
        """Number of currently tracked flows."""
        return len(self._flows)
