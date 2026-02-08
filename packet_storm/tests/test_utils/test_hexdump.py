"""Tests for hexdump utilities."""

from packet_storm.utils.hexdump import hexdump, hex_bytes, format_packet_summary


class TestHexdump:
    """Test hexdump formatting."""

    def test_hexdump_basic(self):
        """Hexdump of simple data."""
        data = b"Hello, World!"
        result = hexdump(data)
        assert isinstance(result, str)
        assert "48 65 6c 6c 6f" in result.lower()

    def test_hexdump_empty(self):
        """Hexdump of empty data."""
        result = hexdump(b"")
        assert result == "" or "empty" in result.lower() or result.strip() == ""

    def test_hex_bytes(self):
        """hex_bytes formatting."""
        result = hex_bytes(b"\x00\x01\x02\xff")
        assert "00" in result
        assert "ff" in result.lower()

    def test_format_packet_summary(self):
        """Packet summary formatting."""
        result = format_packet_summary(b"\x00" * 64)
        assert isinstance(result, str)
        assert len(result) > 0
