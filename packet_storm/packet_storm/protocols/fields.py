"""Common field helpers for protocol construction.

Provides helper functions for constructing network headers that are
shared across all protocol implementations.
"""

import random
import struct
from typing import Optional

from scapy.layers.l2 import Ether
from scapy.layers.inet import IP, TCP, UDP
from scapy.layers.inet6 import IPv6
from scapy.packet import Packet


def build_ethernet(
    src_mac: str = "00:00:00:00:00:00",
    dst_mac: str = "ff:ff:ff:ff:ff:ff",
    ether_type: int = 0x0800,
) -> Ether:
    """Build an Ethernet frame header.

    Args:
        src_mac: Source MAC address.
        dst_mac: Destination MAC address.
        ether_type: EtherType (0x0800=IPv4, 0x86DD=IPv6).

    Returns:
        Scapy Ether layer.
    """
    return Ether(src=src_mac, dst=dst_mac, type=ether_type)


def build_ipv4(
    src_ip: str = "0.0.0.0",
    dst_ip: str = "0.0.0.0",
    ttl: int = 64,
    proto: int = 6,  # TCP
    flags: int = 0,
    frag: int = 0,
    identification: Optional[int] = None,
) -> IP:
    """Build an IPv4 header.

    Args:
        src_ip: Source IPv4 address.
        dst_ip: Destination IPv4 address.
        ttl: Time to live.
        proto: Protocol number (6=TCP, 17=UDP).
        flags: IP flags.
        frag: Fragment offset.
        identification: IP identification field. Random if None.

    Returns:
        Scapy IP layer.
    """
    pkt = IP(
        src=src_ip,
        dst=dst_ip,
        ttl=ttl,
        proto=proto,
        flags=flags,
        frag=frag,
    )
    if identification is not None:
        pkt.id = identification
    return pkt


def build_ipv6(
    src_ip: str = "::",
    dst_ip: str = "::",
    hop_limit: int = 64,
    next_header: int = 6,  # TCP
    flow_label: int = 0,
    traffic_class: int = 0,
) -> IPv6:
    """Build an IPv6 header.

    Args:
        src_ip: Source IPv6 address.
        dst_ip: Destination IPv6 address.
        hop_limit: Hop limit (equivalent to TTL).
        next_header: Next header type (6=TCP, 17=UDP).
        flow_label: Flow label.
        traffic_class: Traffic class.

    Returns:
        Scapy IPv6 layer.
    """
    return IPv6(
        src=src_ip,
        dst=dst_ip,
        hlim=hop_limit,
        nh=next_header,
        fl=flow_label,
        tc=traffic_class,
    )


def build_tcp(
    src_port: int = 0,
    dst_port: int = 0,
    seq: int = 0,
    ack: int = 0,
    flags: str = "S",
    window: int = 65535,
    urgent: int = 0,
    options: Optional[list] = None,
) -> TCP:
    """Build a TCP header.

    Args:
        src_port: Source port (0 = random ephemeral).
        dst_port: Destination port.
        seq: Sequence number.
        ack: Acknowledgment number.
        flags: TCP flags string ('S', 'SA', 'PA', 'FA', etc.).
        window: Window size.
        urgent: Urgent pointer.
        options: TCP options list.

    Returns:
        Scapy TCP layer.
    """
    if src_port == 0:
        src_port = random.randint(49152, 65535)

    pkt = TCP(
        sport=src_port,
        dport=dst_port,
        seq=seq,
        ack=ack,
        flags=flags,
        window=window,
        urgptr=urgent,
    )
    if options:
        pkt.options = options
    return pkt


def build_udp(
    src_port: int = 0,
    dst_port: int = 0,
) -> UDP:
    """Build a UDP header.

    Args:
        src_port: Source port (0 = random ephemeral).
        dst_port: Destination port.

    Returns:
        Scapy UDP layer.
    """
    if src_port == 0:
        src_port = random.randint(49152, 65535)

    return UDP(
        sport=src_port,
        dport=dst_port,
    )


def build_l2_l4_stack(
    network_config: dict,
    dst_port: int,
    src_port: int = 0,
    transport: str = "tcp",
    tcp_flags: str = "PA",
    seq: int = 0,
    ack: int = 0,
) -> Packet:
    """Build a complete L2-L4 header stack from network config.

    This is a convenience function that builds Ethernet + IP + TCP/UDP
    headers using values from the network configuration.

    Args:
        network_config: Network configuration dictionary.
        dst_port: Destination port.
        src_port: Source port (0 = random ephemeral).
        transport: Transport protocol ('tcp' or 'udp').
        tcp_flags: TCP flags (only for TCP).
        seq: TCP sequence number (only for TCP).
        ack: TCP acknowledgment number (only for TCP).

    Returns:
        Stacked Scapy Packet (Ether/IP/TCP or Ether/IP/UDP).
    """
    use_ipv6 = network_config.get("use_ipv6", False)

    # L2 - Ethernet
    ether_type = 0x86DD if use_ipv6 else 0x0800
    eth = build_ethernet(
        src_mac=network_config.get("src_mac", "00:00:00:00:00:00"),
        dst_mac=network_config.get("dst_mac", "ff:ff:ff:ff:ff:ff"),
        ether_type=ether_type,
    )

    # L3 - IP
    if use_ipv6:
        proto = 6 if transport == "tcp" else 17
        ip = build_ipv6(
            src_ip=network_config.get("src_ipv6", "::"),
            dst_ip=network_config.get("dst_ipv6", "::"),
            next_header=proto,
        )
    else:
        proto = 6 if transport == "tcp" else 17
        ip = build_ipv4(
            src_ip=network_config.get("src_ip", "0.0.0.0"),
            dst_ip=network_config.get("dst_ip", "0.0.0.0"),
            proto=proto,
        )

    # L4 - Transport
    if transport == "tcp":
        l4 = build_tcp(
            src_port=src_port,
            dst_port=dst_port,
            flags=tcp_flags,
            seq=seq,
            ack=ack,
        )
    else:
        l4 = build_udp(
            src_port=src_port,
            dst_port=dst_port,
        )

    return eth / ip / l4


def random_mac() -> str:
    """Generate a random MAC address (locally administered, unicast)."""
    octets = [random.randint(0, 255) for _ in range(6)]
    octets[0] = (octets[0] & 0xFE) | 0x02  # Locally administered, unicast
    return ":".join(f"{o:02x}" for o in octets)


def random_ipv4() -> str:
    """Generate a random non-reserved IPv4 address."""
    while True:
        octets = [random.randint(1, 254) for _ in range(4)]
        # Avoid reserved ranges
        if octets[0] not in (0, 10, 127, 224, 225, 226, 227, 228, 229, 230, 231,
                             232, 233, 234, 235, 236, 237, 238, 239, 240, 255):
            return ".".join(str(o) for o in octets)
