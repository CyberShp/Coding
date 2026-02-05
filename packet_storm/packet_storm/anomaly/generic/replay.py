"""Replay attack anomaly - captures and replays historical packets."""

import time
import random
from collections import deque
from typing import Any

from scapy.packet import Packet

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.replay")


@register_anomaly
class ReplayAnomaly(BaseAnomaly):
    """Replays previously captured/sent packets to simulate replay attacks.

    Maintains a history of packets and replays them with optional
    modifications (timestamp shift, sequence number reuse, etc.).

    Modes:
    - 'exact': Replay the packet unchanged (exact duplicate)
    - 'delayed': Replay with a time offset (simulating delayed replay)
    - 'modified': Replay with minor field modifications
    - 'burst': Replay the same packet multiple times rapidly
    """

    NAME = "replay"
    DESCRIPTION = "Replay historical packets to simulate replay attacks"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._mode = config.get("mode", "exact")
        self._history_size = config.get("history_size", 100)
        self._burst_count = config.get("burst_count", 10)
        self._history: deque[bytes] = deque(maxlen=self._history_size)
        self._replay_from = config.get("replay_from", "random")  # 'random', 'oldest', 'newest'

    def apply(self, packet: Packet) -> Packet:
        """Store the packet and return a replayed historical packet.

        The first few calls will return the input packet as-is (no history).
        Once history is populated, replayed packets are returned.
        """
        self._applied_count += 1

        # Store current packet in history
        current_bytes = bytes(packet)
        self._history.append(current_bytes)

        # If not enough history, return the current packet (mild duplication)
        if len(self._history) < 2:
            return self._copy_packet(packet)

        # Select a historical packet to replay
        if self._replay_from == "oldest":
            replay_bytes = self._history[0]
        elif self._replay_from == "newest":
            replay_bytes = self._history[-2]  # Not the one we just added
        else:  # random
            idx = random.randint(0, len(self._history) - 2)
            replay_bytes = self._history[idx]

        # Apply replay mode modifications
        if self._mode == "modified":
            replay_bytes = self._minor_modification(replay_bytes)
        elif self._mode == "burst":
            # In burst mode, we return the same packet (caller handles burst count)
            pass

        # Reconstruct as Scapy packet
        from scapy.layers.l2 import Ether
        try:
            replayed = Ether(replay_bytes)
        except Exception:
            from scapy.packet import Raw
            replayed = Raw(load=replay_bytes)

        logger.debug(
            "Replayed packet from history (mode=%s, history_size=%d)",
            self._mode, len(self._history),
        )

        return replayed

    @staticmethod
    def _minor_modification(data: bytes) -> bytes:
        """Apply minor modifications to replayed data.

        Simulates an attacker who replays with slight changes.
        """
        data = bytearray(data)
        if len(data) > 20:
            # Flip a random byte in the payload area (past headers)
            pos = random.randint(14, len(data) - 1)
            data[pos] ^= random.randint(1, 255)
        return bytes(data)

    def get_history_size(self) -> int:
        """Get current number of packets in replay history."""
        return len(self._history)

    def clear_history(self) -> None:
        """Clear the replay history."""
        self._history.clear()
