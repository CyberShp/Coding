"""
Webhook notification service.

Sends notifications to external systems when important events occur.
This is an optional feature - configure webhook URL in config to enable.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import deque

import aiohttp

logger = logging.getLogger(__name__)

# Configuration
_webhook_url: Optional[str] = None
_webhook_enabled = False
_timeout_seconds = 10
_retry_count = 3
_batch_queue: deque = deque(maxlen=100)  # Buffer for failed notifications


def configure_webhook(url: Optional[str], enabled: bool = True, timeout: int = 10):
    """Configure webhook settings"""
    global _webhook_url, _webhook_enabled, _timeout_seconds
    _webhook_url = url
    _webhook_enabled = enabled and bool(url)
    _timeout_seconds = timeout
    if _webhook_enabled:
        logger.info(f"Webhook notifications enabled: {url}")


async def send_notification(
    event_type: str,
    data: Dict[str, Any],
    severity: str = "info",
):
    """
    Send a webhook notification.

    Args:
        event_type: Type of event (e.g., 'alert.new', 'task.started')
        data: Event data
        severity: Severity level (info, warning, error, critical)
    """
    if not _webhook_enabled:
        return

    payload = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "severity": severity,
        "data": data,
    }

    asyncio.create_task(_do_send(payload))


async def _do_send(payload: Dict):
    """Actually send the webhook notification"""
    for attempt in range(_retry_count):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=_timeout_seconds),
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status < 300:
                        logger.debug(f"Webhook sent: {payload['event_type']}")
                        return
                    else:
                        logger.warning(f"Webhook returned {response.status}")
        except asyncio.TimeoutError:
            logger.warning(f"Webhook timeout (attempt {attempt + 1})")
        except Exception as e:
            logger.warning(f"Webhook error (attempt {attempt + 1}): {e}")

        if attempt < _retry_count - 1:
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

    # Failed after all retries, add to buffer
    _batch_queue.append(payload)
    logger.error(f"Webhook failed after {_retry_count} attempts, buffered")


# Convenience functions for common events
async def notify_alert(alert: Dict, array_id: str):
    """Notify about a new alert"""
    await send_notification(
        "alert.new",
        {"alert": alert, "array_id": array_id},
        severity=alert.get("level", "info"),
    )


async def notify_task_started(task_id: int, task_name: str, array_ids: List[str], user_ip: str):
    """Notify about a test task starting"""
    await send_notification(
        "task.started",
        {
            "task_id": task_id,
            "task_name": task_name,
            "array_ids": array_ids,
            "user_ip": user_ip,
        },
        severity="info",
    )


async def notify_task_stopped(task_id: int, task_name: str, summary: Dict):
    """Notify about a test task completing"""
    await send_notification(
        "task.stopped",
        {
            "task_id": task_id,
            "task_name": task_name,
            "summary": summary,
        },
        severity="info",
    )


async def notify_array_status_change(array_id: str, old_status: str, new_status: str):
    """Notify about array connection status change"""
    await send_notification(
        "array.status_changed",
        {
            "array_id": array_id,
            "old_status": old_status,
            "new_status": new_status,
        },
        severity="warning" if new_status == "disconnected" else "info",
    )
