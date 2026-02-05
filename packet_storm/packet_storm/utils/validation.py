"""Configuration and input validation utilities."""

import ipaddress
import re
from typing import Any, Optional


MAC_PATTERN = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_PROTOCOLS = {"iscsi", "nvmeof", "nas"}
VALID_BACKENDS = {"raw_socket", "scapy", "dpdk"}
VALID_RATE_MODES = {"pps", "mbps", "gbps"}
VALID_EXEC_MODES = {"single", "batch", "continuous"}


class ValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"Validation error in '{field}': {message}")


def validate_mac(mac: str, field: str = "mac") -> str:
    """Validate and normalize a MAC address string."""
    if mac.lower() == "auto":
        return "auto"
    mac = mac.strip().lower()
    if not MAC_PATTERN.match(mac):
        raise ValidationError(field, f"Invalid MAC address: {mac}")
    return mac


def validate_ip(ip: str, field: str = "ip") -> str:
    """Validate an IPv4 or IPv6 address string."""
    if not ip:
        return ""
    try:
        addr = ipaddress.ip_address(ip)
        return str(addr)
    except ValueError:
        raise ValidationError(field, f"Invalid IP address: {ip}")


def validate_port(port: int, field: str = "port") -> int:
    """Validate a network port number."""
    if not isinstance(port, int) or port < 0 or port > 65535:
        raise ValidationError(field, f"Port must be 0-65535, got: {port}")
    return port


def validate_positive_int(value: int, field: str = "value", allow_zero: bool = False) -> int:
    """Validate that a value is a positive integer."""
    if not isinstance(value, int):
        raise ValidationError(field, f"Expected integer, got: {type(value).__name__}")
    if allow_zero and value < 0:
        raise ValidationError(field, f"Expected non-negative integer, got: {value}")
    if not allow_zero and value <= 0:
        raise ValidationError(field, f"Expected positive integer, got: {value}")
    return value


def validate_enum(value: str, valid_values: set, field: str = "value") -> str:
    """Validate that a value is one of the allowed enum values."""
    if value not in valid_values:
        raise ValidationError(
            field,
            f"Invalid value '{value}'. Must be one of: {', '.join(sorted(valid_values))}"
        )
    return value


def validate_config(config: dict) -> list[str]:
    """Validate a full configuration dictionary.

    Returns a list of warning messages (empty if all good).
    Raises ValidationError on critical issues.
    """
    warnings = []

    # Validate global section
    global_cfg = config.get("global", {})
    log_level = global_cfg.get("log_level", "INFO")
    validate_enum(log_level.upper(), VALID_LOG_LEVELS, "global.log_level")

    # Validate network section
    net = config.get("network", {})
    if net.get("src_mac", "auto") != "auto":
        validate_mac(net["src_mac"], "network.src_mac")
    validate_mac(net.get("dst_mac", "ff:ff:ff:ff:ff:ff"), "network.dst_mac")

    if net.get("src_ip"):
        validate_ip(net["src_ip"], "network.src_ip")
    if net.get("dst_ip"):
        validate_ip(net["dst_ip"], "network.dst_ip")
    if net.get("use_ipv6"):
        if net.get("src_ipv6"):
            validate_ip(net["src_ipv6"], "network.src_ipv6")
        if net.get("dst_ipv6"):
            validate_ip(net["dst_ipv6"], "network.dst_ipv6")

    # Validate transport section
    transport = config.get("transport", {})
    backend = transport.get("backend", "scapy")
    validate_enum(backend, VALID_BACKENDS, "transport.backend")

    rate = transport.get("rate_limit", {})
    if rate.get("enabled"):
        validate_enum(rate.get("mode", "pps"), VALID_RATE_MODES, "transport.rate_limit.mode")
        validate_positive_int(rate.get("value", 1), "transport.rate_limit.value")

    # Validate protocol section
    proto = config.get("protocol", {})
    proto_type = proto.get("type", "iscsi")
    validate_enum(proto_type, VALID_PROTOCOLS, "protocol.type")

    if proto_type == "iscsi":
        iscsi = proto.get("iscsi", {})
        validate_port(iscsi.get("target_port", 3260), "protocol.iscsi.target_port")
    elif proto_type == "nvmeof":
        nvmeof = proto.get("nvmeof", {})
        validate_port(nvmeof.get("target_port", 4420), "protocol.nvmeof.target_port")

    # Validate execution section
    execution = config.get("execution", {})
    validate_enum(execution.get("mode", "single"), VALID_EXEC_MODES, "execution.mode")

    return warnings
