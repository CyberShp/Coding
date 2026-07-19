"""Ingest push-side dedup: the same alert can arrive via HTTP push AND SSH pull
(mixed mode reads the same alerts.log line), so ingest must not double-write."""
import pytest

from backend.api.ingest import _handle_alert, IngestPayload
from backend.core.alert_store import get_alert_store


def _payload():
    return IngestPayload(
        type="alert",
        array_id="arrX",
        observer_name="cpu_usage",
        level="warning",
        message="CPU high",
        timestamp="2026-01-01T00:00:00",
    )


@pytest.mark.asyncio
async def test_duplicate_push_is_skipped(db_session):
    await _handle_alert(_payload(), "1.2.3.4", db_session)
    await _handle_alert(_payload(), "1.2.3.4", db_session)  # identical → skip
    alerts = await get_alert_store().get_alerts(db_session, array_id="arrX", limit=10)
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_distinct_alerts_both_kept(db_session):
    p1 = _payload()
    p2 = _payload()
    p2.message = "CPU very high"  # different content
    await _handle_alert(p1, "1.2.3.4", db_session)
    await _handle_alert(p2, "1.2.3.4", db_session)
    alerts = await get_alert_store().get_alerts(db_session, array_id="arrX", limit=10)
    assert len(alerts) == 2
