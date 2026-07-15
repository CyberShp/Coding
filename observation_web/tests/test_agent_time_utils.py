from datetime import datetime, timezone

import pytest

from backend.api.ingest import IngestPayload, _handle_metrics, _metrics_store, get_metrics_for_ip
from backend.core.time_utils import parse_event_timestamp, timestamp_epoch


def test_utc_event_timestamp_converts_without_changing_instant():
    source = '2026-07-16T04:00:00+00:00'
    parsed = parse_event_timestamp(source)
    assert parsed.tzinfo is None
    assert parsed.timestamp() == timestamp_epoch(source)


@pytest.mark.asyncio
async def test_metrics_are_keyed_by_stable_array_id():
    _metrics_store.clear()
    payload = IngestPayload(
        type='metrics', array_id='array-42', ts=datetime.now(timezone.utc).isoformat(), cpu0=12.5,
    )
    await _handle_metrics(payload, '10.0.0.9')
    assert len(get_metrics_for_ip('array-42', 5)) == 1
    assert get_metrics_for_ip('10.0.0.9', 5) == []
