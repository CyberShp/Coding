"""Checksum calculation helpers for TCP/UDP/IP protocols."""

import struct
from typing import Optional


def ones_complement_sum(data: bytes) -> int:
    """Calculate the one's complement sum of a byte sequence.

    This is the core building block for IP/TCP/UDP checksums.

    Args:
        data: Byte sequence to sum.

    Returns:
        16-bit one's complement sum.
    """
    if len(data) % 2:
        data = data + b"\x00"

    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
        # Fold carry bits
        total = (total & 0xFFFF) + (total >> 16)

    return total


def ip_checksum(header: bytes) -> int:
    """Calculate IPv4 header checksum per RFC 791.

    Args:
        header: IPv4 header bytes (with checksum field zeroed).

    Returns:
        16-bit checksum value.
    """
    s = ones_complement_sum(header)
    return (~s) & 0xFFFF


def tcp_checksum(
    src_ip: str,
    dst_ip: str,
    tcp_segment: bytes,
) -> int:
    """Calculate TCP checksum with pseudo-header per RFC 793.

    Args:
        src_ip: Source IPv4 address string.
        dst_ip: Destination IPv4 address string.
        tcp_segment: Full TCP segment (header + data).

    Returns:
        16-bit checksum value.
    """
    # Build pseudo-header
    src = _ip_to_bytes(src_ip)
    dst = _ip_to_bytes(dst_ip)
    pseudo = struct.pack("!4s4sBBH", src, dst, 0, 6, len(tcp_segment))

    data = pseudo + tcp_segment
    s = ones_complement_sum(data)
    return (~s) & 0xFFFF


def udp_checksum(
    src_ip: str,
    dst_ip: str,
    udp_segment: bytes,
) -> int:
    """Calculate UDP checksum with pseudo-header per RFC 768.

    Args:
        src_ip: Source IPv4 address string.
        dst_ip: Destination IPv4 address string.
        udp_segment: Full UDP segment (header + data).

    Returns:
        16-bit checksum value. Returns 0xFFFF if computed checksum is 0.
    """
    src = _ip_to_bytes(src_ip)
    dst = _ip_to_bytes(dst_ip)
    pseudo = struct.pack("!4s4sBBH", src, dst, 0, 17, len(udp_segment))

    data = pseudo + udp_segment
    s = ones_complement_sum(data)
    result = (~s) & 0xFFFF
    # UDP uses 0xFFFF for zero checksum
    return result if result != 0 else 0xFFFF


def tcp6_checksum(
    src_ip6: str,
    dst_ip6: str,
    tcp_segment: bytes,
) -> int:
    """Calculate TCP checksum with IPv6 pseudo-header per RFC 2460.

    Args:
        src_ip6: Source IPv6 address string.
        dst_ip6: Destination IPv6 address string.
        tcp_segment: Full TCP segment (header + data).

    Returns:
        16-bit checksum value.
    """
    import ipaddress

    src = ipaddress.ip_address(src_ip6).packed
    dst = ipaddress.ip_address(dst_ip6).packed
    pseudo = struct.pack("!16s16sIxxxB", src, dst, len(tcp_segment), 6)

    data = pseudo + tcp_segment
    s = ones_complement_sum(data)
    return (~s) & 0xFFFF


def udp6_checksum(
    src_ip6: str,
    dst_ip6: str,
    udp_segment: bytes,
) -> int:
    """Calculate UDP checksum with IPv6 pseudo-header.

    Args:
        src_ip6: Source IPv6 address string.
        dst_ip6: Destination IPv6 address string.
        udp_segment: Full UDP segment (header + data).

    Returns:
        16-bit checksum value.
    """
    import ipaddress

    src = ipaddress.ip_address(src_ip6).packed
    dst = ipaddress.ip_address(dst_ip6).packed
    pseudo = struct.pack("!16s16sIxxxB", src, dst, len(udp_segment), 17)

    data = pseudo + udp_segment
    s = ones_complement_sum(data)
    result = (~s) & 0xFFFF
    return result if result != 0 else 0xFFFF


def crc32c(data: bytes) -> int:
    """Calculate CRC-32C (Castagnoli) used by iSCSI and NVMe-oF.

    Args:
        data: Input byte sequence.

    Returns:
        32-bit CRC-32C value.
    """
    # Use the crc32c table (Castagnoli polynomial 0x1EDC6F41)
    crc = 0xFFFFFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC32C_TABLE[(crc ^ byte) & 0xFF]
    return crc ^ 0xFFFFFFFF


def _ip_to_bytes(ip: str) -> bytes:
    """Convert an IPv4 address string to 4 bytes."""
    import ipaddress
    return ipaddress.ip_address(ip).packed


# Pre-computed CRC-32C lookup table (Castagnoli polynomial)
def _build_crc32c_table() -> list[int]:
    """Build the CRC-32C lookup table."""
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x82F63B78
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC32C_TABLE = _build_crc32c_table()
