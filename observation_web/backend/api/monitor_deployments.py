"""Custom observer desired assignments and verified Agent deployments."""

import asyncio
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..core.custom_observer_deployer import deploy_agent_config
from ..core.monitor_template_service import (
    desired_monitors_for_array,
    replace_assignments,
    resolve_assignment_arrays,
)
from ..core.ssh_pool import get_ssh_pool
from ..db.database import get_db
from ..models.alert import AlertModel
from ..models.monitor_template import (
    MonitorAssignmentModel,
    MonitorDeploymentModel,
    MonitorTemplateModel,
)
from ..models.user_account import UserAccountModel
from .auth import require_user


logger = logging.getLogger(__name__)
router = APIRouter()


class AssignmentRequest(BaseModel):
    target_type: str
    target_ids: List[int]


class DeployRequest(BaseModel):
    template_ids: List[int]
    target_type: str
    target_ids: List[int]


def _assignment_to_dict(row: MonitorAssignmentModel) -> dict:
    return {
        "id": row.id,
        "template_id": row.template_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "desired_version": row.desired_version,
        "is_enabled": row.is_enabled,
        "status": row.status,
        "status_message": row.status_message or "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/{template_id}/assignments", response_model=List[dict])
async def list_assignments(
    template_id: int,
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonitorAssignmentModel)
        .where(
            MonitorAssignmentModel.template_id == template_id,
            MonitorAssignmentModel.is_enabled.is_(True),
        )
        .order_by(MonitorAssignmentModel.target_type, MonitorAssignmentModel.target_id)
    )
    return [_assignment_to_dict(row) for row in result.scalars().all()]


@router.put("/{template_id}/assignments", response_model=List[dict])
async def save_assignments(
    template_id: int,
    body: AssignmentRequest,
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if body.target_type not in {"array", "tag"}:
        raise HTTPException(status_code=400, detail="target_type must be 'tag' or 'array'")
    result = await db.execute(
        select(MonitorTemplateModel).where(MonitorTemplateModel.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    rows = await replace_assignments(
        db, template, body.target_type, body.target_ids, user.nickname or ""
    )
    await db.commit()
    return [_assignment_to_dict(row) for row in rows]


@router.get("/{template_id}/deployments", response_model=List[dict])
async def list_deployments(
    template_id: int,
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonitorDeploymentModel)
        .where(MonitorDeploymentModel.template_id == template_id)
        .order_by(MonitorDeploymentModel.array_id)
    )
    return [
        {
            "id": row.id,
            "assignment_id": row.assignment_id,
            "template_id": row.template_id,
            "array_id": row.array_id,
            "desired_version": row.desired_version,
            "desired_hash": row.desired_hash or "",
            "loaded_hash": row.loaded_hash or "",
            "status": row.status,
            "status_message": row.status_message or "",
            "attempted_at": row.attempted_at.isoformat() if row.attempted_at else None,
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        }
        for row in result.scalars().all()
    ]


@router.get("/health", response_model=List[dict])
async def deployment_health(
    _user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Health dashboard: one row per deployment with its last-alert time.

    last_alert_at is correlated from the alerts table. Agent-executed custom
    monitors stamp their originating template_id into ``alerts.details`` (see
    CustomMonitorObserver._template_details), so we match on that substring
    scoped to the same array_id — this is robust regardless of the
    owner-suffixed observer_name and needs no schema change.
    """
    result = await db.execute(
        select(MonitorDeploymentModel, MonitorTemplateModel, MonitorAssignmentModel)
        .join(
            MonitorTemplateModel,
            MonitorTemplateModel.id == MonitorDeploymentModel.template_id,
            isouter=True,
        )
        .join(
            MonitorAssignmentModel,
            MonitorAssignmentModel.id == MonitorDeploymentModel.assignment_id,
            isouter=True,
        )
        .order_by(MonitorDeploymentModel.template_id, MonitorDeploymentModel.array_id)
    )
    rows = result.all()

    out: List[dict] = []
    for deployment, template, assignment in rows:
        last_alert = (
            await db.execute(
                select(func.max(AlertModel.timestamp)).where(
                    AlertModel.array_id == deployment.array_id,
                    AlertModel.details.like(
                        f'%"template_id": {deployment.template_id}%'
                    ),
                )
            )
        ).scalar()
        out.append({
            "template_id": deployment.template_id,
            "template_name": template.name if template else "",
            "array_id": deployment.array_id,
            "deployed_by": (assignment.created_by if assignment else "") or "",
            "version": deployment.desired_version,
            "status": deployment.status,
            "confirmed_at": deployment.confirmed_at.isoformat() if deployment.confirmed_at else None,
            "last_alert_at": last_alert.isoformat() if last_alert else None,
        })
    return out


async def _deploy_plans(plans: dict) -> List[dict]:
    ssh_pool = get_ssh_pool()
    config = get_config()
    semaphore = asyncio.Semaphore(5)

    async def deploy_one(array_id: str) -> dict:
        conn = ssh_pool.get_connection(array_id)
        if not conn or not conn.is_connected():
            return {
                "array_id": array_id,
                "ok": False,
                "status": "failed",
                "error": "Array not connected",
            }
        try:
            from ..core.agent_deployer import AgentDeployer
            deployer = AgentDeployer(conn, config)
            async with semaphore:
                result = await asyncio.to_thread(
                    deploy_agent_config,
                    conn,
                    plans[array_id],
                    deployer.restart_agent,
                    6,
                    1.0,
                )
            return {"array_id": array_id, **result}
        except Exception as exc:
            logger.exception("Deploy failed for %s", array_id)
            return {
                "array_id": array_id,
                "ok": False,
                "status": "failed",
                "error": str(exc),
            }

    return await asyncio.gather(*(deploy_one(array_id) for array_id in plans))


async def _record_results(
    db: AsyncSession,
    assignments: list,
    resolved: dict,
    results: List[dict],
) -> None:
    result_map = {item["array_id"]: item for item in results}
    now = datetime.now()
    for array_id, matching_assignments in resolved.items():
        deploy_result = result_map[array_id]
        for assignment in matching_assignments:
            query = await db.execute(
                select(MonitorDeploymentModel).where(
                    MonitorDeploymentModel.assignment_id == assignment.id,
                    MonitorDeploymentModel.array_id == array_id,
                )
            )
            row = query.scalar_one_or_none()
            if row is None:
                row = MonitorDeploymentModel(
                    assignment_id=assignment.id,
                    template_id=assignment.template_id,
                    array_id=array_id,
                    desired_version=assignment.desired_version,
                )
                db.add(row)
            row.desired_version = assignment.desired_version
            row.desired_hash = deploy_result.get("desired_hash", "")
            row.loaded_hash = deploy_result.get("loaded_hash", "")
            removal_confirmed = not assignment.is_enabled and deploy_result.get("ok")
            row.status = "removed" if removal_confirmed else deploy_result.get("status", "failed")
            row.status_message = (
                "Agent 已确认移除观察点"
                if removal_confirmed
                else deploy_result.get("error", "")
            )
            row.attempted_at = now
            row.confirmed_at = now if row.status == "active" else None
    for assignment in assignments:
        states = [
            result_map[array_id]
            for array_id, matching in resolved.items()
            if assignment in matching
        ]
        successful = states and all(item.get("ok") for item in states)
        assignment.status = (
            "removed" if successful and not assignment.is_enabled
            else "active" if successful
            else "degraded"
        )
        assignment.status_message = (
            "Agent 已确认移除观察点" if assignment.status == "removed"
            else "" if assignment.status == "active"
            else "部分阵列未确认加载"
        )
    await db.commit()


@router.post("/deploy")
async def deploy_templates(
    body: DeployRequest,
    user: UserAccountModel = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.template_ids:
        raise HTTPException(status_code=400, detail="template_ids required")
    if body.target_type not in {"tag", "array"}:
        raise HTTPException(status_code=400, detail="target_type must be 'tag' or 'array'")
    result = await db.execute(
        select(MonitorTemplateModel).where(
            MonitorTemplateModel.id.in_(body.template_ids),
            MonitorTemplateModel.is_enabled.is_(True),
        )
    )
    templates = result.scalars().all()
    if len(templates) != len(set(body.template_ids)):
        raise HTTPException(status_code=400, detail="No enabled templates found")

    # Deploy requires the template to be VISIBLE to the caller (same rule as
    # list): otherwise a user could deploy another team's draft by guessing ids.
    from .monitor_templates import _is_visible
    from ..core.monitor_template_service import get_user_team_ids
    team_ids = {str(t) for t in await get_user_team_ids(db, user.id)} if user.id else set()
    invisible = [t.id for t in templates if not _is_visible(t, user, team_ids)]
    if invisible:
        raise HTTPException(
            status_code=403,
            detail=f"Templates not visible to you: {invisible}",
        )
    previous_result = await db.execute(
        select(MonitorAssignmentModel).where(
            MonitorAssignmentModel.template_id.in_(body.template_ids)
        )
    )
    previous_assignments = previous_result.scalars().all()
    previous_resolved = await resolve_assignment_arrays(db, previous_assignments)
    previous_deployment_result = await db.execute(
        select(MonitorDeploymentModel).where(
            MonitorDeploymentModel.template_id.in_(body.template_ids)
        )
    )
    previous_deployments = previous_deployment_result.scalars().all()

    assignments = []
    for template in templates:
        assignments.extend(await replace_assignments(
            db, template, body.target_type, body.target_ids, user.nickname or ""
        ))
    active_resolved = await resolve_assignment_arrays(db, assignments)
    current_result = await db.execute(
        select(MonitorAssignmentModel).where(
            MonitorAssignmentModel.template_id.in_(body.template_ids)
        )
    )
    current_assignments = current_result.scalars().all()
    assignment_by_id = {item.id: item for item in current_assignments}
    resolved = {array_id: list(rows) for array_id, rows in previous_resolved.items()}
    for array_id, rows in active_resolved.items():
        bucket = resolved.setdefault(array_id, [])
        bucket.extend(row for row in rows if row not in bucket)
    for deployment in previous_deployments:
        assignment = assignment_by_id.get(deployment.assignment_id)
        if assignment:
            bucket = resolved.setdefault(deployment.array_id, [])
            if assignment not in bucket:
                bucket.append(assignment)
    if not resolved:
        raise HTTPException(status_code=400, detail="No arrays found for target")
    for assignment in current_assignments:
        assignment.status = "deploying"
        assignment.status_message = (
            "正在移除并等待 Agent 加载回执"
            if not assignment.is_enabled
            else "正在下发并等待 Agent 加载回执"
        )
    await db.commit()
    plans = {
        array_id: await desired_monitors_for_array(db, array_id)
        for array_id in resolved
    }
    results = await _deploy_plans(plans)
    await _record_results(db, current_assignments, resolved, results)
    return {"results": results}
