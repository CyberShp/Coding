"""Hex dump formatting utilities for packet inspection."""

from typing import Optional


def hexdump(data: bytes, width: int = 16, offset: int = 0) -> str:
    """Format binary data as a hex dump string.

    Args:
        data: Binary data to format.
        width: Number of bytes per line.
        offset: Starting offset for address display.

    Returns:
        Formatted hex dump string.

    Example:
        >>> print(hexdump(b'\\x00\\x01\\x02Hello World'))
        00000000  00 01 02 48 65 6c 6c 6f  20 57 6f 72 6c 64        |...Hello World  |
    """
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        # Add mid-line separator
        if width == 16:
            hex_left = " ".join(f"{b:02x}" for b in chunk[:8])
            hex_right = " ".join(f"{b:02x}" for b in chunk[8:])
            hex_part = f"{hex_left:<23s}  {hex_right}"
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        addr = offset + i
        lines.append(f"{addr:08x}  {hex_part:<{width * 3 + 1}s} |{ascii_part:<{width}s}|")
    return "\n".join(lines)


def hex_bytes(data: bytes, separator: str = " ") -> str:
    """Format bytes as a simple hex string.

    Args:
        data: Binary data to format.
        separator: Separator between hex bytes.

    Returns:
        Hex string like "00 01 02 48 65".
    """
    return separator.join(f"{b:02x}" for b in data)


def format_packet_summary(
    packet_bytes: bytes,
    anomaly_type: str = "",
    protocol: str = "",
    max_dump_bytes: int = 128,
) -> str:
    """Format a packet summary with metadata and hex dump.

    Args:
        packet_bytes: Raw packet bytes.
        anomaly_type: Name of the anomaly applied.
        protocol: Protocol name.
        max_dump_bytes: Maximum bytes to show in hex dump.

    Returns:
        Formatted packet summary string.
    """
    lines = []
    lines.append(f"Protocol: {protocol or 'unknown'}")
    lines.append(f"Anomaly:  {anomaly_type or 'none'}")
    lines.append(f"Length:   {len(packet_bytes)} bytes")
    lines.append("")

    display_data = packet_bytes[:max_dump_bytes]
    lines.append(hexdump(display_data))
    if len(packet_bytes) > max_dump_bytes:
        lines.append(f"  ... ({len(packet_bytes) - max_dump_bytes} more bytes)")

    return "\n".join(lines)
