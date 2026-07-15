"""Persistence helpers for versioned custom observer templates."""

import hashlib
import json
import re
import secrets
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.array import ArrayModel
from ..models.tag import ArrayTagModel
from ..models.monitor_template import (
    MonitorAssignmentModel,
    MonitorTemplateModel,
    MonitorTemplateVersionModel,
)


CONFIG_FIELDS = (
    "name", "description", "category", "command", "command_type", "interval",
    "timeout", "match_type", "match_expression", "match_condition",
    "match_threshold", "alert_level", "alert_message_template", "cooldown",
    "consecutive_threshold", "is_enabled", "visibility", "team_scope",
)
V2_STRATEGIES = {"pipe", "kv", "json", "table", "lines", "diff", "exit_code"}


def normalize_extraction_strategy(
    match_type: str,
    match_expression: str,
) -> Tuple[str, Dict[str, Any]]:
    """Convert persisted legacy extraction settings to the Agent v2 contract."""
    strategy = match_type or "lines"
    expression = match_expression or ""
    if strategy in V2_STRATEGIES:
        try:
            config = json.loads(expression or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
        return strategy, config if isinstance(config, dict) else {}
    if strategy == "regex":
        return "lines", {"pattern": expression or ".", "mode": "first"}
    if strategy == "jsonpath":
        return "json", {"path": expression}
    if strategy == "contains":
        return "lines", {"pattern": re.escape(expression), "mode": "count"}
    return "lines", {"pattern": expression or ".", "mode": "first"}


def template_snapshot(template: MonitorTemplateModel) -> Dict[str, Any]:
    return {field: getattr(template, field) for field in CONFIG_FIELDS}


def fingerprint_snapshot(snapshot: Dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_template_identity(template: MonitorTemplateModel) -> None:
    if not template.template_key:
        template.template_key = "obs_" + secrets.token_hex(12)
    if not template.version:
        template.version = 1


def add_version_snapshot(
    db: AsyncSession,
    template: MonitorTemplateModel,
    created_by: str,
) -> MonitorTemplateVersionModel:
    ensure_template_identity(template)
    snapshot = template_snapshot(template)
    fingerprint = fingerprint_snapshot(snapshot)
    template.config_fingerprint = fingerprint
    version = MonitorTemplateVersionModel(
        template_id=template.id,
        version=template.version,
        snapshot=json.dumps(snapshot, ensure_ascii=False),
        config_fingerprint=fingerprint,
        created_by=created_by,
    )
    db.add(version)
    return version


def template_to_agent_config(template: MonitorTemplateModel) -> Dict[str, Any]:
    strategy, strategy_config = normalize_extraction_strategy(
        template.match_type,
        template.match_expression,
    )
    return {
        "name": template.name,
        "template_id": template.id,
        "template_key": template.template_key,
        "template_version": template.version,
        "visibility": template.visibility or "team",
        "owner_id": template.created_by or "",
        "team_scope": template.team_scope or "",
        "command": template.command,
        "command_type": template.command_type or "shell",
        "interval": template.interval or 60,
        "timeout": template.timeout or 30,
        "strategy": strategy,
        "strategy_config": strategy_config,
        "match_type": strategy,
        "match_expression": json.dumps(strategy_config, ensure_ascii=False),
        "match_condition": template.match_condition or "found",
        "match_threshold": template.match_threshold,
        "alert_level": template.alert_level or "warning",
        "alert_message_template": template.alert_message_template or "",
        "cooldown": template.cooldown if template.cooldown is not None else 300,
        "consecutive_threshold": (
            template.consecutive_threshold
            if template.consecutive_threshold is not None else 1
        ),
    }


async def upsert_assignments(
    db: AsyncSession,
    template: MonitorTemplateModel,
    target_type: str,
    target_ids: Iterable[int],
    created_by: str,
) -> List[MonitorAssignmentModel]:
    ids = sorted(set(int(item) for item in target_ids))
    result = await db.execute(
        select(MonitorAssignmentModel).where(
            MonitorAssignmentModel.template_id == template.id,
            MonitorAssignmentModel.target_type == target_type,
            MonitorAssignmentModel.target_id.in_(ids),
        )
    )
    existing = {item.target_id: item for item in result.scalars().all()}
    rows = []
    for target_id in ids:
        row = existing.get(target_id)
        if row is None:
            row = MonitorAssignmentModel(
                template_id=template.id,
                target_type=target_type,
                target_id=target_id,
                desired_version=template.version,
                created_by=created_by,
            )
            db.add(row)
        else:
            row.desired_version = template.version
            row.is_enabled = True
            if row.status == "active":
                row.status = "pending"
        rows.append(row)
    await db.flush()
    return rows


async def replace_assignments(
    db: AsyncSession,
    template: MonitorTemplateModel,
    target_type: str,
    target_ids: Iterable[int],
    created_by: str,
) -> List[MonitorAssignmentModel]:
    """Make the supplied targets the complete desired assignment set."""
    ids = sorted(set(int(item) for item in target_ids))
    result = await db.execute(
        select(MonitorAssignmentModel).where(
            MonitorAssignmentModel.template_id == template.id
        )
    )
    for row in result.scalars().all():
        if row.target_type != target_type or row.target_id not in ids:
            row.is_enabled = False
            row.desired_version = template.version
            row.status = "pending"
            row.status_message = "等待从目标阵列移除"
    await db.flush()
    return await upsert_assignments(db, template, target_type, ids, created_by)


async def resolve_assignment_arrays(
    db: AsyncSession,
    assignments: Iterable[MonitorAssignmentModel],
) -> Dict[str, List[MonitorAssignmentModel]]:
    assignments = list(assignments)
    array_targets = {a.target_id for a in assignments if a.target_type == "array"}
    tag_targets = {a.target_id for a in assignments if a.target_type == "tag"}
    linked_tags: Dict[str, set[int]] = {}
    if tag_targets:
        tag_result = await db.execute(
            select(ArrayTagModel.array_id, ArrayTagModel.tag_id).where(
                ArrayTagModel.tag_id.in_(tag_targets)
            )
        )
        for array_id, tag_id in tag_result.all():
            linked_tags.setdefault(array_id, set()).add(tag_id)

    clauses = []
    if array_targets:
        clauses.append(ArrayModel.id.in_(array_targets))
    if tag_targets:
        clauses.append(ArrayModel.tag_id.in_(tag_targets))
    if linked_tags:
        clauses.append(ArrayModel.array_id.in_(linked_tags))
    if not clauses:
        return {}
    result = await db.execute(select(ArrayModel).where(or_(*clauses)))
    resolved: Dict[str, List[MonitorAssignmentModel]] = {}
    for array in result.scalars().all():
        array_tag_ids = linked_tags.get(array.array_id, set())
        if array.tag_id is not None:
            array_tag_ids.add(array.tag_id)
        matches = [
            assignment for assignment in assignments
            if (
                assignment.target_type == "array" and assignment.target_id == array.id
            ) or (
                assignment.target_type == "tag" and assignment.target_id in array_tag_ids
            )
        ]
        if array.array_id and matches:
            resolved[array.array_id] = matches
    return resolved


async def desired_monitors_for_array(
    db: AsyncSession,
    array_id: str,
) -> List[Dict[str, Any]]:
    array_result = await db.execute(select(ArrayModel).where(ArrayModel.array_id == array_id))
    array = array_result.scalar_one_or_none()
    if not array:
        return []
    tag_result = await db.execute(
        select(ArrayTagModel.tag_id).where(ArrayTagModel.array_id == array.array_id)
    )
    tag_ids = set(tag_result.scalars().all())
    if array.tag_id is not None:
        tag_ids.add(array.tag_id)
    clauses = [
        (MonitorAssignmentModel.target_type == "array")
        & (MonitorAssignmentModel.target_id == array.id)
    ]
    if tag_ids:
        clauses.append(
            (MonitorAssignmentModel.target_type == "tag")
            & (MonitorAssignmentModel.target_id.in_(tag_ids))
        )
    result = await db.execute(
        select(MonitorTemplateModel)
        .join(
            MonitorAssignmentModel,
            MonitorAssignmentModel.template_id == MonitorTemplateModel.id,
        )
        .where(
            MonitorAssignmentModel.is_enabled.is_(True),
            MonitorTemplateModel.is_enabled.is_(True),
            or_(*clauses),
        )
        .order_by(MonitorTemplateModel.id)
    )
    seen = set()
    monitors = []
    for template in result.scalars().all():
        if template.id in seen:
            continue
        seen.add(template.id)
        monitors.append(template_to_agent_config(template))
    return monitors
