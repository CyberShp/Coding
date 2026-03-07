"""Card inventory API - global card catalog with fuzzy search.

Phase 1: Manual CRUD (current). TODO Phase 2: GET /api/cards from array sync,
multi-keyword AND search on model/board_id/card_no/array_name per plan Feature 10.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.card_inventory import (
    CardInventoryModel,
    CardInventoryCreate,
    CardInventoryUpdate,
    CardInventoryResponse,
    DEVICE_TYPES,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/card-inventory", tags=["card-inventory"])


@router.get("/device-types", response_model=List[str])
async def list_device_types():
    """Get predefined device types."""
    return DEVICE_TYPES


@router.get("", response_model=List[CardInventoryResponse])
async def list_cards(
    q: Optional[str] = Query(None, description="Fuzzy search on name, model, description"),
    device_type: Optional[str] = Query(None, description="Filter by device type"),
    db: AsyncSession = Depends(get_db),
):
    """List card inventory with optional fuzzy search."""
    query = select(CardInventoryModel).order_by(CardInventoryModel.device_type, CardInventoryModel.name)
    if q and q.strip():
        # Multi-keyword AND: split by spaces, each keyword must match (plan Feature 10)
        from sqlalchemy import and_
        keywords = [k.strip() for k in q.strip().split() if k.strip()]
        for kw in keywords:
            pattern = f"%{kw}%"
            query = query.where(
                or_(
                    CardInventoryModel.name.ilike(pattern),
                    CardInventoryModel.model.ilike(pattern),
                    CardInventoryModel.description.ilike(pattern),
                )
            )
    if device_type and device_type.strip():
        query = query.where(CardInventoryModel.device_type == device_type.strip())

    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=CardInventoryResponse, status_code=status.HTTP_201_CREATED)
async def create_card(
    card: CardInventoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new card inventory entry."""
    db_card = CardInventoryModel(
        name=card.name,
        device_type=card.device_type,
        model=card.model,
        description=card.description,
    )
    db.add(db_card)
    await db.commit()
    await db.refresh(db_card)
    return db_card


@router.get("/{card_id}", response_model=CardInventoryResponse)
async def get_card(
    card_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single card by ID."""
    result = await db.execute(
        select(CardInventoryModel).where(CardInventoryModel.id == card_id)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.put("/{card_id}", response_model=CardInventoryResponse)
async def update_card(
    card_id: int,
    update: CardInventoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a card inventory entry."""
    result = await db.execute(
        select(CardInventoryModel).where(CardInventoryModel.id == card_id)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    for k, v in update.model_dump(exclude_unset=True).items():
        setattr(card, k, v)
    await db.commit()
    await db.refresh(card)
    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    card_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a card inventory entry."""
    result = await db.execute(
        select(CardInventoryModel).where(CardInventoryModel.id == card_id)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    await db.delete(card)
    await db.commit()
