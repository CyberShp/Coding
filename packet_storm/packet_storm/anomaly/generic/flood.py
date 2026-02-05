"""Protocol-aware flood anomaly - generates high-volume attack traffic."""

import random
from typing import Any

from scapy.packet import Packet
from scapy.layers.inet import IP, TCP, UDP

from ..base import BaseAnomaly
from ..registry import register_anomaly
from ...protocols.fields import random_ipv4
from ...utils.logging import get_logger

logger = get_logger("anomaly.flood")


@register_anomaly
class FloodAnomaly(BaseAnomaly):
    """Generates flood-style attack packets with randomized source info.

    Modes:
    - 'syn_flood': SYN packets with random source IPs/ports
    - 'rst_flood': RST packets to disrupt connections
    - 'fin_flood': FIN packets to exhaust connection tracking
    - 'udp_flood': UDP packets with random data
    - 'source_randomize': Current packet with randomized source IP/port
    - 'mixed': Random combination
    """

    NAME = "flood"
    DESCRIPTION = "Generate flood-style attack packets with randomized sources"
    CATEGORY = "generic"
    APPLIES_TO = ["all"]

    def __init__(self, config: dict):
        super().__init__(config)
        self._mode = config.get("mode", "source_randomize")
        self._randomize_src_ip = config.get("randomize_src_ip", True)
        self._randomize_src_port = config.get("randomize_src_port", True)

    def apply(self, packet: Packet) -> Packet:
        """Apply flood modifications to the packet."""
        pkt = self._copy_packet(packet)
        self._applied_count += 1

        if self._mode == "mixed":
            mode = random.choice([
                "syn_flood", "rst_flood", "fin_flood",
                "source_randomize",
            ])
        else:
            mode = self._mode

        if mode == "syn_flood":
            self._syn_flood(pkt)
        elif mode == "rst_flood":
            self._rst_flood(pkt)
        elif mode == "fin_flood":
            self._fin_flood(pkt)
        elif mode == "source_randomize":
            self._source_randomize(pkt)

        return pkt

    def _syn_flood(self, packet: Packet) -> None:
        """Convert packet to a SYN flood packet."""
        if packet.haslayer(TCP):
            tcp = packet[TCP]
            tcp.flags = "S"
            tcp.seq = random.randint(0, 0xFFFFFFFF)
            tcp.ack = 0
            if self._randomize_src_port:
                tcp.sport = random.randint(1024, 65535)
        self._randomize_source_ip(packet)

    def _rst_flood(self, packet: Packet) -> None:
        """Convert packet to a RST flood packet."""
        if packet.haslayer(TCP):
            tcp = packet[TCP]
            tcp.flags = "R"
            tcp.seq = random.randint(0, 0xFFFFFFFF)
            if self._randomize_src_port:
                tcp.sport = random.randint(1024, 65535)
        self._randomize_source_ip(packet)

    def _fin_flood(self, packet: Packet) -> None:
        """Convert packet to a FIN flood packet."""
        if packet.haslayer(TCP):
            tcp = packet[TCP]
            tcp.flags = "FA"
            tcp.seq = random.randint(0, 0xFFFFFFFF)
            tcp.ack = random.randint(0, 0xFFFFFFFF)
            if self._randomize_src_port:
                tcp.sport = random.randint(1024, 65535)
        self._randomize_source_ip(packet)

    def _source_randomize(self, packet: Packet) -> None:
        """Randomize source IP and port while keeping everything else."""
        self._randomize_source_ip(packet)
        if self._randomize_src_port and packet.haslayer(TCP):
            packet[TCP].sport = random.randint(1024, 65535)
        if self._randomize_src_port and packet.haslayer(UDP):
            packet[UDP].sport = random.randint(1024, 65535)

    def _randomize_source_ip(self, packet: Packet) -> None:
        """Randomize the source IP address."""
        if self._randomize_src_ip and packet.haslayer(IP):
            packet[IP].src = random_ipv4()
            # Clear checksum for recalculation
            del packet[IP].chksum
            if packet.haslayer(TCP):
                del packet[TCP].chksum
            if packet.haslayer(UDP):
                del packet[UDP].chksum
