"""Tests for validation utilities."""

import pytest

from packet_storm.utils.validation import (
    is_valid_mac, is_valid_ipv4, is_valid_port,
    validate_config, ValidationError,
)


class TestMacValidation:
    """Test MAC address validation."""

    def test_valid_mac(self):
        assert is_valid_mac("aa:bb:cc:dd:ee:ff")
        assert is_valid_mac("00:00:00:00:00:00")
        assert is_valid_mac("FF:FF:FF:FF:FF:FF")

    def test_invalid_mac(self):
        assert not is_valid_mac("not-a-mac")
        assert not is_valid_mac("aa:bb:cc:dd:ee")
        assert not is_valid_mac("")
        assert not is_valid_mac("gg:hh:ii:jj:kk:ll")


class TestIpv4Validation:
    """Test IPv4 address validation."""

    def test_valid_ipv4(self):
        assert is_valid_ipv4("192.168.1.1")
        assert is_valid_ipv4("0.0.0.0")
        assert is_valid_ipv4("255.255.255.255")
        assert is_valid_ipv4("10.0.0.1")

    def test_invalid_ipv4(self):
        assert not is_valid_ipv4("not-an-ip")
        assert not is_valid_ipv4("256.0.0.1")
        assert not is_valid_ipv4("192.168.1")
        assert not is_valid_ipv4("")


class TestPortValidation:
    """Test port number validation."""

    def test_valid_ports(self):
        assert is_valid_port(1)
        assert is_valid_port(80)
        assert is_valid_port(3260)
        assert is_valid_port(65535)

    def test_invalid_ports(self):
        assert not is_valid_port(0)
        assert not is_valid_port(-1)
        assert not is_valid_port(65536)
        assert not is_valid_port(100000)


class TestConfigValidation:
    """Test configuration validation."""

    def test_valid_config(self):
        """Validate a minimal valid config."""
        config = {
            "network": {"src_ip": "192.168.1.1", "dst_ip": "192.168.1.2"},
            "protocol": {"type": "iscsi"},
            "transport": {"backend": "scapy"},
        }
        warnings = validate_config(config)
        assert isinstance(warnings, list)

    def test_missing_network(self):
        """Config without network section should still validate (with warnings)."""
        config = {"protocol": {"type": "iscsi"}}
        warnings = validate_config(config)
        # Should return warnings but not raise
        assert isinstance(warnings, list)
