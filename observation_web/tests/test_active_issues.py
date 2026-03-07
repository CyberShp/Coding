"""Tests for active issues management."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta

from tests.conftest import create_test_array, inject_test_alert


class TestActiveIssuesAPI:
    """Test active issues API endpoints."""

    @pytest.mark.asyncio
    async def test_active_issues_empty_by_default(self, app_client_with_db):
        """New array should have no active issues."""
        client, db = app_client_with_db
        await create_test_array(db, "test-array-issues-1", host="192.168.1.100")
        await db.commit()

        response = await client.get("/api/arrays/test-array-issues-1/status")
        assert response.status_code == 200
        data = response.json()
        assert data.get("active_issues", []) == []

    @pytest.mark.asyncio
    async def test_cpu_usage_creates_active_issue(self, app_client_with_db):
        """CPU usage alert should create an active issue."""
        client, db = app_client_with_db
        await create_test_array(db, "test-array-issues-2", host="192.168.1.101")
        await inject_test_alert(db, "test-array-issues-2", "cpu_usage", "warning", "CPU usage high: 85%", {"cpu0": 85})
        await db.commit()

        response = await client.get("/api/arrays/test-array-issues-2/status")
        assert response.status_code == 200
        data = response.json()
        issues = data.get("active_issues", [])
        assert len(issues) >= 1
        assert any(i.get("observer") == "cpu_usage" for i in issues)

    @pytest.mark.asyncio
    async def test_cpu_usage_recovery_removes_issue(self, app_client_with_db):
        """CPU recovery alert should remove the active issue."""
        client, db = app_client_with_db
        await create_test_array(db, "test-array-issues-3", host="192.168.1.102")
        await inject_test_alert(db, "test-array-issues-3", "cpu_usage", "warning", "CPU usage high", {"cpu0": 90})
        await inject_test_alert(db, "test-array-issues-3", "cpu_usage", "info", "CPU usage recovered", {"cpu0": 40, "recovered": True})
        await db.commit()

        response = await client.get("/api/arrays/test-array-issues-3/status")
        assert response.status_code == 200
        data = response.json()
        issues = data.get("active_issues", [])
        assert not any(i.get("observer") == "cpu_usage" for i in issues)

    @pytest.mark.asyncio
    async def test_multiple_issues_tracked_separately(self, app_client_with_db):
        """Multiple observer types should create separate issues."""
        client, db = app_client_with_db
        await create_test_array(db, "test-array-issues-4", host="192.168.1.103")
        await inject_test_alert(db, "test-array-issues-4", "cpu_usage", "warning", "CPU high", {"cpu0": 85})
        await inject_test_alert(db, "test-array-issues-4", "memory_leak", "error", "Memory leak", {"current_used_mb": 8000})
        await db.commit()

        response = await client.get("/api/arrays/test-array-issues-4/status")
        assert response.status_code == 200
        data = response.json()
        issues = data.get("active_issues", [])
        observers = [i.get("observer") for i in issues]
        assert "cpu_usage" in observers
        assert "memory_leak" in observers

    @pytest.mark.asyncio
    async def test_issue_update_preserves_since_timestamp(self, app_client_with_db):
        """Updating an issue should keep the original 'since' timestamp."""
        client, db = app_client_with_db
        await create_test_array(db, "test-array-issues-5", host="192.168.1.104")
        await inject_test_alert(db, "test-array-issues-5", "cpu_usage", "warning", "CPU high: 80%", {"cpu0": 80})
        await db.commit()

        response1 = await client.get("/api/arrays/test-array-issues-5/status")
        issues1 = response1.json().get("active_issues", [])
        cpu_issue1 = next((i for i in issues1 if i.get("observer") == "cpu_usage"), None)
        since1 = cpu_issue1.get("since") if cpu_issue1 else None

        # Use explicit later timestamp so the second alert is clearly "latest"
        later_ts = datetime.now() + timedelta(seconds=10)
        await inject_test_alert(db, "test-array-issues-5", "cpu_usage", "error", "CPU very high: 95%", {"cpu0": 95}, timestamp=later_ts)
        await db.commit()

        # Clear status cache so the second request re-derives active_issues from DB
        from backend.api.arrays import _array_status_cache
        if "test-array-issues-5" in _array_status_cache:
            _array_status_cache["test-array-issues-5"].active_issues = []

        response2 = await client.get("/api/arrays/test-array-issues-5/status")
        issues2 = response2.json().get("active_issues", [])
        cpu_issue2 = next((i for i in issues2 if i.get("observer") == "cpu_usage"), None)
        since2 = cpu_issue2.get("since") if cpu_issue2 else None

        assert since1 == since2
        assert cpu_issue2.get("level") == "error"
