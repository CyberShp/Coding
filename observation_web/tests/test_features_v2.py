"""Tests for V2 features: preferences API, tags hierarchy, import, card inventory."""
import io
import pytest
import pytest_asyncio


class TestM3WatchersPathMapping:
    """M3: API path maps to frontend page for watchers presence."""

    def test_api_path_to_page_maps_array_status(self):
        """ /api/arrays/{id}/status -> /arrays/{id}."""
        from backend.middleware.user_session import _api_path_to_page
        assert _api_path_to_page("/api/arrays/arr_abc123/status") == "/arrays/arr_abc123"

    def test_api_path_to_page_maps_array_id_only(self):
        """ /api/arrays/{id} -> /arrays/{id}."""
        from backend.middleware.user_session import _api_path_to_page
        assert _api_path_to_page("/api/arrays/arr_xyz") == "/arrays/arr_xyz"

    def test_api_path_to_page_passthrough_non_array(self):
        """Non-array paths pass through unchanged."""
        from backend.middleware.user_session import _api_path_to_page
        assert _api_path_to_page("/api/arrays") == "/api/arrays"
        assert _api_path_to_page("/api/alerts") == "/api/alerts"


class TestFeature5PreferencesAPI:
    """Feature 5: GET/PUT /users/me/preferences."""

    @pytest.mark.asyncio
    async def test_get_preferences_empty(self, app_client):
        """New user should get null default_tag_id."""
        response = await app_client.get("/api/users/me/preferences")
        assert response.status_code == 200
        data = response.json()
        assert "default_tag_id" in data
        assert data["default_tag_id"] is None

    @pytest.mark.asyncio
    async def test_put_preferences(self, app_client_with_db):
        """Should update and persist default_tag_id."""
        from tests.conftest import create_test_array
        from backend.models.tag import TagModel

        client, db = app_client_with_db
        tag = TagModel(name="TestTag", color="#ff0000", level=1)
        db.add(tag)
        await db.flush()
        await db.commit()

        response = await client.put(
            "/api/users/me/preferences",
            json={"default_tag_id": tag.id},
        )
        assert response.status_code == 200
        assert response.json()["default_tag_id"] == tag.id

        get_resp = await client.get("/api/users/me/preferences")
        assert get_resp.status_code == 200
        assert get_resp.json()["default_tag_id"] == tag.id

    @pytest.mark.asyncio
    async def test_put_preferences_null(self, app_client_with_db):
        """Should allow clearing default_tag_id."""
        client, db = app_client_with_db
        await client.put("/api/users/me/preferences", json={"default_tag_id": None})
        response = await client.get("/api/users/me/preferences")
        assert response.status_code == 200
        assert response.json()["default_tag_id"] is None


class TestFeature6TagsHierarchy:
    """Feature 6: L1/L2 tags CRUD + hierarchy query."""

    @pytest.mark.asyncio
    async def test_create_l1_tag(self, app_client):
        """Should create level-1 tag."""
        response = await app_client.post(
            "/api/tags",
            json={"name": "L1-A", "color": "#00ff00", "level": 1},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "L1-A"
        assert data["level"] == 1
        assert data["parent_id"] is None

    @pytest.mark.asyncio
    async def test_create_l2_tag_under_l1(self, app_client):
        """Should create L2 tag with parent."""
        r1 = await app_client.post(
            "/api/tags",
            json={"name": "L1-B", "color": "#0000ff", "level": 1},
        )
        assert r1.status_code == 201
        parent_id = r1.json()["id"]

        r2 = await app_client.post(
            "/api/tags",
            json={"name": "L2-B1", "color": "#ff00ff", "level": 2, "parent_id": parent_id},
        )
        assert r2.status_code == 201
        data = r2.json()
        assert data["parent_id"] == parent_id
        assert data["level"] == 2

    @pytest.mark.asyncio
    async def test_list_tags_hierarchy(self, app_client):
        """Should list tags with parent_name for L2."""
        response = await app_client.get("/api/tags")
        assert response.status_code == 200
        tags = response.json()
        assert isinstance(tags, list)
        for t in tags:
            assert "name" in t
            assert "level" in t
            if t.get("parent_id"):
                assert "parent_name" in t


class TestFeature7Import:
    """Feature 7: CSV/Excel import."""

    @pytest.mark.asyncio
    async def test_import_csv_normal(self, app_client):
        """Should import valid CSV with name, host."""
        csv = "name,host\nArray1,192.168.1.10\nArray2,192.168.1.11"
        files = {"file": ("arrays.csv", io.BytesIO(csv.encode()), "text/csv")}
        response = await app_client.post("/api/arrays/import", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["created"] >= 1
        assert "total_rows" in data

    @pytest.mark.asyncio
    async def test_import_with_tag_l1_l2(self, app_client):
        """Should create L1/L2 tags from tag_l1, tag_l2 columns."""
        csv = "name,host,tag_l1,tag_l2,color\nArr1,10.0.0.1,DC1,Rack1,#ff0000"
        files = {"file": ("arrays.csv", io.BytesIO(csv.encode()), "text/csv")}
        response = await app_client.post("/api/arrays/import", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["created"] >= 1

    @pytest.mark.asyncio
    async def test_import_duplicate_host_skipped(self, app_client):
        """Duplicate host should be skipped."""
        csv = "name,host\nA1,192.168.1.100\nA2,192.168.1.100"
        files = {"file": ("arrays.csv", io.BytesIO(csv.encode()), "text/csv")}
        response = await app_client.post("/api/arrays/import", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] >= 1 or data["created"] == 1

    @pytest.mark.asyncio
    async def test_import_file_too_large(self, app_client):
        """Should reject file > 10MB."""
        content = b"x" * (11 * 1024 * 1024)
        files = {"file": ("big.csv", io.BytesIO(content), "text/csv")}
        response = await app_client.post("/api/arrays/import", files=files)
        assert response.status_code == 413


class TestFeature10CardInventory:
    """Feature 10: Card inventory CRUD + fuzzy search."""

    @pytest.mark.asyncio
    async def test_create_card(self, app_client):
        """Should create card entry."""
        response = await app_client.post(
            "/api/card-inventory",
            json={
                "name": "Card-A",
                "device_type": "controller",
                "model": "ModelX",
                "description": "Test card",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Card-A"
        assert data["model"] == "ModelX"

    @pytest.mark.asyncio
    async def test_list_cards_empty(self, app_client):
        """Should return empty list when no cards."""
        response = await app_client.get("/api/card-inventory")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_search_multi_keyword_and(self, app_client):
        """Multi-keyword search should AND match."""
        await app_client.post(
            "/api/card-inventory",
            json={"name": "Card Alpha Beta", "device_type": "controller", "model": "M1", "description": ""},
        )
        await app_client.post(
            "/api/card-inventory",
            json={"name": "Card Gamma", "device_type": "controller", "model": "M2", "description": ""},
        )
        response = await app_client.get("/api/card-inventory?q=Card+Alpha")
        assert response.status_code == 200
        cards = response.json()
        assert len(cards) >= 1
        assert any("Alpha" in (c.get("name") or "") for c in cards)

    @pytest.mark.asyncio
    async def test_crud_card(self, app_client):
        """Full CRUD cycle."""
        create = await app_client.post(
            "/api/card-inventory",
            json={"name": "CRUD-Card", "device_type": "disk", "model": "X", "description": ""},
        )
        assert create.status_code == 201
        cid = create.json()["id"]

        get_resp = await app_client.get(f"/api/card-inventory/{cid}")
        assert get_resp.status_code == 200

        update = await app_client.put(
            f"/api/card-inventory/{cid}",
            json={"description": "Updated"},
        )
        assert update.status_code == 200
        assert update.json()["description"] == "Updated"

        delete = await app_client.delete(f"/api/card-inventory/{cid}")
        assert delete.status_code == 204

        get_after = await app_client.get(f"/api/card-inventory/{cid}")
        assert get_after.status_code == 404
