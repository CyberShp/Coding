"""JSON configuration loader with validation and deep merge support."""

import json
import copy
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import get_logger
from ..utils.validation import validate_config, ValidationError

logger = get_logger("config")

# Path to the bundled default configuration
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "configs" / "default.json"


class ConfigManager:
    """Manages tool configuration from JSON files with merge and validation.

    Supports loading defaults, merging user overrides, runtime modification,
    and import/export of configuration snapshots.
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration manager.

        Args:
            config_path: Path to user config file. If None, uses defaults only.
        """
        self._config: dict = {}
        self._config_path: Optional[Path] = Path(config_path) if config_path else None
        self._load()

    def _load(self) -> None:
        """Load default config, then merge user config if provided."""
        # Load defaults
        self._config = self._read_json(DEFAULT_CONFIG_PATH)
        logger.debug("Loaded default config from %s", DEFAULT_CONFIG_PATH)

        # Merge user config
        if self._config_path and self._config_path.exists():
            user_config = self._read_json(self._config_path)
            self._config = self._deep_merge(self._config, user_config)
            logger.info("Merged user config from %s", self._config_path)

        # Validate
        try:
            warnings = validate_config(self._config)
            for w in warnings:
                logger.warning("Config warning: %s", w)
        except ValidationError as e:
            logger.error("Config validation failed: %s", e)
            raise

    @staticmethod
    def _read_json(path: Path) -> dict:
        """Read and parse a JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise ConfigError(f"Failed to read config file {path}: {e}") from e

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge override dict into base dict.

        Args:
            base: Base configuration dictionary.
            override: Override values to merge in.

        Returns:
            New merged dictionary (base is not modified).
        """
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    @property
    def config(self) -> dict:
        """Get the full configuration dictionary."""
        return self._config

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get a config value by dot-separated key path.

        Args:
            key_path: Dot-separated path like 'network.src_ip'.
            default: Default value if key not found.

        Returns:
            The config value or default.

        Example:
            >>> cfg.get('protocol.iscsi.target_port')
            3260
        """
        keys = key_path.split(".")
        current = self._config
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default
        return current

    def set(self, key_path: str, value: Any) -> None:
        """Set a config value by dot-separated key path at runtime.

        Args:
            key_path: Dot-separated path like 'network.src_ip'.
            value: New value to set.
        """
        keys = key_path.split(".")
        current = self._config
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value
        logger.info("Config updated: %s = %s", key_path, value)

    def export_config(self, path: str) -> None:
        """Export current configuration to a JSON file.

        Args:
            path: Output file path.
        """
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)
        logger.info("Config exported to %s", output)

    def import_config(self, path: str) -> None:
        """Import configuration from a JSON file, replacing current config.

        Args:
            path: Input file path.
        """
        new_config = self._read_json(Path(path))
        validate_config(new_config)
        self._config = new_config
        logger.info("Config imported from %s", path)

    def reload(self) -> None:
        """Reload configuration from files."""
        self._load()
        logger.info("Config reloaded")

    def get_network_config(self) -> dict:
        """Get the network configuration section."""
        return self._config.get("network", {})

    def get_protocol_config(self) -> dict:
        """Get the active protocol configuration section."""
        proto_type = self._config.get("protocol", {}).get("type", "iscsi")
        return self._config.get("protocol", {}).get(proto_type, {})

    def get_protocol_type(self) -> str:
        """Get the active protocol type."""
        return self._config.get("protocol", {}).get("type", "iscsi")

    def get_transport_config(self) -> dict:
        """Get the transport configuration section."""
        return self._config.get("transport", {})

    def get_anomalies_config(self) -> list[dict]:
        """Get the list of anomaly configurations."""
        return self._config.get("anomalies", [])

    def get_execution_config(self) -> dict:
        """Get the execution configuration section."""
        return self._config.get("execution", {})


class ConfigError(Exception):
    """Raised when configuration loading or parsing fails."""
    pass
