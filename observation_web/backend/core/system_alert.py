"""
System alert module for backend error tracking.

Provides centralized error logging and retrieval for debugging.
"""

import json
import logging
import threading
import traceback
from collections import deque
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    """System alert levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SystemAlert:
    """Single system alert entry"""
    
    def __init__(
        self,
        level: AlertLevel,
        module: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None,
    ):
        self.id = f"sys_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.timestamp = datetime.now().isoformat()
        self.level = level
        self.module = module
        self.message = message
        self.details = details or {}
        self.traceback = None
        
        if exception:
            self.details["exception_type"] = type(exception).__name__
            self.details["exception_message"] = str(exception)
            self.traceback = traceback.format_exc()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level.value,
            "module": self.module,
            "message": self.message,
            "details": self.details,
            "traceback": self.traceback,
        }


class SystemAlertStore:
    """
    In-memory store for system alerts.
    
    Keeps last N alerts for debugging purposes.
    """
    
    MAX_ALERTS = 500
    
    def __init__(self):
        self._alerts: deque = deque(maxlen=self.MAX_ALERTS)
        self._lock = threading.RLock()
    
    def add(
        self,
        level: AlertLevel,
        module: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None,
    ) -> SystemAlert:
        """Add a new system alert"""
        alert = SystemAlert(level, module, message, details, exception)
        
        with self._lock:
            self._alerts.append(alert)
        
        # Also log to standard logger
        log_msg = f"[{module}] {message}"
        if details:
            log_msg += f" | {json.dumps(details, ensure_ascii=False)}"
        
        if level == AlertLevel.DEBUG:
            logger.debug(log_msg)
        elif level == AlertLevel.INFO:
            logger.info(log_msg)
        elif level == AlertLevel.WARNING:
            logger.warning(log_msg)
        elif level == AlertLevel.ERROR:
            logger.error(log_msg, exc_info=exception is not None)
        elif level == AlertLevel.CRITICAL:
            logger.critical(log_msg, exc_info=exception is not None)
        
        return alert
    
    def get_all(
        self,
        level: Optional[AlertLevel] = None,
        module: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get alerts with optional filtering"""
        with self._lock:
            alerts = list(self._alerts)
        
        # Filter
        if level:
            alerts = [a for a in alerts if a.level == level]
        if module:
            alerts = [a for a in alerts if module.lower() in a.module.lower()]
        
        # Return most recent first
        alerts = alerts[-limit:]
        alerts.reverse()
        
        return [a.to_dict() for a in alerts]
    
    def clear(self):
        """Clear all alerts"""
        with self._lock:
            self._alerts.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Get alert statistics"""
        with self._lock:
            alerts = list(self._alerts)
        
        stats = {
            "total": len(alerts),
            "debug": 0,
            "info": 0,
            "warning": 0,
            "error": 0,
            "critical": 0,
        }
        
        for alert in alerts:
            stats[alert.level.value] += 1
        
        return stats


# Global instance
_system_alert_store: Optional[SystemAlertStore] = None


def get_system_alert_store() -> SystemAlertStore:
    """Get global system alert store instance"""
    global _system_alert_store
    if _system_alert_store is None:
        _system_alert_store = SystemAlertStore()
    return _system_alert_store


# Convenience functions
def sys_debug(module: str, message: str, details: Optional[Dict] = None):
    get_system_alert_store().add(AlertLevel.DEBUG, module, message, details)


def sys_info(module: str, message: str, details: Optional[Dict] = None):
    get_system_alert_store().add(AlertLevel.INFO, module, message, details)


def sys_warning(module: str, message: str, details: Optional[Dict] = None):
    get_system_alert_store().add(AlertLevel.WARNING, module, message, details)


def sys_error(module: str, message: str, details: Optional[Dict] = None, exception: Optional[Exception] = None):
    get_system_alert_store().add(AlertLevel.ERROR, module, message, details, exception)


def sys_critical(module: str, message: str, details: Optional[Dict] = None, exception: Optional[Exception] = None):
    get_system_alert_store().add(AlertLevel.CRITICAL, module, message, details, exception)
