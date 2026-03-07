"""Card inventory API - cards synced from connected arrays."""

import json
import logging
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

    ssh_pool = get_ssh_pool()
    synced = 0
    errors = []

    result = await db.execute(select(ArrayModel))
    arrays = result.scalars().all()

    for array in arrays:
        conn = ssh_pool.get_connection(array.array_id)
        if not conn:
            continue

        try:
            cmd = "anytest intfboardallinfo"
            stdin_, stdout_, stderr_ = conn.exec_command(cmd, timeout=15)
            output = stdout_.read().decode("utf-8", errors="replace")
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
            errors.append(f"{array.name} ({array.host}): {str(e)}")
            logger.warning("Card sync failed for %s: %s", array.name, e)

    return CardSyncResult(synced=synced, errors=errors)


def _parse_card_output(output: str) -> list[dict]:
    """Parse the output of 'anytest intfboardallinfo' command.

    Expected format - lines with key:value pairs per card section,
    separated by blank lines or dashes.
    """
    cards = []
    current: dict = {}
    raw: dict = {}

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("==="):
            if current:
                current["raw_fields"] = raw
                cards.append(current)
                current = {}
                raw = {}
            continue

        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            raw[key] = value
            key_lower = key.lower().replace(" ", "_")

            if key_lower in ("boardid", "board_id"):
                current["board_id"] = value
            elif key_lower in ("cardno", "card_no"):
                current["card_no"] = value
            elif key_lower in ("healthstate", "health_state"):
                current["health_state"] = value
            elif key_lower in ("runningstate", "running_state"):
                current["running_state"] = value
            elif key_lower == "model":
                current["model"] = value

    if current:
        current["raw_fields"] = raw
        cards.append(current)

    return cards
