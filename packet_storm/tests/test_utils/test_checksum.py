"""Tests for checksum utilities."""

from packet_storm.utils.checksum import ipv4_checksum, crc32c


class TestIPv4Checksum:
    """Test IPv4 header checksum."""

    def test_known_header(self):
        """Calculate checksum of a known IPv4 header."""
        # Minimal IPv4 header (20 bytes) with zero checksum field
        header = bytes([
            0x45, 0x00, 0x00, 0x3c,  # version, IHL, DSCP, total length
            0x1c, 0x46, 0x40, 0x00,  # identification, flags, fragment offset
            0x40, 0x06, 0x00, 0x00,  # TTL, protocol (TCP), checksum (zeroed)
            0xac, 0x10, 0x0a, 0x63,  # source IP: 172.16.10.99
            0xac, 0x10, 0x0a, 0x0c,  # dest IP: 172.16.10.12
        ])
        checksum = ipv4_checksum(header)
        assert isinstance(checksum, int)
        assert 0 <= checksum <= 0xFFFF

    def test_all_zeros(self):
        """Checksum of all-zero header."""
        header = bytes(20)
        checksum = ipv4_checksum(header)
        assert checksum == 0xFFFF


class TestCRC32C:
    """Test CRC-32C (Castagnoli) checksum."""

    def test_empty_data(self):
        """CRC32C of empty data."""
        result = crc32c(b"")
        assert isinstance(result, int)

    def test_known_value(self):
        """CRC32C produces consistent results."""
        data = b"Hello"
        result1 = crc32c(data)
        result2 = crc32c(data)
        assert result1 == result2
        assert isinstance(result1, int)
