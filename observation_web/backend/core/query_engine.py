"""
Query Engine for custom command execution and pattern matching.

Provides powerful regex matching capabilities for flexible monitoring.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..models.query import (
    QueryRule, QueryTask, QueryResult, QueryResultItem,
    QueryStatus, RuleType, ExtractField
)
from .ssh_pool import SSHPool, get_ssh_pool

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of pattern matching"""
    is_normal: bool
    matched_values: List[str] = field(default_factory=list)
    extracted_fields: Dict[str, List[str]] = field(default_factory=dict)


class QueryEngine:
    """
    Query Engine - Powerful regex matching for custom queries.
    
    Features:
    - Execute commands on multiple arrays
    - Apply flexible matching rules
    - Extract fields using regex
    - Support loop execution
    """
    
    def __init__(self, ssh_pool: Optional[SSHPool] = None):
        self.ssh_pool = ssh_pool or get_ssh_pool()
        self._running_tasks: Dict[str, bool] = {}
    
    def execute_query(
        self,
        task: QueryTask,
        array_names: Dict[str, str],  # array_id -> name mapping
        timeout: int = 30,
    ) -> QueryResult:
        """
        Execute query task on target arrays.
        
        Args:
            task: Query task definition
            array_names: Mapping of array_id to display name
            timeout: Command execution timeout
            
        Returns:
            QueryResult with all results
        """
        task_id = str(uuid.uuid4())[:8]
        started_at = datetime.now()
        
        results: List[QueryResultItem] = []
        
        for array_id in task.target_arrays:
            array_name = array_names.get(array_id, array_id)
            
            for cmd in task.commands:
                start_time = time.time()
                
                # Execute command
                exit_code, stdout, stderr = self.ssh_pool.execute(
                    array_id, cmd, timeout
                )
                
                execution_time = int((time.time() - start_time) * 1000)
                
                if exit_code == -1:
                    # Execution failed
                    results.append(QueryResultItem(
                        array_id=array_id,
                        array_name=array_name,
                        command=cmd,
                        output=stderr or "Execution failed",
                        status=QueryStatus.ERROR,
                        error=stderr,
                        execution_time_ms=execution_time,
                    ))
                    continue
                
                # Apply matching rule
                output = stdout + stderr
                match_result = self._apply_rule(output, task.rule)
                
                status = QueryStatus.OK if match_result.is_normal else QueryStatus.ERROR
                
                results.append(QueryResultItem(
                    array_id=array_id,
                    array_name=array_name,
                    command=cmd,
                    output=output,
                    status=status,
                    matched_values=match_result.matched_values,
                    extracted_fields=match_result.extracted_fields,
                    execution_time_ms=execution_time,
                ))
        
        return QueryResult(
            task_id=task_id,
            task_name=task.name,
            started_at=started_at,
            completed_at=datetime.now(),
            results=results,
            is_loop=task.loop_interval > 0,
        )
    
    def _apply_rule(self, output: str, rule: QueryRule) -> MatchResult:
        """
        Apply matching rule to command output.
        
        Args:
            output: Command output text
            rule: Matching rule to apply
            
        Returns:
            MatchResult with match status and extracted data
        """
        matched_values: List[str] = []
        extracted_fields: Dict[str, List[str]] = {}
        
        # Apply main pattern
        if rule.pattern:
            try:
                pattern = re.compile(rule.pattern, re.MULTILINE | re.IGNORECASE)
                matches = pattern.findall(output)
                
                # Flatten tuple matches
                for match in matches:
                    if isinstance(match, tuple):
                        matched_values.extend(m for m in match if m)
                    else:
                        matched_values.append(match)
                        
            except re.error as e:
                logger.error(f"Invalid regex pattern: {rule.pattern}, error: {e}")
                return MatchResult(is_normal=False)
        
        # Determine if result is normal
        has_match = len(matched_values) > 0
        
        if rule.rule_type == RuleType.VALID_MATCH:
            # Valid match: match found = expect_match result
            is_normal = has_match == rule.expect_match
        elif rule.rule_type == RuleType.INVALID_MATCH:
            # Invalid match: match found = !expect_match result
            is_normal = has_match != rule.expect_match
        else:  # REGEX_EXTRACT
            # Extract mode: always normal if pattern valid
            is_normal = True
        
        # Extract additional fields
        for field_def in rule.extract_fields:
            try:
                field_pattern = re.compile(field_def.pattern, re.MULTILINE | re.IGNORECASE)
                field_matches = field_pattern.findall(output)
                
                # Flatten tuple matches
                flat_matches = []
                for match in field_matches:
                    if isinstance(match, tuple):
                        flat_matches.extend(m for m in match if m)
                    else:
                        flat_matches.append(match)
                
                extracted_fields[field_def.name] = flat_matches
                
            except re.error as e:
                logger.error(f"Invalid field pattern: {field_def.pattern}, error: {e}")
                extracted_fields[field_def.name] = []
        
        return MatchResult(
            is_normal=is_normal,
            matched_values=matched_values,
            extracted_fields=extracted_fields,
        )
    
    def validate_pattern(self, pattern: str) -> Tuple[bool, str]:
        """
        Validate regex pattern.
        
        Returns:
            (is_valid, error_message)
        """
        if not pattern:
            return (False, "Pattern cannot be empty")
        
        try:
            re.compile(pattern)
            return (True, "")
        except re.error as e:
            return (False, str(e))
    
    def test_pattern(
        self,
        pattern: str,
        test_text: str,
        rule_type: RuleType = RuleType.VALID_MATCH,
        expect_match: bool = True,
    ) -> Dict[str, Any]:
        """
        Test a pattern against sample text.
        
        Returns:
            Test results including matches and status
        """
        is_valid, error = self.validate_pattern(pattern)
        if not is_valid:
            return {
                'valid': False,
                'error': error,
                'matches': [],
                'is_normal': False,
            }
        
        rule = QueryRule(
            rule_type=rule_type,
            pattern=pattern,
            expect_match=expect_match,
        )
        
        result = self._apply_rule(test_text, rule)
        
        return {
            'valid': True,
            'error': '',
            'matches': result.matched_values,
            'is_normal': result.is_normal,
        }


# Built-in query templates
BUILTIN_TEMPLATES = [
    {
        'name': '磁盘状态检查',
        'description': '检查磁盘运行状态',
        'commands': ['lsblk -o NAME,SIZE,STATE 2>/dev/null || fdisk -l'],
        'rule': {
            'rule_type': 'valid_match',
            'pattern': r'running|online|active',
            'expect_match': True,
            'extract_fields': [],
        },
    },
    {
        'name': 'RAID 健康检查',
        'description': '检查 RAID 阵列健康状态',
        'commands': ['cat /proc/mdstat 2>/dev/null || echo "No mdstat"'],
        'rule': {
            'rule_type': 'invalid_match',
            'pattern': r'degraded|failed|inactive',
            'expect_match': False,
            'extract_fields': [],
        },
    },
    {
        'name': '服务状态检查',
        'description': '检查系统服务状态',
        'commands': ['systemctl is-active sshd'],
        'rule': {
            'rule_type': 'valid_match',
            'pattern': r'^active$',
            'expect_match': True,
            'extract_fields': [],
        },
    },
    {
        'name': '内存使用情况',
        'description': '提取内存使用信息',
        'commands': ['free -m'],
        'rule': {
            'rule_type': 'regex_extract',
            'pattern': r'Mem:\s+(\d+)\s+(\d+)',
            'expect_match': True,
            'extract_fields': [
                {'name': '总内存(MB)', 'pattern': r'Mem:\s+(\d+)'},
                {'name': '已用(MB)', 'pattern': r'Mem:\s+\d+\s+(\d+)'},
            ],
        },
    },
    {
        'name': 'CPU 负载检查',
        'description': '检查 CPU 负载',
        'commands': ['uptime'],
        'rule': {
            'rule_type': 'regex_extract',
            'pattern': r'load average:\s*([\d.]+)',
            'expect_match': True,
            'extract_fields': [
                {'name': '1分钟负载', 'pattern': r'load average:\s*([\d.]+)'},
                {'name': '5分钟负载', 'pattern': r'load average:\s*[\d.]+,\s*([\d.]+)'},
            ],
        },
    },
    {
        'name': '网络连通性测试',
        'description': '测试网络连通性',
        'commands': ['ping -c 1 -W 2 127.0.0.1'],
        'rule': {
            'rule_type': 'valid_match',
            'pattern': r'1 (packets )?received|1 received',
            'expect_match': True,
            'extract_fields': [],
        },
    },
]
