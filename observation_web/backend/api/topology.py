"""Ethernet topology: switch enrollment, collection and graph reads."""
import asyncio
import json
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.topology_collector import collect_device
from ..core.topology_graph import build_graph
from ..core.topology_parsers import TopologyParseError
from ..db.database import get_db
from ..models.array import ArrayModel
from ..models.topology import TopologySnapshotModel, TopologySwitchModel, TopologyCableModel
from .auth import require_user

router = APIRouter(prefix="/topology", tags=["topology"])
_collection_slots = asyncio.Semaphore(4)


class SwitchInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=256)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=64)
    password: Optional[str] = Field(default=None, max_length=512)
    key_path: str = Field(default="", max_length=512)

    @field_validator("name", "host", "username")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("字段不能为空或包含控制字符")
        return value


def public_switch(row):
    return {"id": row.device_id, "name": row.name, "host": row.host, "port": row.port,
            "username": row.username, "key_path": row.key_path, "kind": "switch",
            "has_saved_password": bool(row.saved_password)}


async def inventory(db):
    arrays = (await db.execute(select(ArrayModel))).scalars().all()
    switches = (await db.execute(select(TopologySwitchModel))).scalars().all()
    devices = [{"id": "storage:" + a.array_id, "array_id": a.array_id, "name": a.name,
                "host": a.host, "mgmt_ip": a.mgmt_ip or "", "kind": "storage"} for a in arrays]
    devices.extend({k: public_switch(s)[k] for k in ("id", "name", "host", "kind")} for s in switches)
    return devices


@router.get("")
async def graph(db: AsyncSession = Depends(get_db)):
    devices = await inventory(db)
    rows = (await db.execute(select(TopologySnapshotModel))).scalars().all()
    snapshots = {r.device_id: {"payload": json.loads(r.payload), "collected_at": r.collected_at,
                               "attempted_at": r.attempted_at, "last_error": r.last_error} for r in rows}
    cables = (await db.execute(select(TopologyCableModel))).scalars().all()
    return build_graph(devices, snapshots, cables=[{
        key: getattr(c, key) for key in ('cable_id', 'source', 'source_port', 'target', 'target_port', 'confirmed_by', 'confirmed_at')
    } for c in cables])


class CableInput(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    source_port: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=80)
    target_port: str = Field(min_length=1, max_length=128)


@router.post('/links', status_code=201)
async def confirm_cable(data: CableInput, db: AsyncSession = Depends(get_db), user=Depends(require_user)):
    if data.source == data.target:
        raise HTTPException(422, '请选择两台不同设备')
    current = await graph(db)
    for end in ('source', 'target'):
        device = next((d for d in current['devices'] if d['id'] == getattr(data, end) and d['kind'] != 'external'), None)
        if not device or not any(p['id'] == getattr(data, end + '_port') for p in device['ports']):
            raise HTTPException(422, '请选择已添加设备中已采集的物理端口')
    endpoints = sorted([(data.source, data.source_port), (data.target, data.target_port)])
    cable_id = hashlib.sha256(repr(endpoints).encode()).hexdigest()
    db.add(TopologyCableModel(cable_id=cable_id, source=endpoints[0][0], source_port=endpoints[0][1],
                             target=endpoints[1][0], target_port=endpoints[1][1],
                             confirmed_by=user.nickname, confirmed_at=datetime.utcnow()))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, '这条接线已确认')
    return {'id': cable_id}


@router.delete('/links/{cable_id}', status_code=204)
async def remove_cable(cable_id: str, db: AsyncSession = Depends(get_db), user=Depends(require_user)):
    result = await db.execute(delete(TopologyCableModel).where(TopologyCableModel.cable_id == cable_id))
    if not result.rowcount:
        raise HTTPException(404, '人工接线不存在')
    await db.commit()


async def invalidate_device(db, device_id):
    await db.execute(delete(TopologySnapshotModel).where(TopologySnapshotModel.device_id == device_id))
    await db.execute(delete(TopologyCableModel).where(
        (TopologyCableModel.source == device_id) | (TopologyCableModel.target == device_id)))


@router.get("/switches")
async def list_switches(db: AsyncSession = Depends(get_db)):
    return [public_switch(s) for s in (await db.execute(select(TopologySwitchModel))).scalars().all()]


async def save_switch(data, row, db):
    # One SSH endpoint must not be enrolled as both a storage and a switch.
    existing_array = (await db.execute(select(ArrayModel.id).where(ArrayModel.host == data.host))).first()
    if existing_array:
        raise HTTPException(409, "该地址已作为存储设备添加")
    for key in ("name", "host", "port", "username", "key_path"):
        setattr(row, key, getattr(data, key))
    if data.password is not None:
        row.saved_password = data.password
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "交换机地址已存在")
    await db.refresh(row)
    return public_switch(row)


@router.post("/switches", status_code=201)
async def add_switch(data: SwitchInput, db: AsyncSession = Depends(get_db), user=Depends(require_user)):
    return await save_switch(data, TopologySwitchModel(device_id="switch:" + uuid.uuid4().hex), db)


@router.put("/switches/{device_id}")
async def edit_switch(device_id: str, data: SwitchInput, db: AsyncSession = Depends(get_db), user=Depends(require_user)):
    row = await db.get(TopologySwitchModel, device_id)
    if not row:
        raise HTTPException(404, "交换机不存在")
    # Endpoint edits invalidate the old identity and any in-flight collection token.
    if any(getattr(row, key) != getattr(data, key) for key in ('host', 'port', 'username', 'key_path')):
        await invalidate_device(db, device_id)
    return await save_switch(data, row, db)


@router.delete("/switches/{device_id}", status_code=204)
async def remove_switch(device_id: str, db: AsyncSession = Depends(get_db), user=Depends(require_user)):
    row = await db.get(TopologySwitchModel, device_id)
    if not row:
        raise HTTPException(404, "交换机不存在")
    await db.delete(row)
    await invalidate_device(db, device_id)
    await db.commit()


@router.post("/collect/{device_id}")
async def collect(device_id: str, db: AsyncSession = Depends(get_db), user=Depends(require_user)):
    if device_id.startswith("storage:"):
        row = (await db.execute(select(ArrayModel).where(ArrayModel.array_id == device_id[8:]))).scalar_one_or_none()
        kind = "storage"
    else:
        row = await db.get(TopologySwitchModel, device_id)
        kind = "switch"
    if not row:
        raise HTTPException(404, "设备不存在")
    device = {"id": device_id, "host": row.host, "port": row.port, "username": row.username,
              "key_path": row.key_path, "kind": kind}
    password = row.saved_password or ""
    if kind == "storage" and not password:
        from ..core.ssh_pool import get_ssh_pool
        connection = get_ssh_pool().get_connection(row.array_id)
        password = connection.password if connection else ""
    # A persisted compare-and-set token prevents old collectors overwriting new results.
    snapshot = await db.get(TopologySnapshotModel, device_id)
    if not snapshot:
        db.add(TopologySnapshotModel(device_id=device_id))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
    attempted = datetime.utcnow()
    claim = await db.execute(update(TopologySnapshotModel).where(
        TopologySnapshotModel.device_id == device_id,
        (TopologySnapshotModel.attempted_at.is_(None)) |
        (TopologySnapshotModel.attempted_at < attempted - timedelta(minutes=3)) |
        (TopologySnapshotModel.last_error != "采集中"),
    ).values(attempted_at=attempted, last_error="采集中"))
    await db.commit()
    if not claim.rowcount:
        raise HTTPException(409, "该设备正在采集，请稍后刷新")
    error, payload = "", None
    try:
        try:
            await asyncio.wait_for(_collection_slots.acquire(), timeout=5)
        except asyncio.TimeoutError:
            raise RuntimeError("采集任务繁忙，请稍后重试") from None
        try:
            payload = await asyncio.to_thread(collect_device, device, password)
        finally:
            _collection_slots.release()
    except (TopologyParseError, ConnectionError, TimeoutError, RuntimeError) as exc:
        error = str(exc)
    except Exception:
        error = "SSH 采集失败，请检查连接及设备命令兼容性"
    values = {"last_error": error}
    if payload is not None:
        values.update(payload=json.dumps(payload, ensure_ascii=False), collected_at=datetime.utcnow())
    saved = await db.execute(update(TopologySnapshotModel).where(
        TopologySnapshotModel.device_id == device_id, TopologySnapshotModel.attempted_at == attempted,
    ).values(**values))
    await db.commit()
    if not saved.rowcount:
        raise HTTPException(409, "设备配置已变化，本次结果已弃用")
    return {"device_id": device_id, "success": not error, "error": error}
