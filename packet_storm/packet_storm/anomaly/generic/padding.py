"""Packet padding anomaly - appends extra data beyond protocol maximum."""

import random
from typing import Any

from scapy.packet import Packet, Raw

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.padding")


@register_anomaly
class PaddingAnomaly(BaseAnomaly):
    """Adds extra padding/data to packets beyond protocol-allowed length.

    Modes:
    - 'random': Append random bytes
    - 'zeros': Append null bytes
    - 'pattern': Append a repeating pattern
    - 'overflow': Append data designed to trigger buffer overflows
    """

    NAME = "padding"
    DESCRIPTION = "Pad packets with extra data beyond protocol maximum length"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._mode = config.get("mode", "random")
        self._pad_size = config.get("pad_size", 0)  # 0 = random 64-4096
        self._pattern = config.get("pattern", "AAAA").encode()

    def apply(self, packet: Packet) -> Packet:
        """Append extra data to the packet."""
        pkt = self._copy_packet(packet)
        self._applied_count += 1

        pad_size = self._pad_size
        if pad_size <= 0:
            pad_size = random.randint(64, 4096)

        if self._mode == "zeros":
            padding = b"\x00" * pad_size
        elif self._mode == "pattern":
            repeats = (pad_size // len(self._pattern)) + 1
            padding = (self._pattern * repeats)[:pad_size]
        elif self._mode == "overflow":
            # Common overflow patterns
            patterns = [
                b"\x41" * pad_size,                          # 'AAAA...'
                b"\x90" * (pad_size - 8) + b"\xCC" * 8,     # NOP sled + INT3
                bytes(range(256)) * (pad_size // 256 + 1),   # Cyclic pattern
                b"\xFF" * pad_size,                          # All ones
            ]
            padding = random.choice(patterns)[:pad_size]
        else:  # random
            padding = bytes(random.randint(0, 255) for _ in range(pad_size))

        logger.debug(
            "Added %d bytes padding (mode=%s) to %d byte packet",
            pad_size, self._mode, len(bytes(pkt)),
        )

        # Append padding as Raw payload to the last layer
        return pkt / Raw(load=padding)
