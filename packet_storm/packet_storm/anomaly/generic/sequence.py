"""TCP sequence number manipulation anomaly."""

import random
from typing import Any

from scapy.packet import Packet
from scapy.layers.inet import IP, TCP

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.sequence")


@register_anomaly
class SequenceAnomaly(BaseAnomaly):
    """Manipulates TCP sequence and acknowledgment numbers.

    Tests how the receiver handles:
    - Out-of-order segments
    - Duplicate ACKs
    - Window size manipulation
    - Invalid sequence number combinations

    Modes:
    - 'out_of_order': Set sequence number far ahead or behind
    - 'duplicate_ack': Set ack to already-acknowledged value
    - 'window_manipulation': Set window size to extreme values
    - 'seq_wrap': Test sequence number wraparound
    - 'zero_window': Set window to 0 (flow control attack)
    - 'mixed': Random combination
    """

    NAME = "sequence"
    DESCRIPTION = "Manipulate TCP sequence/ack numbers and window sizes"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._mode = config.get("mode", "mixed")

    def apply(self, packet: Packet) -> Packet:
        """Apply sequence number manipulation."""
        pkt = self._copy_packet(packet)
        self._applied_count += 1

        if not pkt.haslayer(TCP):
            return pkt

        tcp = pkt[TCP]

        if self._mode == "mixed":
            mode = random.choice([
                "out_of_order", "duplicate_ack", "window_manipulation",
                "seq_wrap", "zero_window",
            ])
        else:
            mode = self._mode

        if mode == "out_of_order":
            self._out_of_order(tcp)
        elif mode == "duplicate_ack":
            self._duplicate_ack(tcp)
        elif mode == "window_manipulation":
            self._window_manipulation(tcp)
        elif mode == "seq_wrap":
            self._seq_wrap(tcp)
        elif mode == "zero_window":
            self._zero_window(tcp)

        return pkt

    def _out_of_order(self, tcp: TCP) -> None:
        """Set sequence number far from expected."""
        original_seq = tcp.seq
        offset = random.choice([
            random.randint(100000, 1000000),     # Far ahead
            -random.randint(100000, 1000000),    # Far behind
            random.randint(1, 100),               # Slightly ahead
        ])
        tcp.seq = (original_seq + offset) & 0xFFFFFFFF
        logger.debug("Out-of-order seq: %d -> %d", original_seq, tcp.seq)

    def _duplicate_ack(self, tcp: TCP) -> None:
        """Set ack to an already-acknowledged value (rewinding)."""
        original_ack = tcp.ack
        # Rewind ack by a random amount
        rewind = random.randint(1, min(original_ack, 100000)) if original_ack > 0 else 1
        tcp.ack = (original_ack - rewind) & 0xFFFFFFFF
        # Set ACK flag
        tcp.flags = tcp.flags | 0x10  # ACK flag
        logger.debug("Duplicate ACK: %d -> %d", original_ack, tcp.ack)

    def _window_manipulation(self, tcp: TCP) -> None:
        """Set window size to extreme values."""
        tcp.window = random.choice([
            0,          # Zero window (should trigger probe)
            1,          # Tiny window
            65535,      # Maximum window
            random.randint(0, 65535),  # Random
        ])
        logger.debug("Window manipulation: set to %d", tcp.window)

    def _seq_wrap(self, tcp: TCP) -> None:
        """Test sequence number wraparound behavior."""
        tcp.seq = random.choice([
            0xFFFFFFFF,           # Max value (about to wrap)
            0xFFFFFFF0,           # Near wrap
            0,                     # Just wrapped
            0x80000000,           # Middle of sequence space
        ])
        logger.debug("Seq wrap test: set to 0x%08x", tcp.seq)

    def _zero_window(self, tcp: TCP) -> None:
        """Zero window attack - tell sender to stop sending."""
        tcp.window = 0
        tcp.flags = tcp.flags | 0x10  # ACK flag
        logger.debug("Zero window attack applied")
