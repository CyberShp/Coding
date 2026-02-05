"""Anomaly type registry and discovery.

Provides centralized registration of all anomaly types (generic and
protocol-specific) and factory methods for creating anomaly instances.
"""

from typing import Any, Optional

from .base import BaseAnomaly
from ..core.registry import anomaly_registry
from ..utils.logging import get_logger

logger = get_logger("anomaly.registry")


def register_anomaly(cls: type[BaseAnomaly]) -> type[BaseAnomaly]:
    """Decorator to register an anomaly class in the global registry.

    Usage:
        @register_anomaly
        class MyAnomaly(BaseAnomaly):
            NAME = "my_anomaly"
            ...

    Args:
        cls: Anomaly class to register.

    Returns:
        The same class (unchanged).
    """
    if hasattr(cls, "NAME") and cls.NAME != "unknown":
        anomaly_registry.register(cls.NAME, cls)
    else:
        logger.warning("Cannot register anomaly class %s: no NAME defined", cls.__name__)
    return cls


def create_anomaly(anomaly_type: str, config: dict) -> BaseAnomaly:
    """Create an anomaly instance by type name.

    Args:
        anomaly_type: Registered anomaly type name.
        config: Anomaly configuration dictionary.

    Returns:
        An initialized anomaly instance.

    Raises:
        KeyError: If anomaly_type is not registered.
    """
    return anomaly_registry.create(anomaly_type, config)


def list_anomalies(category: Optional[str] = None) -> list[dict[str, Any]]:
    """List all registered anomaly types.

    Args:
        category: Filter by category ('generic', 'iscsi', etc.)
            If None, returns all.

    Returns:
        List of anomaly info dictionaries.
    """
    result = []
    for name, cls in anomaly_registry.list_all().items():
        info = {
            "name": name,
            "description": getattr(cls, "DESCRIPTION", ""),
            "category": getattr(cls, "CATEGORY", "generic"),
            "applies_to": getattr(cls, "APPLIES_TO", ["all"]),
        }
        if category is None or info["category"] == category:
            result.append(info)
    return result
