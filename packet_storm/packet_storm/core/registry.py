"""Plugin registry for protocol builders and anomaly generators.

Provides a centralized registry for dynamically discovering and instantiating
protocol and anomaly plugins.
"""

from typing import Any, Optional

from ..utils.logging import get_logger

logger = get_logger("registry")


class Registry:
    """Generic plugin registry supporting protocol builders and anomaly generators.

    Plugins register themselves with a unique name and can be looked up at runtime.
    """

    def __init__(self, kind: str = "plugin"):
        """Initialize the registry.

        Args:
            kind: Description of what this registry holds (for logging).
        """
        self._kind = kind
        self._entries: dict[str, type] = {}

    def register(self, name: str, cls: type) -> None:
        """Register a plugin class.

        Args:
            name: Unique name for the plugin.
            cls: The plugin class to register.
        """
        if name in self._entries:
            logger.warning(
                "Overwriting existing %s registration: %s", self._kind, name
            )
        self._entries[name] = cls
        logger.debug("Registered %s: %s -> %s", self._kind, name, cls.__name__)

    def get(self, name: str) -> Optional[type]:
        """Get a registered plugin class by name.

        Args:
            name: Plugin name.

        Returns:
            The plugin class, or None if not found.
        """
        return self._entries.get(name)

    def create(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Create an instance of a registered plugin.

        Args:
            name: Plugin name.
            *args: Positional arguments for the constructor.
            **kwargs: Keyword arguments for the constructor.

        Returns:
            An instance of the plugin.

        Raises:
            KeyError: If plugin name is not registered.
        """
        cls = self._entries.get(name)
        if cls is None:
            raise KeyError(
                f"Unknown {self._kind}: '{name}'. "
                f"Available: {', '.join(sorted(self._entries.keys()))}"
            )
        return cls(*args, **kwargs)

    def list_names(self) -> list[str]:
        """List all registered plugin names."""
        return sorted(self._entries.keys())

    def list_all(self) -> dict[str, type]:
        """Get a copy of all registered entries."""
        return dict(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)


# Global registries
protocol_registry = Registry("protocol")
anomaly_registry = Registry("anomaly")
transport_registry = Registry("transport")
