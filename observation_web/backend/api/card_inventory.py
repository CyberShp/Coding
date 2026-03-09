"""Card inventory API - cards synced from connected arrays."""

import json
import logging
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.card_inventory import CardInventoryModel, CardInventoryResponse, CardSyncResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/card-inventory", tags=["card-inventory"])


@router.get("", response_model=List[CardInventoryResponse])
async def list_cards(
    q: Optional[str] = Query(None, description="Multi-keyword fuzzy search"),
    db: AsyncSession = Depends(get_db),
):
    """List card inventory with array info and optional multi-keyword search."""
    sql = text("""
        SELECT
            ci.id, ci.array_id, ci.card_no, ci.board_id,
            ci.health_state, ci.running_state, ci.model,
            ci.raw_fields, ci.last_updated,
            COALESCE(a.name, '') AS array_name,
            COALESCE(a.host, '') AS array_host,
            COALESCE(t1.name, '') AS tag_l1,
            COALESCE(t2.name, '') AS tag_l2
        FROM card_inventory ci
        LEFT JOIN arrays a ON ci.array_id = a.array_id
        LEFT JOIN tags t2 ON a.tag_id = t2.id
        LEFT JOIN tags t1 ON t2.parent_id = t1.id
        ORDER BY ci.array_id, ci.card_no
    """)
    result = await db.execute(sql)
    rows = result.fetchall()

    cards = []
    for r in rows:
        cards.append(CardInventoryResponse(
            id=r.id,
            array_id=r.array_id,
            card_no=r.card_no or "",
            board_id=r.board_id or "",
            health_state=r.health_state or "",
            running_state=r.running_state or "",
            model=r.model or "",
            raw_fields=r.raw_fields or "{}",
            last_updated=r.last_updated,
            array_name=r.array_name or "",
            array_host=r.array_host or "",
            tag_l1=r.tag_l1 or "",
            tag_l2=r.tag_l2 or "",
        ))

    if q and q.strip():
        keywords = [kw.strip().lower() for kw in q.strip().split() if kw.strip()]

        def matches(card):
            searchable = f"{card.model} {card.board_id} {card.card_no} {card.array_name} {card.array_host}".lower()
            return all(kw in searchable for kw in keywords)

        cards = [c for c in cards if matches(c)]

    return cards


@router.get("/last-sync")
async def get_last_sync(db: AsyncSession = Depends(get_db)):
    """Get the timestamp of the most recent card sync."""
    result = await db.execute(
        select(CardInventoryModel.last_updated)
        .order_by(CardInventoryModel.last_updated.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return {"last_sync": row.isoformat() if row else None}


@router.post("/sync", response_model=CardSyncResult)
async def sync_cards(db: AsyncSession = Depends(get_db)):
    """Sync card inventory from all connected arrays using SSH."""
    from ..core.ssh_pool import get_ssh_pool
    from ..models.array import ArrayModel
    from .arrays import _get_array_status

    ssh_pool = get_ssh_pool()
    synced = 0
    errors = []
    start_work_enabled = False

    try:
        from ..models.observer_config import ObserverConfigModel
        cfg = await db.execute(
            select(ObserverConfigModel).where(ObserverConfigModel.observer_name == "start_work")
        )
        row = cfg.scalar_one_or_none()
        start_work_enabled = bool(row.enabled) if row is not None else False
    except Exception:
        start_work_enabled = False

    result = await db.execute(select(ArrayModel))
    arrays = result.scalars().all()

    for array in arrays:
        conn = ssh_pool.get_connection(array.array_id)
        if not conn or not conn.is_connected():
            continue
        status_obj = _get_array_status(array.array_id)
        if not getattr(status_obj, "agent_deployed", False):
            continue
        if start_work_enabled:
            started = await _check_start_work(conn)
            if not started:
                errors.append(f"{array.name} ({array.host}): 阵列未开工，跳过卡件同步")
                continue

        try:
            cmd = "anytest intfboardallinfo"
            exit_code, output, err_output = await conn.execute_async(cmd, 15)
            if exit_code != 0:
                errors.append(f"{array.name} ({array.host}): exit={exit_code}, {err_output[:200]}")
                continue
            cards_data = _parse_card_output(output)

            for card_data in cards_data:
                existing = await db.execute(
                    select(CardInventoryModel).where(
                        CardInventoryModel.array_id == array.array_id,
                        CardInventoryModel.card_no == card_data.get("card_no", ""),
                    )
                )
                existing_card = existing.scalar_one_or_none()
                if existing_card:
                    existing_card.board_id = card_data.get("board_id", "")
                    existing_card.health_state = card_data.get("health_state", "")
                    existing_card.running_state = card_data.get("running_state", "")
                    existing_card.model = card_data.get("model", "")
                    existing_card.raw_fields = json.dumps(card_data.get("raw_fields", {}))
                    existing_card.last_updated = datetime.now()
                else:
                    db.add(CardInventoryModel(
                        array_id=array.array_id,
                        card_no=card_data.get("card_no", ""),
                        board_id=card_data.get("board_id", ""),
                        health_state=card_data.get("health_state", ""),
                        running_state=card_data.get("running_state", ""),
                        model=card_data.get("model", ""),
                        raw_fields=json.dumps(card_data.get("raw_fields", {})),
                        last_updated=datetime.now(),
                    ))
                synced += 1

            await db.commit()
        except Exception as e:
            await db.rollback()
            errors.append(f"{array.name} ({array.host}): {str(e)}")
            logger.warning("Card sync failed for %s: %s", array.name, e)

    return CardSyncResult(synced=synced, errors=errors)


# Regex for agent-style output: "No001  BoardId: xxxx" (card prefix + field: value)
_CARD_NO_PATTERN = re.compile(r"(No\d+)", re.IGNORECASE)
_SEPARATOR_PATTERN = re.compile(r"-{3,}")
_FIELD_PATTERN_TEMPLATE = r"\b{keyword}\b\s*[=:\s]+\s*(\S+)"
_RE_BOARD_ID = re.compile(_FIELD_PATTERN_TEMPLATE.format(keyword="BoardId"), re.IGNORECASE)
_RE_CARD_NO = re.compile(_FIELD_PATTERN_TEMPLATE.format(keyword="CardNo"), re.IGNORECASE)
_RE_RUNNING = re.compile(_FIELD_PATTERN_TEMPLATE.format(keyword="RunningState"), re.IGNORECASE)
_RE_HEALTH = re.compile(_FIELD_PATTERN_TEMPLATE.format(keyword="HealthState"), re.IGNORECASE)
_RE_MODEL = re.compile(_FIELD_PATTERN_TEMPLATE.format(keyword="Model"), re.IGNORECASE)
_INVALID_MODEL_VALUES = {"undefined", "undefine", "none", "null", "n/a"}
_START_WORK_LINE_RE = re.compile(r"^\s*[A-Za-z0-9_]+\s*[:：]\s*([0-9]+)\s*$")


def _parse_card_output(output: str) -> list[dict]:
    """Parse the output of 'anytest intfboardallinfo' command.

    Supports two formats:
    1. Agent-style: "No001  BoardId: xxxx", "No001  RunningState: RUNNING", blocks separated by ---
    2. Legacy: "BoardId: xxxx", "CardNo: No001", same separators.
    """
    blocks = _SEPARATOR_PATTERN.split(output)
    cards = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        card_no_match = _CARD_NO_PATTERN.search(block)
        card_no = card_no_match.group(1) if card_no_match else ""
        fields = {}
        raw = {}

        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Collect key:value for raw_fields
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                key_clean = re.sub(r"^No\d+\s+", "", key, flags=re.IGNORECASE).strip() or key
                raw[key_clean] = value

            # Extract fields via regex (handles "No001  BoardId: xxxx")
            m = _RE_BOARD_ID.search(line)
            if m:
                fields["board_id"] = m.group(1).strip()
            m = _RE_CARD_NO.search(line)
            if m:
                fields["card_no"] = m.group(1).strip()
            m = _RE_RUNNING.search(line)
            if m:
                fields["running_state"] = m.group(1).strip()
            m = _RE_HEALTH.search(line)
            if m:
                fields["health_state"] = m.group(1).strip()
            m = _RE_MODEL.search(line)
            if m:
                fields["model"] = m.group(1).strip()

        if not card_no:
            card_no = fields.get("card_no") or (card_no_match.group(1) if card_no_match else "")
        if not card_no:
            card_no = f"Unknown_{len(cards)}"

        current = {
            "card_no": card_no,
            "board_id": fields.get("board_id") or _get_from_raw(raw, "BoardId", "board_id"),
            "running_state": fields.get("running_state") or _get_from_raw(raw, "RunningState", "running_state"),
            "health_state": fields.get("health_state") or _get_from_raw(raw, "HealthState", "health_state"),
            "model": fields.get("model") or _get_from_raw(raw, "Model", "model"),
            "raw_fields": raw,
        }
        model_lower = (current.get("model") or "").strip().lower()
        if model_lower in _INVALID_MODEL_VALUES:
            current["model"] = ""
        cards.append(current)

    return cards


def _get_from_raw(raw: dict, *keys: str) -> str:
    """Get first matching key from raw (case-insensitive)."""
    raw_lower = {k.lower(): v for k, v in raw.items()}
    for k in keys:
        v = raw_lower.get(k.lower())
        if v is not None:
            return v
    return ""


async def _check_start_work(conn) -> bool:
    """Return True if all sysgetstartwork module states are 1."""
    try:
        exit_code, output, _ = await conn.execute_async("anytest sysgetstartwork", 15)
        if exit_code != 0:
            return False
        matched = False
        for line in (output or "").splitlines():
            m = _START_WORK_LINE_RE.match(line.strip())
            if not m:
                continue
            matched = True
            if m.group(1) != "1":
                return False
        return matched
    except Exception:
        return False
