"""
Tests for persistent metric sample storage (backend/api/ingest.py).

Covers:
- downsampled persistence (>=60s gate) in _handle_metrics
- reading persisted samples by time range (get_metrics_from_db)
- fallback to in-memory store when DB has no rows (GET endpoint behaviour)
"""

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

# Top-level import registers MetricSampleModel in Base.metadata so the shared
# db_session fixture's create_all builds the metric_samples table.
from backend.models.metric_sample import MetricSampleModel
from backend.api import ingest


@pytest.fixture(autouse=True)
def _reset_ingest_state():
    """Isolate module-level ingest state between tests."""
    ingest._metrics_store.clear()
    ingest._last_persist_at.clear()
    ingest._last_push_at.clear()
    ingest._ip_to_array_id.clear()
    yield
    ingest._metrics_store.clear()
    ingest._last_persist_at.clear()


def _payload(array_id="arr-1", cpu0=10.0, mem_used=100.0, mem_total=1000.0, ts=None, **extra):
    return ingest.IngestPayload(
        type="metrics",
        array_id=array_id,
        ts=ts or datetime.now().isoformat(),
        cpu0=cpu0,
        mem_used_mb=mem_used,
        mem_total_mb=mem_total,
        **extra,
    )


@pytest.mark.asyncio
async def test_persist_writes_one_sample(db_session):
    """First metrics push with a live db persists exactly one row."""
    await ingest._handle_metrics(_payload(cpu0=42.0), "1.2.3.4", db=db_session)
    await db_session.commit()

    rows = (await db_session.execute(select(MetricSampleModel))).scalars().all()
    assert len(rows) == 1
    assert rows[0].array_id == "arr-1"
    assert rows[0].cpu0 == 42.0
    assert rows[0].mem_used_mb == 100.0
    # Also lands in the in-memory deque.
    assert "arr-1" in ingest._metrics_store


@pytest.mark.asyncio
async def test_downsampling_rate_limits_writes(db_session):
    """Rapid successive pushes within the window persist only one row."""
    for i in range(5):
        await ingest._handle_metrics(_payload(cpu0=float(i)), "1.2.3.4", db=db_session)
    await db_session.commit()

    rows = (await db_session.execute(select(MetricSampleModel))).scalars().all()
    assert len(rows) == 1, "high-frequency pushes must be downsampled to one row"
    # But every push is retained in memory.
    assert len(ingest._metrics_store["arr-1"]) == 5


@pytest.mark.asyncio
async def test_downsampling_allows_write_after_window(db_session):
    """Once the window elapses, a new push persists another row."""
    await ingest._handle_metrics(_payload(cpu0=1.0), "1.2.3.4", db=db_session)
    # Simulate 61s having passed since the last persist.
    ingest._last_persist_at["arr-1"] = time.time() - 61.0
    await ingest._handle_metrics(_payload(cpu0=2.0), "1.2.3.4", db=db_session)
    await db_session.commit()

    rows = (await db_session.execute(select(MetricSampleModel))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_no_db_skips_persistence_keeps_memory(db_session):
    """db=None: no persistence, but memory store still populated."""
    await ingest._handle_metrics(_payload(), "1.2.3.4", db=None)
    rows = (await db_session.execute(select(MetricSampleModel))).scalars().all()
    assert len(rows) == 0
    assert len(ingest._metrics_store["arr-1"]) == 1


@pytest.mark.asyncio
async def test_extra_fields_roundtrip(db_session):
    """Unknown metric fields are stored in extra JSON and read back."""
    await ingest._handle_metrics(
        _payload(load_avg=0.75, disk_pct=88), "1.2.3.4", db=db_session
    )
    await db_session.commit()

    out = await ingest.get_metrics_from_db(db_session, "arr-1", minutes=60)
    assert len(out) == 1
    assert out[0]["cpu0"] == 10.0
    assert out[0]["load_avg"] == 0.75
    assert out[0]["disk_pct"] == 88


@pytest.mark.asyncio
async def test_read_by_time_range(db_session):
    """get_metrics_from_db filters by window and returns ascending by ts."""
    now = datetime.now()
    # Old sample outside a 30-min window.
    db_session.add(MetricSampleModel(
        array_id="arr-1", ts=now - timedelta(hours=2), cpu0=1.0,
    ))
    # Two in-window samples, inserted out of order.
    db_session.add(MetricSampleModel(
        array_id="arr-1", ts=now - timedelta(minutes=5), cpu0=3.0,
    ))
    db_session.add(MetricSampleModel(
        array_id="arr-1", ts=now - timedelta(minutes=20), cpu0=2.0,
    ))
    # Another array, must not leak in.
    db_session.add(MetricSampleModel(
        array_id="arr-2", ts=now - timedelta(minutes=5), cpu0=9.0,
    ))
    await db_session.commit()

    out = await ingest.get_metrics_from_db(db_session, "arr-1", minutes=30)
    assert [r["cpu0"] for r in out] == [2.0, 3.0]  # ascending, old one excluded

    empty = await ingest.get_metrics_from_db(db_session, "arr-1", minutes=1)
    assert empty == []


@pytest.mark.asyncio
async def test_fallback_to_memory_when_db_empty(db_session):
    """When DB has no rows for the array, the memory store is the source."""
    # Nothing persisted; push with db=None so only memory has it.
    await ingest._handle_metrics(_payload(array_id="arr-9"), "5.6.7.8", db=None)

    persisted = await ingest.get_metrics_from_db(db_session, "arr-9", minutes=60)
    assert persisted == []  # DB empty -> caller falls back

    # Memory store is keyed by real array_id when available.
    mem = ingest.get_metrics_for_ip("arr-9", minutes=60)
    assert len(mem) == 1
    assert mem[0]["cpu0"] == 10.0
