"""Tests for multi-user Phase 1: accounts, login, write-gate, force_unlock."""
import pytest

pytestmark = pytest.mark.asyncio


async def _register(client, nickname, password="secret123"):
    resp = await client.post(
        "/api/auth/register", json={"nickname": nickname, "password": password}
    )
    return resp


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Registration / login
# ---------------------------------------------------------------------------

class TestRegisterLogin:
    async def test_register_returns_token(self, anonymous_client):
        resp = await _register(anonymous_client, "alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"]
        assert data["nickname"] == "alice"

    async def test_first_user_is_admin_second_is_not(self, anonymous_client):
        r1 = await _register(anonymous_client, "alice")
        assert r1.json()["is_admin"] is True
        r2 = await _register(anonymous_client, "bob")
        assert r2.json()["is_admin"] is False

    async def test_duplicate_nickname_rejected(self, anonymous_client):
        await _register(anonymous_client, "alice")
        resp = await _register(anonymous_client, "alice")
        assert resp.status_code == 409

    async def test_login_success(self, anonymous_client):
        await _register(anonymous_client, "alice", "pw123456")
        resp = await anonymous_client.post(
            "/api/auth/user-login", json={"nickname": "alice", "password": "pw123456"}
        )
        assert resp.status_code == 200
        assert resp.json()["token"]

    async def test_login_wrong_password(self, anonymous_client):
        await _register(anonymous_client, "alice", "pw123456")
        resp = await anonymous_client.post(
            "/api/auth/user-login", json={"nickname": "alice", "password": "wrong"}
        )
        assert resp.status_code == 401

    async def test_login_unknown_user(self, anonymous_client):
        resp = await anonymous_client.post(
            "/api/auth/user-login", json={"nickname": "ghost", "password": "x"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# whoami / teams
# ---------------------------------------------------------------------------

class TestWhoamiTeams:
    async def test_whoami_anonymous(self, anonymous_client):
        resp = await anonymous_client.get("/api/auth/whoami")
        assert resp.status_code == 200
        assert resp.json()["anonymous"] is True

    async def test_whoami_logged_in(self, anonymous_client):
        token = (await _register(anonymous_client, "alice")).json()["token"]
        resp = await anonymous_client.get("/api/auth/whoami", headers=_auth(token))
        data = resp.json()
        assert data["anonymous"] is False
        assert data["nickname"] == "alice"
        assert data["is_admin"] is True
        assert data["teams"] == []

    async def test_set_teams_requires_login(self, anonymous_client):
        resp = await anonymous_client.put("/api/auth/me/teams", json={"tag_ids": [1]})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "login_required"

    async def test_set_teams_full_replace(self, anonymous_client):
        token = (await _register(anonymous_client, "alice")).json()["token"]
        r = await anonymous_client.put(
            "/api/auth/me/teams", json={"tag_ids": [3, 1]}, headers=_auth(token)
        )
        assert r.status_code == 200
        assert r.json()["teams"] == [1, 3]
        # full replace
        r = await anonymous_client.put(
            "/api/auth/me/teams", json={"tag_ids": [5]}, headers=_auth(token)
        )
        assert r.json()["teams"] == [5]
        who = await anonymous_client.get("/api/auth/whoami", headers=_auth(token))
        assert who.json()["teams"] == [5]


# ---------------------------------------------------------------------------
# Admin grant
# ---------------------------------------------------------------------------

class TestAdminGrant:
    async def test_grant_admin(self, anonymous_client):
        admin_token = (await _register(anonymous_client, "alice")).json()["token"]
        bob = (await _register(anonymous_client, "bob")).json()
        assert bob["is_admin"] is False

        r = await anonymous_client.post(
            f"/api/auth/admin/grant/{bob['user_id']}", headers=_auth(admin_token)
        )
        assert r.status_code == 200
        assert r.json()["is_admin"] is True

        # whoami reflects DB state even with the pre-grant token
        who = await anonymous_client.get(
            "/api/auth/whoami", headers=_auth(bob["token"])
        )
        assert who.json()["is_admin"] is True

    async def test_grant_requires_admin(self, anonymous_client):
        await _register(anonymous_client, "alice")  # admin
        bob = (await _register(anonymous_client, "bob")).json()
        carol = (await _register(anonymous_client, "carol")).json()
        r = await anonymous_client.post(
            f"/api/auth/admin/grant/{carol['user_id']}", headers=_auth(bob["token"])
        )
        assert r.status_code == 403

    async def test_grant_anonymous_401(self, anonymous_client):
        r = await anonymous_client.post("/api/auth/admin/grant/1")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Write gate on representative endpoints
# ---------------------------------------------------------------------------

class TestWriteGate:
    async def test_tags_post_anonymous_401(self, anonymous_client):
        resp = await anonymous_client.post("/api/tags", json={"name": "team-x"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "login_required"

    async def test_tags_post_logged_in_ok(self, anonymous_client):
        token = (await _register(anonymous_client, "alice")).json()["token"]
        resp = await anonymous_client.post(
            "/api/tags", json={"name": "team-x"}, headers=_auth(token)
        )
        assert resp.status_code == 201

    async def test_tags_get_open_to_anonymous(self, anonymous_client):
        resp = await anonymous_client.get("/api/tags")
        assert resp.status_code == 200

    async def test_test_tasks_post_gated(self, anonymous_client):
        payload = {"name": "t1", "task_type": "regression", "array_ids": ["a1"]}
        resp = await anonymous_client.post("/api/test-tasks", json=payload)
        assert resp.status_code == 401
        token = (await _register(anonymous_client, "alice")).json()["token"]
        resp = await anonymous_client.post(
            "/api/test-tasks", json=payload, headers=_auth(token)
        )
        assert resp.status_code == 200

    async def test_issues_post_gated_and_signed(self, anonymous_client):
        payload = {"title": "bug", "content": "something broke"}
        resp = await anonymous_client.post("/api/issues", json=payload)
        assert resp.status_code == 401
        token = (await _register(anonymous_client, "alice")).json()["token"]
        resp = await anonymous_client.post(
            "/api/issues", json=payload, headers=_auth(token)
        )
        assert resp.status_code == 200
        assert resp.json()["created_by_nickname"] == "alice"

    async def test_scheduler_delete_gated(self, anonymous_client):
        resp = await anonymous_client.delete("/api/tasks/1")
        # anonymous must be blocked before lookup
        assert resp.status_code == 401

    async def test_legacy_admin_token_passes_write_gate(self, anonymous_client):
        from backend.config import get_config
        cfg = get_config()
        login = await anonymous_client.post(
            "/api/auth/login",
            json={"username": cfg.admin.username, "password": cfg.admin.password},
        )
        assert login.status_code == 200
        token = login.json()["token"]
        resp = await anonymous_client.post(
            "/api/tags", json={"name": "legacy-made"}, headers=_auth(token)
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Ack attribution
# ---------------------------------------------------------------------------

class TestAckAttribution:
    async def test_ack_records_nickname(self, app_client_with_db):
        client, db = app_client_with_db
        from tests.conftest import create_test_array, inject_test_alert
        await create_test_array(db, "arr1")
        alert = await inject_test_alert(db, "arr1", "obs", "warning", "msg")
        await db.commit()

        token = (await _register(client, "acker")).json()["token"]
        resp = await client.post(
            "/api/alerts/ack",
            json={"alert_ids": [alert.id]},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        acks = resp.json()
        assert len(acks) == 1
        assert acks[0]["acked_by_ip"] == "acker"
        assert "user_id=" in (acks[0]["note"] or "")


# ---------------------------------------------------------------------------
# force_unlock permissions
# ---------------------------------------------------------------------------

class TestForceUnlock:
    async def _start_task(self, client, token, name="lock-test"):
        r = await client.post(
            "/api/test-tasks",
            json={"name": name, "task_type": "regression", "array_ids": ["arrX"]},
            headers=_auth(token),
        )
        assert r.status_code == 200
        task_id = r.json()["id"]
        r = await client.post(
            f"/api/test-tasks/{task_id}/start", headers=_auth(token)
        )
        assert r.status_code == 200
        return task_id

    async def test_force_unlock_anonymous_401(self, anonymous_client):
        r = await anonymous_client.delete("/api/test-tasks/locks/force/arrX")
        assert r.status_code == 401

    async def test_holder_can_force_unlock(self, anonymous_client):
        await _register(anonymous_client, "admin-first")  # absorbs auto-admin
        holder = (await _register(anonymous_client, "holder")).json()["token"]
        await self._start_task(anonymous_client, holder)
        r = await anonymous_client.delete(
            "/api/test-tasks/locks/force/arrX", headers=_auth(holder)
        )
        assert r.status_code == 200

    async def test_stranger_cannot_force_unlock(self, anonymous_client):
        await _register(anonymous_client, "admin-first")
        holder = (await _register(anonymous_client, "holder")).json()["token"]
        stranger = (await _register(anonymous_client, "stranger")).json()["token"]
        await self._start_task(anonymous_client, holder)
        r = await anonymous_client.delete(
            "/api/test-tasks/locks/force/arrX", headers=_auth(stranger)
        )
        assert r.status_code == 403

    async def test_admin_can_force_unlock(self, anonymous_client):
        admin = (await _register(anonymous_client, "admin-first")).json()["token"]
        holder = (await _register(anonymous_client, "holder")).json()["token"]
        await self._start_task(anonymous_client, holder)
        r = await anonymous_client.delete(
            "/api/test-tasks/locks/force/arrX", headers=_auth(admin)
        )
        assert r.status_code == 200
