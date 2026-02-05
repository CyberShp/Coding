"""Malformed packet anomaly - creates structurally invalid packets."""

import random
from typing import Any

from scapy.packet import Packet, Raw
from scapy.layers.inet import IP, TCP, UDP

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.malformed")


@register_anomaly
class MalformedAnomaly(BaseAnomaly):
    """Creates structurally malformed packets that violate protocol format rules.

    Modes:
    - 'reserved_bits': Set reserved/must-be-zero bits to non-zero values
    - 'version_invalid': Set protocol version fields to invalid values
    - 'header_length': Set header length fields to wrong values
    - 'field_overflow': Set fields to values exceeding their valid range
    - 'mixed': Apply multiple malformations randomly
    """

    NAME = "malformed"
    DESCRIPTION = "Create structurally malformed packets (reserved bits, invalid versions, etc.)"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._mode = config.get("mode", "mixed")

    def apply(self, packet: Packet) -> Packet:
        """Apply malformation to the packet."""
        pkt = self._copy_packet(packet)
        self._applied_count += 1

        if self._mode == "mixed":
            mode = random.choice([
                "reserved_bits", "version_invalid",
                "header_length", "field_overflow",
            ])
        else:
            mode = self._mode

        if mode == "reserved_bits":
            self._set_reserved_bits(pkt)
        elif mode == "version_invalid":
            self._invalid_version(pkt)
        elif mode == "header_length":
            self._wrong_header_length(pkt)
        elif mode == "field_overflow":
            self._field_overflow(pkt)

        return pkt

    def _set_reserved_bits(self, packet: Packet) -> None:
        """Set reserved/must-be-zero fields to non-zero values."""
        layer = packet
        while layer:
            for field in layer.fields_desc:
                name = field.name.lower()
                if "reserved" in name or "padding" in name or "mbz" in name:
                    if isinstance(getattr(layer, field.name, None), int):
                        setattr(layer, field.name, random.randint(1, 0xFF))
                        logger.debug("Set reserved field %s.%s to non-zero", layer.name, field.name)
                    elif isinstance(getattr(layer, field.name, None), bytes):
                        val = getattr(layer, field.name)
                        setattr(layer, field.name, bytes(random.randint(1, 255) for _ in range(len(val))))
            layer = layer.payload if hasattr(layer, 'payload') and layer.payload else None

    def _invalid_version(self, packet: Packet) -> None:
        """Set version fields to invalid values."""
        if packet.haslayer(IP):
            ip = packet[IP]
            # IPv4 version should be 4; set to something else
            ip.version = random.choice([0, 1, 2, 3, 5, 6, 7, 8, 15])
            logger.debug("Set IP version to %d", ip.version)

        # Also try iSCSI version fields
        layer = packet
        while layer:
            if hasattr(layer, 'version_max'):
                layer.version_max = random.randint(1, 0xFF)
                logger.debug("Set iSCSI version_max to %d", layer.version_max)
            if hasattr(layer, 'version_min'):
                layer.version_min = random.randint(1, 0xFF)
                logger.debug("Set iSCSI version_min to %d", layer.version_min)
            layer = layer.payload if hasattr(layer, 'payload') and layer.payload else None

    def _wrong_header_length(self, packet: Packet) -> None:
        """Set header length fields to incorrect values."""
        if packet.haslayer(IP):
            ip = packet[IP]
            # IHL should be 5 (20 bytes) for standard header
            bad_ihl = random.choice([0, 1, 2, 3, 4, 14, 15])
            ip.ihl = bad_ihl
            logger.debug("Set IP IHL to %d (should be 5)", bad_ihl)

        if packet.haslayer(TCP):
            tcp = packet[TCP]
            # Data offset should be 5 (20 bytes) minimum
            bad_offset = random.choice([0, 1, 2, 3, 4, 14, 15])
            tcp.dataofs = bad_offset
            logger.debug("Set TCP data offset to %d (should be >=5)", bad_offset)

    def _field_overflow(self, packet: Packet) -> None:
        """Set fields to boundary/overflow values."""
        if packet.haslayer(IP):
            ip = packet[IP]
            overflow_target = random.choice(["len", "ttl", "frag", "id"])
            if overflow_target == "len":
                ip.len = random.choice([0, 1, 20, 65535])  # Wrong total length
            elif overflow_target == "ttl":
                ip.ttl = 0  # Zero TTL
            elif overflow_target == "frag":
                ip.frag = 0x1FFF  # Max fragment offset
            elif overflow_target == "id":
                ip.id = 0  # Zero identification

        if packet.haslayer(TCP):
            tcp = packet[TCP]
            tcp.window = random.choice([0, 1, 65535])  # Extreme window sizes
