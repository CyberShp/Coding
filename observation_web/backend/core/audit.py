"""
Audit logging service.

Provides simple functions to log user operations for accountability.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.audit_log import AuditLogModel

logger = logging.getLogger(__name__)

# Global flag to enable/disable audit logging
_audit_enabled = True


def set_audit_enabled(enabled: bool):
    """Enable or disable audit logging"""
    global _audit_enabled
    _audit_enabled = enabled


async def log_action(
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: str,
    user_ip: str = "",
    user_nickname: str = "",
    details: Dict[str, Any] = None,
    result: str = "success",
):
    """
    Log a user action.

    Args:
        db: Database session
        action: Action identifier (e.g., 'array.connect')
        resource_type: Type of resource (e.g., 'array')
        resource_id: ID of the affected resource
        user_ip: IP address of the user
        user_nickname: Nickname of the user (if set)
        details: Additional details as dict
        result: Result of the action ('success', 'failure', 'error')
    """
    if not _audit_enabled:
        return

    try:
        log_entry = AuditLogModel(
            user_ip=user_ip or "",
            user_nickname=user_nickname or "",
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details=json.dumps(details or {}),
            result=result,
        )
        db.add(log_entry)
        # Don't commit here - let the calling function's transaction handle it
    except Exception as e:
        logger.warning(f"Failed to log audit action: {e}")


async def get_recent_logs(
    db: AsyncSession,
    limit: int = 100,
    user_ip: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> List[AuditLogModel]:
    """
    Get recent audit logs.

    Args:
        db: Database session
        limit: Max number of logs to return
        user_ip: Filter by user IP
        action: Filter by action type
        resource_type: Filter by resource type
    """
    query = select(AuditLogModel).order_by(AuditLogModel.timestamp.desc())

    if user_ip:
        query = query.where(AuditLogModel.user_ip == user_ip)
    if action:
        query = query.where(AuditLogModel.action == action)
    if resource_type:
        query = query.where(AuditLogModel.resource_type == resource_type)

    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def cleanup_old_logs(db: AsyncSession, retention_days: int = 30) -> int:
    """
    Delete audit logs older than retention period.

    Args:
        db: Database session
        retention_days: Number of days to retain logs

    Returns:
        Number of deleted logs
    """
    cutoff = datetime.now() - timedelta(days=retention_days)
    result = await db.execute(
        sa_delete(AuditLogModel).where(AuditLogModel.timestamp < cutoff)
    )
    await db.commit()
    deleted = result.rowcount
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} audit logs older than {retention_days} days")
    return deleted
