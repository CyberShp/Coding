"""
Tag management API endpoints.

Tags are used to organize/group arrays. Each array can belong to one tag.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_db
from ..models.tag import TagModel, TagCreate, TagUpdate, TagResponse, TagWithArrays
from ..models.array import ArrayModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tags", tags=["tags"])


async def _get_tag_or_404(tag_id: int, db: AsyncSession) -> TagModel:
    """Get tag by ID or raise 404"""
    result = await db.execute(
        select(TagModel).where(TagModel.id == tag_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag with id {tag_id} not found"
        )
    return tag


@router.get("", response_model=List[TagResponse])
async def list_tags(
    db: AsyncSession = Depends(get_db),
):
    """
    Get all tags with array counts.
    """
    result = await db.execute(
        select(
            TagModel,
            func.count(ArrayModel.id).label('array_count')
        )
        .outerjoin(ArrayModel, ArrayModel.tag_id == TagModel.id)
        .group_by(TagModel.id)
        .order_by(TagModel.name)
    )
    rows = result.all()

    tags = []
    for tag, count in rows:
        tag_dict = {
            "id": tag.id,
            "name": tag.name,
            "color": tag.color,
            "description": tag.description or "",
            "created_at": tag.created_at,
            "updated_at": tag.updated_at,
            "array_count": count,
        }
        tags.append(TagResponse(**tag_dict))

    return tags


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag: TagCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new tag.
    """
    # Check for duplicate name
    result = await db.execute(
        select(TagModel).where(TagModel.name == tag.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tag with name '{tag.name}' already exists"
        )

    db_tag = TagModel(
        name=tag.name,
        color=tag.color,
        description=tag.description,
    )
    db.add(db_tag)
    await db.commit()
    await db.refresh(db_tag)

    logger.info(f"Created tag: {tag.name}")

    return TagResponse(
        id=db_tag.id,
        name=db_tag.name,
        color=db_tag.color,
        description=db_tag.description or "",
        created_at=db_tag.created_at,
        updated_at=db_tag.updated_at,
        array_count=0,
    )


@router.get("/{tag_id}", response_model=TagWithArrays)
async def get_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Get tag by ID with its arrays.
    """
    tag = await _get_tag_or_404(tag_id, db)

    # Get arrays for this tag
    result = await db.execute(
        select(ArrayModel).where(ArrayModel.tag_id == tag_id)
    )
    arrays = result.scalars().all()

    array_list = [
        {
            "id": a.id,
            "array_id": a.array_id,
            "name": a.name,
            "host": a.host,
            "port": a.port,
            "username": a.username,
        }
        for a in arrays
    ]

    return TagWithArrays(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        description=tag.description or "",
        created_at=tag.created_at,
        updated_at=tag.updated_at,
        array_count=len(arrays),
        arrays=array_list,
    )


@router.get("/{tag_id}/arrays")
async def get_tag_arrays(
    tag_id: int,
    search_ip: Optional[str] = Query(None, description="Filter by IP address"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get arrays belonging to a tag, optionally filtered by IP.
    """
    await _get_tag_or_404(tag_id, db)

    query = select(ArrayModel).where(ArrayModel.tag_id == tag_id)

    if search_ip:
        query = query.where(ArrayModel.host.contains(search_ip))

    result = await db.execute(query)
    arrays = result.scalars().all()

    return {
        "tag_id": tag_id,
        "search_ip": search_ip,
        "count": len(arrays),
        "arrays": [
            {
                "id": a.id,
                "array_id": a.array_id,
                "name": a.name,
                "host": a.host,
                "port": a.port,
                "username": a.username,
                "folder": a.folder,
                "tag_id": a.tag_id,
            }
            for a in arrays
        ],
    }


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: int,
    tag_update: TagUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update a tag.
    """
    tag = await _get_tag_or_404(tag_id, db)

    # Check for duplicate name if name is being changed
    if tag_update.name and tag_update.name != tag.name:
        result = await db.execute(
            select(TagModel).where(TagModel.name == tag_update.name)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tag with name '{tag_update.name}' already exists"
            )

    # Update fields
    update_data = tag_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tag, field, value)

    await db.commit()
    await db.refresh(tag)

    # Get array count
    count_result = await db.execute(
        select(func.count(ArrayModel.id)).where(ArrayModel.tag_id == tag_id)
    )
    array_count = count_result.scalar() or 0

    logger.info(f"Updated tag: {tag.name}")

    return TagResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        description=tag.description or "",
        created_at=tag.created_at,
        updated_at=tag.updated_at,
        array_count=array_count,
    )


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a tag. Arrays with this tag will have tag_id set to NULL.
    """
    tag = await _get_tag_or_404(tag_id, db)

    await db.delete(tag)
    await db.commit()

    logger.info(f"Deleted tag: {tag.name}")


@router.post("/migrate-folders", response_model=dict)
async def migrate_folders_to_tags(
    db: AsyncSession = Depends(get_db),
):
    """
    Migrate existing folder values to tags.

    For each unique non-empty folder value, create a tag and update
    corresponding arrays to use tag_id instead.
    """
    # Get all unique folder values
    result = await db.execute(
        select(ArrayModel.folder)
        .where(ArrayModel.folder != "")
        .where(ArrayModel.folder.isnot(None))
        .where(ArrayModel.tag_id.is_(None))
        .distinct()
    )
    folders = [row[0] for row in result.all() if row[0]]

    if not folders:
        return {"migrated": 0, "message": "No folders to migrate"}

    migrated_count = 0

    for folder_name in folders:
        # Check if tag already exists
        tag_result = await db.execute(
            select(TagModel).where(TagModel.name == folder_name)
        )
        tag = tag_result.scalar_one_or_none()

        if not tag:
            # Create new tag
            tag = TagModel(name=folder_name, color="#409eff", description=f"Migrated from folder: {folder_name}")
            db.add(tag)
            await db.flush()

        # Update arrays with this folder to use the tag
        await db.execute(
            sa_update(ArrayModel)
            .where(ArrayModel.folder == folder_name)
            .where(ArrayModel.tag_id.is_(None))
            .values(tag_id=tag.id)
        )
        migrated_count += 1

    await db.commit()

    logger.info(f"Migrated {migrated_count} folders to tags")

    return {
        "migrated": migrated_count,
        "folders": folders,
        "message": f"Successfully migrated {migrated_count} folders to tags",
    }
