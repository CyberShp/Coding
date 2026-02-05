"""Multi-level, dual-output logging setup for Packet Storm."""

import logging
import os
import sys
from pathlib import Path
from typing import Optional


LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Compact format for console
CONSOLE_FORMAT = "%(asctime)s [%(levelname)-7s] %(message)s"
CONSOLE_DATE_FORMAT = "%H:%M:%S"


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    console: bool = True,
) -> logging.Logger:
    """Configure root logger with file and/or console handlers.

    Args:
        level: Log level string (DEBUG/INFO/WARNING/ERROR).
        log_file: Path to log file. If None, file logging is disabled.
        console: Whether to enable console output.

    Returns:
        The configured root logger for packet_storm.
    """
    root_logger = logging.getLogger("packet_storm")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root_logger.handlers.clear()

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # File always captures everything
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        root_logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, CONSOLE_DATE_FORMAT))
        root_logger.addHandler(console_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the packet_storm namespace.

    Args:
        name: Logger name (will be prefixed with 'packet_storm.').

    Returns:
        A child logger instance.
    """
    return logging.getLogger(f"packet_storm.{name}")
