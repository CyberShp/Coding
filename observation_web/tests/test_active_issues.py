"""Tests for active issues management."""
import pytest
import pytest_asyncio


class TestActiveIssuesAPI:
    """Test active issues API endpoints."""
    
    @pytest.mark.asyncio
    async def test_active_issues_empty_by_default(self, app_client):
        """New array should have no active issues."""
        reg_data = {
            "array_id": "test-array-issues-1",
            "hostname": "test-host",
            "ip_address": "192.168.1.100",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        response = await app_client.get("/api/arrays/test-array-issues-1/status")
        assert response.status_code == 200
        data = response.json()
        assert data.get("active_issues", []) == []
    
    @pytest.mark.asyncio
    async def test_cpu_usage_creates_active_issue(self, app_client):
        """CPU usage alert should create an active issue."""
        reg_data = {
            "array_id": "test-array-issues-2",
            "hostname": "test-host",
            "ip_address": "192.168.1.101",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        alert_data = {
            "array_id": "test-array-issues-2",
            "alerts": [{
                "observer_name": "cpu_usage",
                "level": "warning",
                "message": "CPU usage high: 85%",
                "details": {"cpu0": 85}
            }]
        }
        await app_client.post("/api/ingest", json=alert_data)
        
        response = await app_client.get("/api/arrays/test-array-issues-2/status")
        assert response.status_code == 200
        data = response.json()
        issues = data.get("active_issues", [])
        assert len(issues) >= 1
        assert any(i.get("observer") == "cpu_usage" for i in issues)
    
    @pytest.mark.asyncio
    async def test_cpu_usage_recovery_removes_issue(self, app_client):
        """CPU recovery alert should remove the active issue."""
        reg_data = {
            "array_id": "test-array-issues-3",
            "hostname": "test-host",
            "ip_address": "192.168.1.102",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        # Create issue
        alert_data = {
            "array_id": "test-array-issues-3",
            "alerts": [{
                "observer_name": "cpu_usage",
                "level": "warning",
                "message": "CPU usage high",
                "details": {"cpu0": 90}
            }]
        }
        await app_client.post("/api/ingest", json=alert_data)
        
        # Recovery
        recovery_data = {
            "array_id": "test-array-issues-3",
            "alerts": [{
                "observer_name": "cpu_usage",
                "level": "info",
                "message": "CPU usage recovered",
                "details": {"cpu0": 40, "recovered": True}
            }]
        }
        await app_client.post("/api/ingest", json=recovery_data)
        
        response = await app_client.get("/api/arrays/test-array-issues-3/status")
        assert response.status_code == 200
        data = response.json()
        issues = data.get("active_issues", [])
        assert not any(i.get("observer") == "cpu_usage" for i in issues)
    
    @pytest.mark.asyncio
    async def test_multiple_issues_tracked_separately(self, app_client):
        """Multiple observer types should create separate issues."""
        reg_data = {
            "array_id": "test-array-issues-4",
            "hostname": "test-host",
            "ip_address": "192.168.1.103",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        # Create CPU issue
        cpu_alert = {
            "array_id": "test-array-issues-4",
            "alerts": [{
                "observer_name": "cpu_usage",
                "level": "warning",
                "message": "CPU high",
                "details": {"cpu0": 85}
            }]
        }
        await app_client.post("/api/ingest", json=cpu_alert)
        
        # Create memory leak issue
        mem_alert = {
            "array_id": "test-array-issues-4",
            "alerts": [{
                "observer_name": "memory_leak",
                "level": "error",
                "message": "Memory leak",
                "details": {"current_used_mb": 8000}
            }]
        }
        await app_client.post("/api/ingest", json=mem_alert)
        
        response = await app_client.get("/api/arrays/test-array-issues-4/status")
        assert response.status_code == 200
        data = response.json()
        issues = data.get("active_issues", [])
        observers = [i.get("observer") for i in issues]
        assert "cpu_usage" in observers
        assert "memory_leak" in observers
    
    @pytest.mark.asyncio
    async def test_issue_update_preserves_since_timestamp(self, app_client):
        """Updating an issue should keep the original 'since' timestamp."""
        reg_data = {
            "array_id": "test-array-issues-5",
            "hostname": "test-host",
            "ip_address": "192.168.1.104",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        # First alert
        alert1 = {
            "array_id": "test-array-issues-5",
            "alerts": [{
                "observer_name": "cpu_usage",
                "level": "warning",
                "message": "CPU high: 80%",
                "details": {"cpu0": 80}
            }]
        }
        await app_client.post("/api/ingest", json=alert1)
        
        response1 = await app_client.get("/api/arrays/test-array-issues-5/status")
        issues1 = response1.json().get("active_issues", [])
        cpu_issue1 = next((i for i in issues1 if i.get("observer") == "cpu_usage"), None)
        since1 = cpu_issue1.get("since") if cpu_issue1 else None
        
        # Second alert (same observer, higher value)
        alert2 = {
            "array_id": "test-array-issues-5",
            "alerts": [{
                "observer_name": "cpu_usage",
                "level": "error",
                "message": "CPU very high: 95%",
                "details": {"cpu0": 95}
            }]
        }
        await app_client.post("/api/ingest", json=alert2)
        
        response2 = await app_client.get("/api/arrays/test-array-issues-5/status")
        issues2 = response2.json().get("active_issues", [])
        cpu_issue2 = next((i for i in issues2 if i.get("observer") == "cpu_usage"), None)
        since2 = cpu_issue2.get("since") if cpu_issue2 else None
        
        # 'since' should remain the same, but 'latest' should be updated
        assert since1 == since2
        assert cpu_issue2.get("level") == "error"  # Updated to new level
