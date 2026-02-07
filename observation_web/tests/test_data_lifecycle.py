"""Tests for backend/core/data_lifecycle.py — DataLifecycleManager."""
import gzip
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from backend.core.data_lifecycle import DataLifecycleManager


class TestDataLifecycleManager:
    def test_singleton(self):
        from backend.core.data_lifecycle import get_lifecycle_manager
        m1 = get_lifecycle_manager()
        m2 = get_lifecycle_manager()
        assert m1 is m2

    def test_compute_message_hash(self):
        mgr = DataLifecycleManager()
        h1 = mgr._compute_message_hash("2026-01-01", "test", "msg1")
        h2 = mgr._compute_message_hash("2026-01-01", "test", "msg1")
        assert h1 == h2

    def test_compute_hash_different_messages(self):
        mgr = DataLifecycleManager()
        h1 = mgr._compute_message_hash("2026-01-01", "test", "msg1")
        h2 = mgr._compute_message_hash("2026-01-01", "test", "msg2")
        assert h1 != h2

    def test_set_connection(self):
        mgr = DataLifecycleManager()
        mock_conn = MagicMock()
        mgr.set_connection(mock_conn)

    @pytest.mark.asyncio
    async def test_get_archive_config_default(self, db_session):
        mgr = DataLifecycleManager()
        config = await mgr.get_archive_config(db_session)
        assert config is not None

    @pytest.mark.asyncio
    async def test_get_archive_stats_empty(self, db_session):
        mgr = DataLifecycleManager()
        stats = await mgr.get_archive_stats(db_session)
        assert stats is not None


class TestArchiveCompression:
    def test_gzip_roundtrip(self):
        original = [{"alert": i, "level": "info"} for i in range(100)]
        data = json.dumps(original).encode()
        compressed = gzip.compress(data)
        decompressed = gzip.decompress(compressed)
        restored = json.loads(decompressed)
        assert restored == original

    def test_empty_data_compression(self):
        data = json.dumps([]).encode()
        compressed = gzip.compress(data)
        decompressed = gzip.decompress(compressed)
        assert json.loads(decompressed) == []
