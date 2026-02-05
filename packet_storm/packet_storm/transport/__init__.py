"""Packet transport backends for Packet Storm."""

from .base import TransportBackend, TransportError, TransportStats
from .raw_socket import RawSocketTransport
from .scapy_send import ScapyTransport
from ..core.registry import transport_registry

# Register built-in transport backends
transport_registry.register("raw_socket", RawSocketTransport)
transport_registry.register("scapy", ScapyTransport)

__all__ = [
    "TransportBackend",
    "TransportError",
    "TransportStats",
    "RawSocketTransport",
    "ScapyTransport",
]
