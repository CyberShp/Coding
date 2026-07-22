"""
Issue/feedback API endpoints.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.issue import (
    IssueModel,
    IssueCreate,
    IssueUpdateStatus,
    IssueResponse,
)
from ..models.user_account import UserAccountModel
from .auth import require_admin, require_user, _verify_token

router = APIRouter(prefix="/issues", tags=["issues"])


def _is_admin(request: Request) -> bool:
    """Check if request has a valid admin token.

    Accepts legacy admin tokens (config.json account) or user tokens whose
    signed payload carries is_admin=True.
    """
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if not token:
        return False
    payload = _verify_token(token)
    if not payload:
        return False
    if payload.get("typ") == "user":
        return bool(payload.get("is_admin"))
    return True


def _can_change_status(
    request: Request, issue: IssueModel, is_admin: bool,
    user: "UserAccountModel" = None,
) -> bool:
    """Only creator or admin can change status.

    Creator match is either account nickname (multi-user Phase 1) or the
    legacy same-IP rule.
    """
    if is_admin:
        return True
    if user is not None:
        if user.is_admin:
            return True
        if user.nickname and issue.created_by_nickname == user.nickname:
            return True
    user_ip = getattr(request.state, 'user_ip', None)
    return bool(user_ip and issue.created_by_ip == user_ip)


@router.get("", response_model=List[IssueResponse])
async def list_issues(
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List issues, optionally filtered by status."""
    stmt = select(IssueModel).order_by(IssueModel.created_at.desc())
    if status_filter:
        stmt = stmt.where(IssueModel.status == status_filter)
    result = await db.execute(stmt)
    issues = result.scalars().all()
    return [IssueResponse.model_validate(i) for i in issues]


@router.post("", response_model=IssueResponse)
async def create_issue(
    request: Request,
    body: IssueCreate,
    db: AsyncSession = Depends(get_db),
    user: UserAccountModel = Depends(require_user),
):
    """Create a new issue (logged-in user)."""
    user_ip = getattr(request.state, 'user_ip', 'unknown')
    user_nickname = user.nickname or ''

    issue = IssueModel(
        title=body.title.strip()[:256],
        content=body.content.strip(),
        status="open",
        created_by_ip=user_ip,
        created_by_nickname=user_nickname,
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)
    return IssueResponse.model_validate(issue)


@router.get("/{issue_id}", response_model=IssueResponse)
async def get_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get issue by ID."""
    result = await db.execute(select(IssueModel).where(IssueModel.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return IssueResponse.model_validate(issue)


@router.put("/{issue_id}/status", response_model=IssueResponse)
async def update_issue_status(
    issue_id: int,
    request: Request,
    body: IssueUpdateStatus,
    db: AsyncSession = Depends(get_db),
    user: UserAccountModel = Depends(require_user),
):
    """
    Update issue status. Only creator or admin can change.
    Use Authorization header for admin, or must be creator (same IP).
    """
    if body.status not in ("open", "resolved", "rejected", "adopted"):
        raise HTTPException(status_code=400, detail="Invalid status")

    result = await db.execute(select(IssueModel).where(IssueModel.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    is_admin = _is_admin(request)

    if not _can_change_status(request, issue, is_admin, user=user):
        raise HTTPException(status_code=403, detail="仅创建者或管理员可修改状态")

    user_ip = getattr(request.state, 'user_ip', '')
    user_nickname = user.nickname or ''

    issue.status = body.status
    issue.resolution_note = (body.resolution_note or '')[:2000]
    issue.resolved_by_ip = user_ip
    issue.resolved_by_nickname = user_nickname

    await db.commit()
    await db.refresh(issue)
    return IssueResponse.model_validate(issue)


