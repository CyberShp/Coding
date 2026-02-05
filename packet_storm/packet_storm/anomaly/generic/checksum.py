"""Checksum error anomaly - corrupts checksums at various protocol layers."""

import random
import struct
from typing import Any

from scapy.packet import Packet
from scapy.layers.inet import IP, TCP, UDP
from scapy.layers.inet6 import IPv6

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...utils.logging import get_logger

logger = get_logger("anomaly.checksum")


@register_anomaly
class ChecksumErrorAnomaly(BaseAnomaly):
    """Corrupts checksums at IP, TCP, UDP, or protocol application layers.

    Modes:
    - 'ip': Corrupt IPv4 header checksum
    - 'tcp': Corrupt TCP checksum
    - 'udp': Corrupt UDP checksum
    - 'all': Corrupt all available checksums
    - 'random': Randomly pick which checksum(s) to corrupt
    - 'protocol': Corrupt application-layer checksums (e.g., iSCSI CRC32C)
    """

    NAME = "checksum_error"
    DESCRIPTION = "Corrupt checksums at IP/TCP/UDP/protocol layers"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._layer = config.get("layer", "random")

    def apply(self, packet: Packet) -> Packet:
        """Corrupt checksum(s) in the packet."""
        pkt = self._copy_packet(packet)
        self._applied_count += 1

        target = self._layer
        if target == "random":
            options = []
            if pkt.haslayer(IP):
                options.append("ip")
            if pkt.haslayer(TCP):
                options.append("tcp")
            if pkt.haslayer(UDP):
                options.append("udp")
            target = random.choice(options) if options else "ip"

        if target in ("ip", "all"):
            self._corrupt_ip_checksum(pkt)
        if target in ("tcp", "all"):
            self._corrupt_tcp_checksum(pkt)
        if target in ("udp", "all"):
            self._corrupt_udp_checksum(pkt)

        return pkt

    def _corrupt_ip_checksum(self, packet: Packet) -> None:
        """Corrupt the IPv4 header checksum."""
        if packet.haslayer(IP):
            ip_layer = packet[IP]
            # Force Scapy to compute the checksum first
            del ip_layer.chksum
            # Serialize to get the correct checksum
            correct = IP(bytes(ip_layer)).chksum or 0
            # Set to an incorrect value
            bad_checksum = self._generate_bad_checksum(correct)
            ip_layer.chksum = bad_checksum
            logger.debug("Corrupted IP checksum: 0x%04x -> 0x%04x", correct, bad_checksum)

    def _corrupt_tcp_checksum(self, packet: Packet) -> None:
        """Corrupt the TCP checksum."""
        if packet.haslayer(TCP):
            tcp_layer = packet[TCP]
            del tcp_layer.chksum
            correct = TCP(bytes(tcp_layer)).chksum or 0
            bad_checksum = self._generate_bad_checksum(correct)
            tcp_layer.chksum = bad_checksum
            logger.debug("Corrupted TCP checksum: 0x%04x -> 0x%04x", correct, bad_checksum)

    def _corrupt_udp_checksum(self, packet: Packet) -> None:
        """Corrupt the UDP checksum."""
        if packet.haslayer(UDP):
            udp_layer = packet[UDP]
            del udp_layer.chksum
            correct = UDP(bytes(udp_layer)).chksum or 0
            bad_checksum = self._generate_bad_checksum(correct)
            udp_layer.chksum = bad_checksum
            logger.debug("Corrupted UDP checksum: 0x%04x -> 0x%04x", correct, bad_checksum)

    @staticmethod
    def _generate_bad_checksum(correct: int) -> int:
        """Generate a checksum value that is definitely wrong."""
        methods = [
            lambda c: (c + random.randint(1, 0x7FFF)) & 0xFFFF,  # Add offset
            lambda c: c ^ random.randint(1, 0xFFFF),              # XOR
            lambda c: (~c) & 0xFFFF,                               # Bitwise complement
            lambda c: 0,                                           # Zero
            lambda c: 0xFFFF,                                      # Max
            lambda c: random.randint(0, 0xFFFF),                   # Random
        ]
        bad = random.choice(methods)(correct)
        # Make sure it's actually different
        if bad == correct:
            bad = (correct + 1) & 0xFFFF
        return bad
