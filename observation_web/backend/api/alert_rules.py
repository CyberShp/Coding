"""
Alert expectation rules API endpoints.

CRUD for alert expectation rules used during test tasks.
"""

import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.alert_rule import (
    AlertExpectationRuleModel,
    AlertRuleCreate,
    AlertRuleUpdate,
    AlertRuleResponse,
    BUILTIN_RULES,
)
from ..core.alert_expectation import get_expectation_engine, init_builtin_rules

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alert-rules", tags=["alert-rules"])


@router.get("", response_model=List[AlertRuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
):
    """Get all alert expectation rules."""
    result = await db.execute(
        select(AlertExpectationRuleModel).order_by(
            AlertExpectationRuleModel.priority,
            AlertExpectationRuleModel.name,
        )
    )
    rules = result.scalars().all()
    return [_to_response(r) for r in rules]


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    rule: AlertRuleCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new alert expectation rule."""
    db_rule = AlertExpectationRuleModel(
        name=rule.name,
        description=rule.description,
        task_types=json.dumps(rule.task_types),
        observer_patterns=json.dumps(rule.observer_patterns),
        level_patterns=json.dumps(rule.level_patterns),
        message_patterns=json.dumps(rule.message_patterns),
        is_enabled=rule.is_enabled,
        is_builtin=False,
        priority=rule.priority,
    )
    db.add(db_rule)
    await db.commit()
    await db.refresh(db_rule)

    # Invalidate cache
    get_expectation_engine().invalidate_cache()

    logger.info(f"Created alert rule: {rule.name}")
    return _to_response(db_rule)


@router.get("/{rule_id}", response_model=AlertRuleResponse)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single alert expectation rule."""
    rule = await db.get(AlertExpectationRuleModel, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _to_response(rule)


@router.put("/{rule_id}", response_model=AlertRuleResponse)
async def update_rule(
    rule_id: int,
    update: AlertRuleUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an alert expectation rule."""
    rule = await db.get(AlertExpectationRuleModel, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = update.model_dump(exclude_unset=True)

    # Convert list fields to JSON
    for field in ['task_types', 'observer_patterns', 'level_patterns', 'message_patterns']:
        if field in update_data and update_data[field] is not None:
            update_data[field] = json.dumps(update_data[field])

    for field, value in update_data.items():
        setattr(rule, field, value)

    await db.commit()
    await db.refresh(rule)

    # Invalidate cache
    get_expectation_engine().invalidate_cache()

    logger.info(f"Updated alert rule: {rule.name}")
    return _to_response(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an alert expectation rule."""
    rule = await db.get(AlertExpectationRuleModel, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if rule.is_builtin:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete built-in rules. Disable them instead."
        )

    await db.delete(rule)
    await db.commit()

    # Invalidate cache
    get_expectation_engine().invalidate_cache()

    logger.info(f"Deleted alert rule: {rule.name}")


@router.post("/{rule_id}/toggle", response_model=AlertRuleResponse)
async def toggle_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Toggle a rule's enabled state."""
    rule = await db.get(AlertExpectationRuleModel, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.is_enabled = not rule.is_enabled
    await db.commit()
    await db.refresh(rule)

    # Invalidate cache
    get_expectation_engine().invalidate_cache()

    logger.info(f"Toggled alert rule {rule.name}: enabled={rule.is_enabled}")
    return _to_response(rule)


@router.post("/init-builtin")
async def init_builtin(
    db: AsyncSession = Depends(get_db),
):
    """Initialize built-in rules."""
    await init_builtin_rules(db)
    return {"message": "Built-in rules initialized", "count": len(BUILTIN_RULES)}


@router.post("/reset-builtin")
async def reset_builtin(
    db: AsyncSession = Depends(get_db),
):
    """Reset built-in rules to defaults."""
    # Delete existing built-in rules
    result = await db.execute(
        select(AlertExpectationRuleModel).where(
            AlertExpectationRuleModel.is_builtin == True
        )
    )
    for rule in result.scalars().all():
        await db.delete(rule)

    await db.commit()

    # Re-create
    await init_builtin_rules(db)

    # Invalidate cache
    get_expectation_engine().invalidate_cache()

    return {"message": "Built-in rules reset", "count": len(BUILTIN_RULES)}


def _to_response(rule: AlertExpectationRuleModel) -> AlertRuleResponse:
    """Convert database model to response."""
    return AlertRuleResponse(
        id=rule.id,
        name=rule.name,
        description=rule.description or "",
        task_types=_parse_json(rule.task_types),
        observer_patterns=_parse_json(rule.observer_patterns),
        level_patterns=_parse_json(rule.level_patterns),
        message_patterns=_parse_json(rule.message_patterns),
        is_enabled=rule.is_enabled,
        is_builtin=rule.is_builtin,
        priority=rule.priority,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _parse_json(value) -> List[str]:
    """Parse JSON string to list."""
    if not value:
        return []
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (json.JSONDecodeError, TypeError):
        return []
