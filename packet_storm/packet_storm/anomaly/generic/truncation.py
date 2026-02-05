"""Packet truncation anomaly - truncates packets to invalid lengths."""

import random
from typing import Any

from scapy.packet import Packet, Raw

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.truncation")


@register_anomaly
class TruncationAnomaly(BaseAnomaly):
    """Truncates packets to lengths shorter than protocol minimum.

    Modes:
    - 'fixed': Truncate to a specific byte length
    - 'random': Truncate to a random length between min and max
    - 'protocol_min': Truncate to just below the protocol's minimum header size
    - 'half': Truncate to exactly half the original packet
    """

    NAME = "truncation"
    DESCRIPTION = "Truncate packets to invalid/short lengths"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    # Minimum header sizes per protocol layer
    MIN_SIZES = {
        "ethernet": 14,
        "ip": 20,
        "ipv6": 40,
        "tcp": 20,
        "udp": 8,
        "iscsi": 48,  # BHS
    }

    def __init__(self, config: dict):
        super().__init__(config)
        self._mode = config.get("mode", "random")
        self._truncate_to = config.get("truncate_to", 0)
        self._min_length = config.get("min_length", 1)
        self._max_length = config.get("max_length", 0)  # 0 = auto

    def apply(self, packet: Packet) -> Packet:
        """Truncate the packet to an invalid length."""
        self._applied_count += 1

        # Serialize the packet to raw bytes
        raw_bytes = bytes(packet)
        original_len = len(raw_bytes)

        if original_len <= 1:
            return packet

        # Determine truncation length
        if self._mode == "fixed":
            target_len = max(1, self._truncate_to)
        elif self._mode == "half":
            target_len = original_len // 2
        elif self._mode == "protocol_min":
            # Truncate to just below the innermost protocol's minimum
            target_len = self._below_protocol_min(packet, original_len)
        else:  # random
            max_len = self._max_length if self._max_length > 0 else original_len - 1
            target_len = random.randint(self._min_length, max(self._min_length, max_len))

        # Apply truncation
        target_len = min(target_len, original_len - 1)
        target_len = max(1, target_len)
        truncated = raw_bytes[:target_len]

        logger.debug(
            "Truncated packet: %d -> %d bytes (mode=%s)",
            original_len, len(truncated), self._mode,
        )

        # Return as raw Ethernet frame
        from scapy.layers.l2 import Ether
        try:
            return Ether(truncated)
        except Exception:
            return Raw(load=truncated)

    def _below_protocol_min(self, packet: Packet, total_len: int) -> int:
        """Calculate a length just below the innermost protocol's minimum."""
        # Walk the layers to find the cumulative offset of the innermost protocol
        offset = 0
        last_min = 14  # Ethernet minimum

        layer = packet
        while layer:
            layer_name = layer.name.lower()
            for proto_name, min_size in self.MIN_SIZES.items():
                if proto_name in layer_name:
                    last_min = offset + min_size
                    break
            if hasattr(layer, 'payload') and layer.payload:
                offset += len(bytes(layer)) - len(bytes(layer.payload))
                layer = layer.payload
            else:
                break

        # Truncate to 1-5 bytes below the minimum
        return max(1, last_min - random.randint(1, 5))
