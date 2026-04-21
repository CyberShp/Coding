"""
Custom query API endpoints.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.query_engine import QueryEngine, BUILTIN_TEMPLATES
from ..core.ssh_pool import get_ssh_pool, SSHPool
from ..db.database import get_db
from ..models.array import ArrayModel
from ..models.query import (
    QueryTask, QueryResult, QueryRule, QueryTemplateModel,
    QueryTemplateCreate, QueryTemplateResponse, RuleType, ExtractField
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])


@router.post("/execute", response_model=QueryResult)
async def execute_query(
    task: QueryTask,
    db: AsyncSession = Depends(get_db),
    ssh_pool: SSHPool = Depends(get_ssh_pool),
):
    """
    Execute a custom query on target arrays.
    
    The query task includes:
    - commands: List of commands to execute
    - target_arrays: Array IDs to run against
    - rule: Matching rule for results
    """
    # Get array names
    result = await db.execute(select(ArrayModel))
    arrays = {a.array_id: a.name for a in result.scalars().all()}
    
    # Validate target arrays
    for array_id in task.target_arrays:
        if array_id not in arrays:
            raise HTTPException(
                status_code=404,
                detail=f"Array {array_id} not found"
            )
        
        conn = ssh_pool.get_connection(array_id)
        if not conn or not conn.is_connected():
            raise HTTPException(
                status_code=400,
                detail=f"Array {array_id} is not connected"
            )
    
    # execute_query performs synchronous SSH I/O; run in threadpool
    # to avoid blocking the event loop (which breaks concurrent async DB ops).
    engine = QueryEngine(ssh_pool)
    loop = asyncio.get_running_loop()
    result = await asyncio.wait_for(
        loop.run_in_executor(None, engine.execute_query, task, arrays),
        timeout=120,
    )
    
    return result


@router.post("/test-pattern")
async def test_pattern(
    pattern: str = Body(..., embed=True),
    test_text: str = Body(..., embed=True),
    rule_type: str = Body("valid_match", embed=True),
    expect_match: bool = Body(True, embed=True),
):
    """
    Test a regex pattern against sample text.
    
    Useful for validating patterns before creating queries.
    """
    engine = QueryEngine()
    
    try:
        rule_type_enum = RuleType(rule_type)
    except ValueError:
        rule_type_enum = RuleType.VALID_MATCH
    
    result = engine.test_pattern(
        pattern=pattern,
        test_text=test_text,
        rule_type=rule_type_enum,
        expect_match=expect_match,
    )
    
    return result


@router.post("/validate-pattern")
async def validate_pattern(
    pattern: str = Body(..., embed=True),
):
    """Validate a regex pattern"""
    engine = QueryEngine()
    is_valid, error = engine.validate_pattern(pattern)
    
    return {
        "valid": is_valid,
        "error": error,
    }


@router.get("/templates", response_model=List[QueryTemplateResponse])
async def list_templates(
    include_builtin: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """Get all query templates"""
    templates = []
    
    # Add built-in templates
    if include_builtin:
        for i, t in enumerate(BUILTIN_TEMPLATES):
            templates.append(QueryTemplateResponse(
                id=-(i + 1),  # Negative IDs for built-in
                name=t['name'],
                description=t['description'],
                commands=t['commands'],
                rule=QueryRule(
                    rule_type=RuleType(t['rule']['rule_type']),
                    pattern=t['rule']['pattern'],
                    expect_match=t['rule']['expect_match'],
                    extract_fields=[
                        ExtractField(**f) for f in t['rule'].get('extract_fields', [])
                    ],
                ),
                is_builtin=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ))
    
    # Add user templates from database
    result = await db.execute(select(QueryTemplateModel))
    for t in result.scalars().all():
        import json
        templates.append(QueryTemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            commands=json.loads(t.commands),
            rule=QueryRule(
                rule_type=RuleType(t.rule_type),
                pattern=t.pattern,
                expect_match=t.expect_match,
                extract_fields=[
                    ExtractField(**f) for f in json.loads(t.extract_fields)
                ],
            ),
            is_builtin=False,
            created_at=t.created_at,
            updated_at=t.updated_at,
        ))
    
    return templates


@router.post("/templates", response_model=QueryTemplateResponse)
async def create_template(
    template: QueryTemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new query template"""
    import json
    
    db_template = QueryTemplateModel(
        name=template.name,
        description=template.description,
        commands=json.dumps(template.commands),
        rule_type=template.rule.rule_type.value,
        pattern=template.rule.pattern,
        expect_match=template.rule.expect_match,
        extract_fields=json.dumps([f.dict() for f in template.rule.extract_fields]),
        is_builtin=False,
        auto_monitor=template.auto_monitor,
        monitor_interval=template.monitor_interval,
        monitor_arrays=json.dumps(template.monitor_arrays),
        alert_on_mismatch=template.alert_on_mismatch,
    )
    
    db.add(db_template)
    await db.commit()
    await db.refresh(db_template)
    
    return QueryTemplateResponse(
        id=db_template.id,
        name=db_template.name,
        description=db_template.description,
        commands=json.loads(db_template.commands),
        rule=template.rule,
        is_builtin=False,
        auto_monitor=db_template.auto_monitor,
        monitor_interval=db_template.monitor_interval,
        monitor_arrays=json.loads(db_template.monitor_arrays or "[]"),
        alert_on_mismatch=db_template.alert_on_mismatch,
        created_at=db_template.created_at,
        updated_at=db_template.updated_at,
    )


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a query template"""
    if template_id < 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete built-in templates"
        )
    
    result = await db.execute(
        select(QueryTemplateModel).where(QueryTemplateModel.id == template_id)
    )
    template = result.scalar()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    await db.delete(template)
    await db.commit()
    
    return {"status": "deleted"}


# ── F201: Natural Language Query ─────────────────────────────

import re

# Strict table whitelist — only these tables may appear in FROM/JOIN
_NL_ALLOWED_TABLES = {"alerts", "arrays", "task_sessions", "baseline_stats", "causal_rules"}

# Column blacklist — sensitive columns that must never appear in SQL
_NL_BLOCKED_COLUMNS = {
    "saved_password", "key_path", "api_key", "password",
    "token", "secret", "credential",
}

# Statement-level forbidden keywords
_NL_FORBIDDEN = {"insert", "update", "delete", "drop", "alter", "create", "replace", "attach", "detach", "pragma"}

# Structural keywords that enable bypass via nested queries
_NL_FORBIDDEN_STRUCTURAL = {"union", "intersect", "except"}

# Max rows returned by any NL query
_NL_MAX_ROWS = 200


def _extract_table_refs(sql: str) -> set:
    """
    Extract table names from FROM/JOIN clauses including comma-separated
    old-style joins: FROM table1 a, table2 b, table3 c
    """
    normalized = re.sub(r'\s+', ' ', sql.strip().lower())
    tables = set()

    # Step 1: Extract FROM clause content (between FROM and WHERE/GROUP/ORDER/HAVING/LIMIT/JOIN or end)
    from_match = re.search(
        r'\bfrom\s+(.*?)(?:\b(?:where|group|order|having|limit|union)\b|$)',
        normalized,
    )
    if from_match:
        from_clause = from_match.group(1)
        # Split by JOIN first to handle mixed syntax: FROM a, b JOIN c
        parts = re.split(r'\bjoin\b', from_clause)
        # First part is the comma-separated FROM list
        for item in parts[0].split(','):
            item = item.strip()
            if item:
                # First word is the table name (rest is alias/ON clause)
                table = item.split()[0].strip()
                if table and re.match(r'^\w+$', table):
                    tables.add(table)
        # Remaining parts are JOIN targets
        for part in parts[1:]:
            part = part.strip()
            if part:
                table = part.split()[0].strip()
                if table and re.match(r'^\w+$', table):
                    tables.add(table)

    # Step 2: Also catch any standalone JOIN (handles subselects, multiple JOINs)
    for m in re.finditer(r'\bjoin\s+(\w+)', normalized):
        tables.add(m.group(1))

    return tables


def _strip_string_literals(sql: str) -> str:
    """
    Replace all single- and double-quoted string literals with empty
    placeholders so keyword scanning doesn't match content inside strings.
    e.g. WHERE message LIKE '%drop%' → WHERE message LIKE ''
    """
    result = re.sub(r"'[^']*'", "''", sql)
    result = re.sub(r'"[^"]*"', '""', result)
    return result


def _validate_nl_sql(sql: str) -> Optional[str]:
    """
    Validate LLM-generated SQL. Returns error message or None if OK.

    Security layers:
    1. Must be SELECT only
    2. No forbidden keywords (INSERT/UPDATE/DELETE/DROP/etc)
    3. No wildcard SELECT (*, table.*) — must name columns explicitly
    4. All referenced tables must be in whitelist (parsed from FROM/JOIN)
    5. No sensitive column names anywhere in query
    """
    normalized = sql.strip().rstrip(";").lower()

    # Strip string literals for keyword scanning to avoid false positives
    # like WHERE message LIKE '%drop%' being flagged as DROP
    stripped = _strip_string_literals(normalized)

    # Must be a SELECT
    if not normalized.startswith("select"):
        return "只允许 SELECT 查询"

    # Check for forbidden keywords (on stripped text)
    for word in _NL_FORBIDDEN:
        if re.search(rf'\b{word}\b', stripped):
            return f"禁止使用 {word.upper()} 语句"

    # Block subqueries — only one SELECT allowed (no nested SELECT)
    select_count = len(re.findall(r'\bselect\b', stripped))
    if select_count > 1:
        return "禁止使用子查询 — 只允许单层 SELECT"

    # Block set operations (UNION/INTERSECT/EXCEPT)
    for word in _NL_FORBIDDEN_STRUCTURAL:
        if re.search(rf'\b{word}\b', stripped):
            return f"禁止使用 {word.upper()} — 只允许单层 SELECT"

    # Block SELECT * and table.* — forces explicit column naming
    if re.search(r'\bselect\s+\*', normalized) or re.search(r'\w+\.\*', normalized):
        return "禁止使用 SELECT * — 请指定具体列名"

    # Extract and validate ALL table references (use normalized — FROM/JOIN won't have string content)
    tables = _extract_table_refs(normalized)
    if not tables:
        return "无法识别查询的表"
    disallowed = tables - _NL_ALLOWED_TABLES
    if disallowed:
        return f"禁止查询的表: {', '.join(sorted(disallowed))}"

    # Block sensitive column references (on stripped text)
    for col in _NL_BLOCKED_COLUMNS:
        if re.search(rf'\b{col}\b', stripped):
            return f"禁止访问敏感字段: {col}"

    return None


def _enforce_limit(sql: str) -> str:
    """
    Ensure SQL has a LIMIT clause. If missing, append one.
    If present but > _NL_MAX_ROWS, cap it.
    """
    normalized = sql.strip().rstrip(";").lower()
    limit_match = re.search(r'\blimit\s+(\d+)', normalized)
    if not limit_match:
        return sql.rstrip().rstrip(";") + f" LIMIT {_NL_MAX_ROWS}"
    limit_val = int(limit_match.group(1))
    if limit_val > _NL_MAX_ROWS:
        # Replace the limit value
        return sql[:limit_match.start(1)] + str(_NL_MAX_ROWS) + sql[limit_match.end(1):]
    return sql


@router.post("/nl")
async def natural_language_query(
    question: str = Body(..., embed=True, min_length=2, max_length=500),
    db: AsyncSession = Depends(get_db),
):
    """
    F201: Natural Language Query.
    Translates a natural language question to SQL, executes it read-only,
    and returns structured results.
    """
    from ..core.ai_service import nl_to_sql, is_ai_available
    from sqlalchemy import text

    if not is_ai_available():
        raise HTTPException(status_code=503, detail="AI 服务未启用，无法使用自然语言查询")

    # Step 1: Translate NL → SQL
    sql = await nl_to_sql(question)
    if not sql:
        raise HTTPException(status_code=422, detail="无法理解该问题，请尝试更具体的表述")

    # Step 2: Validate generated SQL
    error = _validate_nl_sql(sql)
    if error:
        logger.warning("NL query validation failed: %s — SQL: %s", error, sql)
        raise HTTPException(status_code=400, detail=f"生成的查询不安全: {error}")

    # Step 3: Enforce LIMIT cap
    sql = _enforce_limit(sql)

    # Step 4: Execute read-only
    try:
        result = await db.execute(text(sql))
        rows = result.fetchall()
        columns = list(result.keys()) if rows else []

        # Convert to list of dicts
        data = [dict(zip(columns, row)) for row in rows]

        return {
            "question": question,
            "sql": sql,
            "columns": columns,
            "data": data,
            "row_count": len(data),
        }
    except Exception as e:
        logger.warning("NL query execution failed: %s — SQL: %s", e, sql)
        raise HTTPException(status_code=400, detail=f"查询执行失败: {str(e)}")
