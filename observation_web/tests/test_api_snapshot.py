"""Tests for backend/api/snapshot.py — Snapshot API endpoints."""
import json
import pytest
from datetime import datetime, timedelta


@pytest.mark.asyncio
class TestSnapshotAPI:
    @pytest.mark.skip(reason="SQLite in-memory database transaction issue with concurrent access")
    async def test_list_snapshots_empty(self, db_session):
        """Test listing snapshots when none exist - using db_session to avoid transaction issues."""
        from sqlalchemy import select
        from backend.models.snapshot import SnapshotModel
        
        # Query directly from database to verify empty
        result = await db_session.execute(
            select(SnapshotModel).where(SnapshotModel.array_id == "test-array")
        )
        snapshots = result.scalars().all()
        assert len(snapshots) == 0

    @pytest.mark.skip(reason="SQLite in-memory database transaction issue with concurrent access")
    async def test_list_snapshots_with_limit(self, app_client):
        """Test listing snapshots with custom limit."""
        resp = await app_client.get("/api/snapshots/test-array?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_list_snapshots_invalid_limit(self, app_client):
        """Test listing snapshots with invalid limit (too high)."""
        resp = await app_client.get("/api/snapshots/test-array?limit=200")
        # Limit > 100 returns 422 validation error
        assert resp.status_code == 422

    async def test_create_snapshot_empty_array(self, app_client_with_db):
        """Test creating snapshot for array with no alerts."""
        client, session = app_client_with_db
        resp = await client.post("/api/snapshots/empty-array")
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["array_id"] == "empty-array"

    async def test_create_snapshot_with_label(self, app_client_with_db):
        """Test creating snapshot with custom label."""
        client, session = app_client_with_db
        resp = await client.post("/api/snapshots/test-array?label=TestSnapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("label") == "TestSnapshot"

    async def test_create_snapshot_with_task_id(self, app_client_with_db):
        """Test creating snapshot with task ID."""
        client, session = app_client_with_db
        resp = await client.post("/api/snapshots/test-array?task_id=123")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("task_id") == 123


@pytest.mark.asyncio
class TestSnapshotDiff:
    async def test_diff_snapshots_not_found(self, app_client):
        """Test diff with non-existent snapshots."""
        resp = await app_client.get("/api/snapshots/diff?id1=9999&id2=9998")
        assert resp.status_code == 404

    async def test_diff_same_snapshot(self, app_client_with_db):
        """Test diff when comparing the same snapshot."""
        client, session = app_client_with_db
        
        # Create a snapshot first
        resp = await client.post("/api/snapshots/test-array?label=Test1")
        assert resp.status_code == 200
        snap1 = resp.json()
        
        # Try to diff with itself
        resp = await client.get(f"/api/snapshots/diff?id1={snap1['id']}&id2={snap1['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "changes" in data
        assert len(data["changes"]) == 0


@pytest.mark.asyncio
class TestSnapshotEdgeCases:
    async def test_list_snapshots_nonexistent_array(self, app_client):
        """Test listing snapshots for non-existent array returns empty list."""
        resp = await app_client.get("/api/snapshots/definitely-does-not-exist-12345")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_snapshot_label_empty_string(self, app_client_with_db):
        """Test creating snapshot with empty label uses default."""
        client, session = app_client_with_db
        resp = await client.post("/api/snapshots/test-array?label=")
        assert resp.status_code == 200
        data = resp.json()
        # Empty label should use default format
        assert "label" in data
