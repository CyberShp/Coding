"""IP fragmentation attack anomaly - creates malicious fragment patterns."""

import random
from typing import Any

from scapy.packet import Packet, Raw
from scapy.layers.l2 import Ether
from scapy.layers.inet import IP, TCP, UDP

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.fragmentation")


@register_anomaly
class FragmentationAnomaly(BaseAnomaly):
    """Creates IP fragmentation-based attacks.

    Modes:
    - 'tiny': Create fragments smaller than minimum (< 68 bytes)
    - 'overlapping': Create overlapping fragment offsets
    - 'incomplete': Send initial fragment without final fragment
    - 'reversed': Send fragments in reverse order
    - 'duplicate': Send duplicate fragments with different data
    - 'excessive': Create an excessive number of fragments
    - 'mixed': Randomly choose an attack pattern
    """

    NAME = "fragmentation"
    DESCRIPTION = "IP fragmentation attacks (tiny, overlapping, incomplete, etc.)"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._mode = config.get("mode", "mixed")
        self._fragment_size = config.get("fragment_size", 8)  # Minimum 8 bytes
        self._num_fragments = config.get("num_fragments", 0)  # 0 = auto

    def apply(self, packet: Packet) -> Packet:
        """Apply fragmentation attack to the packet.

        Note: For modes that generate multiple fragments, this returns
        the first fragment. The engine should call get_fragments() for
        the complete set.
        """
        pkt = self._copy_packet(packet)
        self._applied_count += 1

        if self._mode == "mixed":
            mode = random.choice([
                "tiny", "overlapping", "incomplete",
                "reversed", "duplicate", "excessive",
            ])
        else:
            mode = self._mode

        if not pkt.haslayer(IP):
            logger.debug("No IP layer found, cannot apply fragmentation")
            return pkt

        # Get the payload after IP header
        ip_layer = pkt[IP]
        ip_payload = bytes(ip_layer.payload)

        if len(ip_payload) < 16:
            # Pad payload for meaningful fragmentation
            ip_payload += b"\x00" * (64 - len(ip_payload))

        if mode == "tiny":
            return self._tiny_fragment(pkt, ip_layer, ip_payload)
        elif mode == "overlapping":
            return self._overlapping_fragment(pkt, ip_layer, ip_payload)
        elif mode == "incomplete":
            return self._incomplete_fragment(pkt, ip_layer, ip_payload)
        elif mode == "excessive":
            return self._excessive_fragment(pkt, ip_layer, ip_payload)
        else:
            return self._tiny_fragment(pkt, ip_layer, ip_payload)

    def _tiny_fragment(self, pkt: Packet, ip: IP, payload: bytes) -> Packet:
        """Create a tiny fragment (< minimum fragment size)."""
        # First fragment: MF flag set, tiny payload
        frag_size = max(8, self._fragment_size)
        tiny_payload = payload[:frag_size]

        frag = pkt.copy()
        frag_ip = frag[IP]
        frag_ip.flags = "MF"  # More Fragments
        frag_ip.frag = 0
        # Remove original payload and add tiny one
        frag_ip.remove_payload()
        frag_ip = frag_ip / Raw(load=tiny_payload)

        # Recalculate length
        del frag_ip.len
        del frag_ip.chksum

        logger.debug("Created tiny fragment: %d bytes", frag_size)
        return Ether(bytes(frag))

    def _overlapping_fragment(self, pkt: Packet, ip: IP, payload: bytes) -> Packet:
        """Create an overlapping fragment that conflicts with the first."""
        frag_size = 32

        # Create a fragment with offset that overlaps the beginning
        frag = pkt.copy()
        frag_ip = frag[IP]
        frag_ip.flags = "MF"
        # Offset overlaps with first fragment (offset is in 8-byte units)
        frag_ip.frag = random.randint(0, 2)
        frag_ip.remove_payload()
        # Different data than what the first fragment would have
        evil_payload = bytes(random.randint(0, 255) for _ in range(frag_size))
        frag_ip = frag_ip / Raw(load=evil_payload)

        del frag_ip.len
        del frag_ip.chksum

        logger.debug("Created overlapping fragment at offset %d", frag_ip.frag)
        return Ether(bytes(frag))

    def _incomplete_fragment(self, pkt: Packet, ip: IP, payload: bytes) -> Packet:
        """Create a first fragment with MF=1 but never send the final fragment."""
        frag = pkt.copy()
        frag_ip = frag[IP]
        frag_ip.flags = "MF"  # More Fragments (but we never send them)
        frag_ip.frag = 0
        # Only include partial payload
        partial = payload[:random.randint(8, min(64, len(payload)))]
        frag_ip.remove_payload()
        frag_ip = frag_ip / Raw(load=partial)

        del frag_ip.len
        del frag_ip.chksum

        logger.debug("Created incomplete fragment (no final fragment will follow)")
        return Ether(bytes(frag))

    def _excessive_fragment(self, pkt: Packet, ip: IP, payload: bytes) -> Packet:
        """Create a fragment indicating an impossibly large reassembled packet."""
        frag = pkt.copy()
        frag_ip = frag[IP]
        frag_ip.flags = "MF"
        # Set fragment offset to very high value (in 8-byte units)
        # Max offset = 8191 (13 bits), meaning offset = 8191 * 8 = 65528 bytes
        frag_ip.frag = 8191
        frag_ip.remove_payload()
        frag_ip = frag_ip / Raw(load=payload[:64])

        del frag_ip.len
        del frag_ip.chksum

        logger.debug("Created excessive fragment (offset=%d)", frag_ip.frag)
        return Ether(bytes(frag))
