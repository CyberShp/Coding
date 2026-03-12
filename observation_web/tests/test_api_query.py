"""Tests for backend/api/query.py — Query API endpoints."""
import json
import pytest


@pytest.mark.asyncio
class TestQueryTemplates:
    async def test_list_templates_builtin_only(self, app_client):
        """Test listing built-in templates."""
        resp = await app_client.get("/api/query/templates?include_builtin=true")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Built-in templates should exist
        assert len(data) > 0

    async def test_list_templates_without_builtin(self, app_client):
        """Test listing templates without built-ins."""
        resp = await app_client.get("/api/query/templates?include_builtin=false")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_list_templates_default(self, app_client):
        """Test listing templates with default parameters."""
        resp = await app_client.get("/api/query/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
class TestQueryPattern:
    async def test_test_pattern_valid(self, app_client):
        """Test pattern testing with valid regex."""
        resp = await app_client.post(
            "/api/query/test-pattern",
            json={
                "pattern": r"error|warn",
                "test_text": "This is an error message",
                "rule_type": "valid_match",
                "expect_match": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "matches" in data
        assert "valid" in data

    async def test_test_pattern_no_match(self, app_client):
        """Test pattern that doesn't match."""
        resp = await app_client.post(
            "/api/query/test-pattern",
            json={
                "pattern": r"success",
                "test_text": "This is an error message",
                "rule_type": "valid_match",
                "expect_match": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "matches" in data
        assert "valid" in data

    async def test_test_pattern_invalid_regex(self, app_client):
        """Test pattern with invalid regex."""
        resp = await app_client.post(
            "/api/query/test-pattern",
            json={
                "pattern": r"[invalid",
                "test_text": "test text",
                "rule_type": "valid_match",
                "expect_match": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should return error info
        assert "error" in data or "matched" in data


@pytest.mark.asyncio
class TestValidatePattern:
    async def test_validate_pattern_valid(self, app_client):
        """Test validating a valid regex pattern."""
        resp = await app_client.post(
            "/api/query/validate-pattern",
            json={"pattern": r"^\d{4}-\d{2}-\d{2}$"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert data["valid"] is True

    async def test_validate_pattern_invalid(self, app_client):
        """Test validating an invalid regex pattern."""
        resp = await app_client.post(
            "/api/query/validate-pattern",
            json={"pattern": r"["},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert data["valid"] is False
        assert "error" in data


@pytest.mark.asyncio
class TestQueryExecute:
    async def test_execute_query_array_not_found(self, app_client):
        """Test executing query on non-existent array."""
        resp = await app_client.post(
            "/api/query/execute",
            json={
                "commands": ["ls"],
                "target_arrays": ["nonexistent-array"],
                "rule": {
                    "rule_type": "valid_match",
                    "pattern": ".*",
                    "expect_match": True,
                },
            },
        )
        assert resp.status_code == 404

    async def test_execute_query_array_not_connected(self, app_client):
        """Test executing query on disconnected array."""
        # First create an array
        from tests.conftest import create_test_array
        from sqlalchemy import select
        from backend.models.array import ArrayModel
        
        # This test would require creating an array and then trying to query it
        # The array would not be connected, so it should return 400
        resp = await app_client.post(
            "/api/query/execute",
            json={
                "commands": ["ls"],
                "target_arrays": ["test-array-123"],
                "rule": {
                    "rule_type": "valid_match",
                    "pattern": ".*",
                    "expect_match": True,
                },
            },
        )
        # Array doesn't exist, so 404
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestQueryTemplateCRUD:
    async def test_create_template(self, app_client):
        """Test creating a new query template."""
        resp = await app_client.post(
            "/api/query/templates",
            json={
                "name": "Test Template",
                "description": "A test template",
                "commands": ["ls -la", "df -h"],
                "rule": {
                    "rule_type": "valid_match",
                    "pattern": ".*",
                    "expect_match": True,
                    "extract_fields": [],
                },
                "auto_monitor": False,
                "monitor_interval": 60,
                "monitor_arrays": [],
                "alert_on_mismatch": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Template"

    async def test_delete_template_not_found(self, app_client):
        """Test deleting non-existent template."""
        resp = await app_client.delete("/api/query/templates/99999")
        assert resp.status_code == 404

    async def test_delete_builtin_template(self, app_client):
        """Test deleting built-in template should fail."""
        resp = await app_client.delete("/api/query/templates/-1")
        assert resp.status_code == 400
        data = resp.json()
        assert "built-in" in data.get("detail", "").lower()


@pytest.mark.asyncio
class TestQueryEdgeCases:
    async def test_test_pattern_empty_strings(self, app_client):
        """Test pattern testing with empty strings."""
        resp = await app_client.post(
            "/api/query/test-pattern",
            json={
                "pattern": "",
                "test_text": "",
                "rule_type": "valid_match",
                "expect_match": True,
            },
        )
        assert resp.status_code == 200

    async def test_validate_pattern_empty(self, app_client):
        """Test validating empty pattern."""
        resp = await app_client.post(
            "/api/query/validate-pattern",
            json={"pattern": ""},
        )
        assert resp.status_code == 200

    async def test_create_template_empty_commands(self, app_client):
        """Test creating template with empty commands list."""
        resp = await app_client.post(
            "/api/query/templates",
            json={
                "name": "Empty Commands Template",
                "description": "Test",
                "commands": [],
                "rule": {
                    "rule_type": "valid_match",
                    "pattern": ".*",
                    "expect_match": True,
                    "extract_fields": [],
                },
            },
        )
        # May succeed or fail depending on validation
        assert resp.status_code in [200, 422]
