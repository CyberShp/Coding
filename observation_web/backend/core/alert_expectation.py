"""
Alert expectation evaluation engine.

Evaluates alerts against expectation rules to determine if they are "expected"
based on the current test task type.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert import AlertModel
from ..models.alert_rule import AlertExpectationRuleModel, BUILTIN_RULES
from ..models.task_session import TaskSessionModel

logger = logging.getLogger(__name__)

# Expected values
EXPECTED_UNKNOWN = 0
EXPECTED_YES = 1
EXPECTED_NO = -1


class AlertExpectationEngine:
    """Engine for evaluating alert expectations."""

    def __init__(self):
        self._rules_cache: List[Dict] = []
        self._cache_valid = False

    async def load_rules(self, db: AsyncSession) -> List[Dict]:
        """Load all enabled rules from database."""
        result = await db.execute(
            select(AlertExpectationRuleModel)
            .where(AlertExpectationRuleModel.is_enabled == True)
            .order_by(AlertExpectationRuleModel.priority)
        )
        rules = result.scalars().all()

        self._rules_cache = []
        for rule in rules:
            self._rules_cache.append({
                'id': rule.id,
                'name': rule.name,
                'task_types': self._parse_json(rule.task_types),
                'observer_patterns': self._parse_json(rule.observer_patterns),
                'level_patterns': self._parse_json(rule.level_patterns),
                'message_patterns': self._parse_json(rule.message_patterns),
                'priority': rule.priority,
            })

        self._cache_valid = True
        return self._rules_cache

    def _parse_json(self, value: str) -> List[str]:
        """Parse JSON string to list."""
        if not value:
            return []
        try:
            return json.loads(value) if isinstance(value, str) else value
        except (json.JSONDecodeError, TypeError):
            return []

    def invalidate_cache(self):
        """Invalidate the rules cache."""
        self._cache_valid = False

    async def evaluate_alert(
        self,
        db: AsyncSession,
        alert: AlertModel,
        task_type: Optional[str] = None,
    ) -> Tuple[int, Optional[int]]:
        """
        Evaluate if an alert is expected based on rules.

        Args:
            db: Database session
            alert: Alert to evaluate
            task_type: Current test task type (if any)

        Returns:
            Tuple of (is_expected value, matched rule ID or None)
        """
        if not self._cache_valid:
            await self.load_rules(db)

        if not task_type:
            return EXPECTED_UNKNOWN, None

        for rule in self._rules_cache:
            if self._matches_rule(alert, rule, task_type):
                return EXPECTED_YES, rule['id']

        return EXPECTED_UNKNOWN, None

    def _matches_rule(self, alert: AlertModel, rule: Dict, task_type: str) -> bool:
        """Check if an alert matches a rule."""
        # Check task type
        if rule['task_types'] and task_type not in rule['task_types']:
            return False

        # Check observer pattern
        if rule['observer_patterns']:
            observer_match = False
            for pattern in rule['observer_patterns']:
                if pattern == alert.observer_name or re.search(pattern, alert.observer_name, re.IGNORECASE):
                    observer_match = True
                    break
            if not observer_match:
                return False

        # Check level pattern
        if rule['level_patterns'] and alert.level not in rule['level_patterns']:
            return False

        # Check message pattern
        if rule['message_patterns']:
            message_match = False
            for pattern in rule['message_patterns']:
                try:
                    if re.search(pattern, alert.message or '', re.IGNORECASE):
                        message_match = True
                        break
                except re.error:
                    continue
            if not message_match:
                return False

        return True

    async def evaluate_alerts_batch(
        self,
        db: AsyncSession,
        alerts: List[AlertModel],
        task_type: Optional[str] = None,
    ) -> List[Tuple[int, int, Optional[int]]]:
        """
        Evaluate multiple alerts in batch.

        Returns:
            List of (alert_id, is_expected, matched_rule_id)
        """
        if not self._cache_valid:
            await self.load_rules(db)

        results = []
        for alert in alerts:
            is_expected, rule_id = await self.evaluate_alert(db, alert, task_type)
            results.append((alert.id, is_expected, rule_id))
        return results


async def init_builtin_rules(db: AsyncSession):
    """Initialize built-in rules in database if not present."""
    for rule_data in BUILTIN_RULES:
        # Check if rule already exists
        result = await db.execute(
            select(AlertExpectationRuleModel)
            .where(AlertExpectationRuleModel.name == rule_data['name'])
            .where(AlertExpectationRuleModel.is_builtin == True)
        )
        existing = result.scalar_one_or_none()

        if not existing:
            rule = AlertExpectationRuleModel(
                name=rule_data['name'],
                description=rule_data.get('description', ''),
                task_types=json.dumps(rule_data.get('task_types', [])),
                observer_patterns=json.dumps(rule_data.get('observer_patterns', [])),
                level_patterns=json.dumps(rule_data.get('level_patterns', [])),
                message_patterns=json.dumps(rule_data.get('message_patterns', [])),
                is_builtin=True,
                is_enabled=True,
                priority=50,
            )
            db.add(rule)
            logger.info(f"Created built-in rule: {rule_data['name']}")

    await db.commit()


# Global instance
_engine: Optional[AlertExpectationEngine] = None


def get_expectation_engine() -> AlertExpectationEngine:
    global _engine
    if _engine is None:
        _engine = AlertExpectationEngine()
    return _engine
