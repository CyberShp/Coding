"""Tests for backend/api/issues.py — Issues API endpoints."""
import pytest


@pytest.mark.asyncio
class TestIssuesList:
    async def test_list_issues_empty(self, app_client):
        """Test listing issues when none exist."""
        resp = await app_client.get("/api/issues")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_list_issues_with_status_filter(self, app_client):
        """Test listing issues with status filter."""
        resp = await app_client.get("/api/issues?status_filter=open")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_list_issues_invalid_status(self, app_client):
        """Test listing issues with invalid status."""
        resp = await app_client.get("/api/issues?status_filter=invalid_status")
        assert resp.status_code == 200  # Returns empty list


@pytest.mark.asyncio
class TestIssuesCreate:
    async def test_create_issue_basic(self, app_client):
        """Test creating a basic issue."""
        resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue Title",
                "content": "This is a test issue content",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Issue Title"
        assert data["content"] == "This is a test issue content"
        assert data["status"] == "open"

    async def test_create_issue_empty_title(self, app_client):
        """Test creating issue with empty title."""
        resp = await app_client.post(
            "/api/issues",
            json={
                "title": "",
                "content": "Content only",
            },
        )
        # Empty title may be stripped or rejected
        assert resp.status_code in [200, 422]

    async def test_create_issue_very_long_title(self, app_client):
        """Test creating issue with very long title."""
        long_title = "a" * 300
        resp = await app_client.post(
            "/api/issues",
            json={
                "title": long_title,
                "content": "Test content",
            },
        )
        # Title may be truncated
        assert resp.status_code in [200, 422]

    async def test_create_issue_very_long_content(self, app_client):
        """Test creating issue with very long content."""
        long_content = "a" * 10000
        resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Long Content Test",
                "content": long_content,
            },
        )
        # Should succeed (content not validated for length)
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestIssuesGet:
    async def test_get_issue_not_found(self, app_client):
        """Test getting non-existent issue."""
        resp = await app_client.get("/api/issues/99999")
        assert resp.status_code == 404

    async def test_get_issue_after_create(self, app_client):
        """Test getting issue that was just created."""
        # Create first
        create_resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue",
                "content": "Test content",
            },
        )
        assert create_resp.status_code == 200
        issue_id = create_resp.json()["id"]
        
        # Get
        resp = await app_client.get(f"/api/issues/{issue_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == issue_id


@pytest.mark.asyncio
class TestIssuesUpdateStatus:
    async def test_update_issue_status_not_found(self, app_client):
        """Test updating status of non-existent issue."""
        resp = await app_client.put(
            "/api/issues/99999/status",
            json={"status": "resolved"},
        )
        assert resp.status_code == 404

    async def test_update_issue_invalid_status(self, app_client):
        """Test updating issue with invalid status."""
        # Create issue first
        create_resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue",
                "content": "Test",
            },
        )
        issue_id = create_resp.json()["id"]
        
        # Try invalid status
        resp = await app_client.put(
            f"/api/issues/{issue_id}/status",
            json={"status": "invalid_status"},
        )
        assert resp.status_code == 400

    async def test_update_issue_to_resolved(self, app_client):
        """Test updating issue status to resolved."""
        # Create issue
        create_resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue",
                "content": "Test",
            },
        )
        issue_id = create_resp.json()["id"]
        
        # Update to resolved
        resp = await app_client.put(
            f"/api/issues/{issue_id}/status",
            json={"status": "resolved"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"

    async def test_update_issue_to_rejected(self, app_client):
        """Test updating issue status to rejected."""
        # Create issue
        create_resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue",
                "content": "Test",
            },
        )
        issue_id = create_resp.json()["id"]
        
        # Update to rejected
        resp = await app_client.put(
            f"/api/issues/{issue_id}/status",
            json={"status": "rejected"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"

    async def test_update_issue_to_adopted(self, app_client):
        """Test updating issue status to adopted."""
        # Create issue
        create_resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue",
                "content": "Test",
            },
        )
        issue_id = create_resp.json()["id"]
        
        # Update to adopted
        resp = await app_client.put(
            f"/api/issues/{issue_id}/status",
            json={"status": "adopted"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "adopted"

    async def test_update_issue_with_resolution_note(self, app_client):
        """Test updating issue with resolution note."""
        # Create issue
        create_resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue",
                "content": "Test",
            },
        )
        issue_id = create_resp.json()["id"]
        
        # Update with resolution note
        resp = await app_client.put(
            f"/api/issues/{issue_id}/status",
            json={
                "status": "resolved",
                "resolution_note": "This issue has been fixed",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolution_note"] == "This issue has been fixed"

    async def test_update_issue_very_long_resolution_note(self, app_client):
        """Test updating issue with very long resolution note."""
        # Create issue
        create_resp = await app_client.post(
            "/api/issues",
            json={
                "title": "Test Issue",
                "content": "Test",
            },
        )
        issue_id = create_resp.json()["id"]
        
        # Try very long resolution note
        long_note = "a" * 3000
        resp = await app_client.put(
            f"/api/issues/{issue_id}/status",
            json={
                "status": "resolved",
                "resolution_note": long_note,
            },
        )
        # Should succeed (note may be truncated to 2000 chars)
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestIssuesEdgeCases:
    async def test_create_issue_missing_title(self, app_client):
        """Test creating issue without title."""
        resp = await app_client.post(
            "/api/issues",
            json={"content": "Content only"},
        )
        assert resp.status_code == 422

    async def test_create_issue_missing_content(self, app_client):
        """Test creating issue without content."""
        resp = await app_client.post(
            "/api/issues",
            json={"title": "Title only"},
        )
        assert resp.status_code == 422

    async def test_create_issue_whitespace_only(self, app_client):
        """Test creating issue with whitespace-only title."""
        resp = await app_client.post(
            "/api/issues",
            json={"title": "   ", "content": "Content"},
        )
        # Whitespace should be stripped
        assert resp.status_code in [200, 422]
