"""
Audit log API endpoints.

View and manage audit logs for user operations.
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.audit_log import AuditLogModel, AuditLogResponse
from ..core.audit import get_recent_logs, cleanup_old_logs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=List[AuditLogResponse])
async def list_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    user_ip: Optional[str] = Query(None, description="Filter by user IP"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    db: AsyncSession = Depends(get_db),
):
    """Get recent audit logs."""
    logs = await get_recent_logs(db, limit, user_ip, action, resource_type)
    return [_to_response(log) for log in logs]


@router.delete("/cleanup")
async def cleanup_audit_logs(
    retention_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Delete audit logs older than retention period."""
    deleted = await cleanup_old_logs(db, retention_days)
    return {"deleted": deleted, "retention_days": retention_days}


@router.get("/stats")
async def get_audit_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get audit log statistics."""
    from sqlalchemy import func, select

    # Total count
    total_result = await db.execute(select(func.count(AuditLogModel.id)))
    total = total_result.scalar() or 0

    # Count by action
    action_result = await db.execute(
        select(AuditLogModel.action, func.count(AuditLogModel.id))
        .group_by(AuditLogModel.action)
        .order_by(func.count(AuditLogModel.id).desc())
        .limit(20)
    )
    by_action = {row[0]: row[1] for row in action_result.all()}

    # Count by user
    user_result = await db.execute(
        select(AuditLogModel.user_ip, func.count(AuditLogModel.id))
        .group_by(AuditLogModel.user_ip)
        .order_by(func.count(AuditLogModel.id).desc())
        .limit(10)
    )
    by_user = {row[0]: row[1] for row in user_result.all()}

    return {
        "total": total,
        "by_action": by_action,
        "by_user": by_user,
    }


def _to_response(log: AuditLogModel) -> AuditLogResponse:
    """Convert database model to response."""
    details = {}
    if log.details:
        try:
            details = json.loads(log.details) if isinstance(log.details, str) else log.details
        except (json.JSONDecodeError, TypeError):
            details = {}

    return AuditLogResponse(
        id=log.id,
        timestamp=log.timestamp,
        user_ip=log.user_ip or "",
        user_nickname=log.user_nickname or "",
        action=log.action or "",
        resource_type=log.resource_type or "",
        resource_id=log.resource_id or "",
        details=details,
        result=log.result or "success",
    )
