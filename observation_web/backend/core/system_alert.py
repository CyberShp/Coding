"""
System alert module for backend error tracking.

Provides centralized error logging and retrieval for debugging.
Supports file-based archiving when memory buffer reaches capacity.
"""

import json
import logging
import os
import threading
import traceback
from collections import deque
from datetime import datetime
from enum import Enum
from pathlib import Path
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
    Automatically archives older alerts to file when capacity reaches 80%.
    """
    
    MAX_ALERTS = 2000
    ARCHIVE_THRESHOLD = 0.8  # Archive when 80% full
    KEEP_IN_MEMORY = 500     # Keep latest 500 in memory after archiving
    
    def __init__(self):
        self._alerts: deque = deque(maxlen=self.MAX_ALERTS)
        self._lock = threading.RLock()
        self._archive_path = Path(__file__).parent.parent.parent / "system_alerts.jsonl"
    
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
            # Auto-archive when reaching capacity threshold
            if len(self._alerts) >= int(self.MAX_ALERTS * self.ARCHIVE_THRESHOLD):
                self._archive_to_file()
        
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
    
    def _archive_to_file(self):
        """
        Archive older alerts to file, keeping only the latest KEEP_IN_MEMORY in memory.
        Must be called while holding self._lock.
        """
        try:
            alerts_list = list(self._alerts)
            if len(alerts_list) <= self.KEEP_IN_MEMORY:
                return
            
            # Alerts to archive (older ones)
            to_archive = alerts_list[:-self.KEEP_IN_MEMORY]
            to_keep = alerts_list[-self.KEEP_IN_MEMORY:]
            
            # Write to JSONL file
            with open(self._archive_path, 'a', encoding='utf-8') as f:
                for alert in to_archive:
                    f.write(json.dumps(alert.to_dict(), ensure_ascii=False) + '\n')
            
            # Reset in-memory store with only recent alerts
            self._alerts.clear()
            for alert in to_keep:
                self._alerts.append(alert)
            
            logger.info(f"Archived {len(to_archive)} system alerts to {self._archive_path}")
        except Exception as e:
            logger.error(f"Failed to archive system alerts: {e}")
    
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
