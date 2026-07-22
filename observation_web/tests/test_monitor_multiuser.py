"""Multi-user Phase 2 (backend): custom-monitor ownership, visibility,
owner permissions, publish lifecycle, health dashboard, and same-array
same-name coexistence.

Uses the Phase 1 user fixtures (anonymous_client / app_client_with_db /
db_session) and builds two users in different L1-tag teams to prove isolation.
"""
import json

import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/admin/monitor-templates"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _register(client, nickname, password="secret123"):
    r = await client.post(
        "/api/auth/register", json={"nickname": nickname, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _set_teams(client, token, tag_ids):
    r = await client.put(
        "/api/auth/me/teams", json={"tag_ids": tag_ids}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text


def _template_payload(name="cpu_watch", **overrides):
    payload = {
        "name": name,
        "description": "watch cpu",
        "command": "cat /proc/loadavg",
        "command_type": "shell",
        "match_type": "lines",
        "match_expression": '{"pattern":"x","mode":"count"}',
        "match_condition": "gt",
        "match_threshold": "0",
        "alert_level": "warning",
        "visibility": "team",
    }
    payload.update(overrides)
    return payload


async def _create(client, token, **overrides):
    r = await client.post(
        BASE, json=_template_payload(**overrides), headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _list_ids(client, token=None):
    headers = _auth(token) if token else {}
    r = await client.get(BASE, headers=headers)
    assert r.status_code == 200, r.text
    return {t["id"] for t in r.json()}


@pytest.fixture
async def two_teams(anonymous_client):
    """Absorb the auto-admin, then build alice(team 10) and bob(team 20)."""
    client = anonymous_client
    await _register(client, "root-admin")  # first user becomes admin, discarded
    alice = await _register(client, "alice")
    bob = await _register(client, "bob")
    await _set_teams(client, alice["token"], [10])
    await _set_teams(client, bob["token"], [20])
    return client, alice, bob


# ---------------------------------------------------------------------------
# Ownership / creation attribution
# ---------------------------------------------------------------------------

class TestCreationAttribution:
    async def test_create_records_nickname_owner_and_team_scope(self, two_teams):
        client, alice, _ = two_teams
        tmpl = await _create(client, alice["token"], name="own1")
        assert tmpl["created_by"] == "alice"
        assert tmpl["owner_user_id"] == alice["user_id"]
        assert tmpl["team_scope"] == "10"  # first L1 tag of alice
        assert tmpl["visibility"] == "team"

    async def test_create_requires_login(self, anonymous_client):
        r = await anonymous_client.post(BASE, json=_template_payload())
        assert r.status_code == 401

    async def test_invalid_visibility_rejected(self, two_teams):
        client, alice, _ = two_teams
        r = await client.post(
            BASE, json=_template_payload(visibility="private"), headers=_auth(alice["token"])
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Visibility filtering (global / team / draft + cross-group isolation)
# ---------------------------------------------------------------------------

class TestVisibility:
    async def test_global_visible_to_other_team(self, two_teams):
        client, alice, bob = two_teams
        g = await _create(client, alice["token"], name="glob", visibility="global")
        assert g["id"] in await _list_ids(client, bob["token"])

    async def test_team_hidden_from_other_team(self, two_teams):
        client, alice, bob = two_teams
        t = await _create(client, alice["token"], name="team-a", visibility="team")
        # alice (owner, team 10) sees it; bob (team 20) does not
        assert t["id"] in await _list_ids(client, alice["token"])
        assert t["id"] not in await _list_ids(client, bob["token"])

    async def test_team_visible_to_same_team_member(self, two_teams):
        client, alice, _ = two_teams
        carol = await _register(client, "carol")
        await _set_teams(client, carol["token"], [10])  # same team as alice
        t = await _create(client, alice["token"], name="team-shared", visibility="team")
        assert t["id"] in await _list_ids(client, carol["token"])

    async def test_draft_private_to_owner_only(self, two_teams):
        client, alice, bob = two_teams
        d = await _create(client, alice["token"], name="draft1", visibility="draft")
        assert d["id"] in await _list_ids(client, alice["token"])
        assert d["id"] not in await _list_ids(client, bob["token"])

    async def test_anonymous_sees_only_global(self, two_teams):
        client, alice, _ = two_teams
        g = await _create(client, alice["token"], name="pub", visibility="global")
        t = await _create(client, alice["token"], name="priv", visibility="team")
        anon_ids = await _list_ids(client)  # no token
        assert g["id"] in anon_ids
        assert t["id"] not in anon_ids


# ---------------------------------------------------------------------------
# Owner permission on mutation
# ---------------------------------------------------------------------------

class TestOwnerPermission:
    async def test_non_owner_cannot_update(self, two_teams):
        client, alice, bob = two_teams
        t = await _create(client, alice["token"], name=" up")
        r = await client.put(
            f"{BASE}/{t['id']}",
            json={"description": "hacked"},
            headers=_auth(bob["token"]),
        )
        assert r.status_code == 403

    async def test_non_owner_cannot_delete(self, two_teams):
        client, alice, bob = two_teams
        t = await _create(client, alice["token"], name="del")
        r = await client.delete(f"{BASE}/{t['id']}", headers=_auth(bob["token"]))
        assert r.status_code == 403

    async def test_owner_can_update_and_delete(self, two_teams):
        client, alice, _ = two_teams
        t = await _create(client, alice["token"], name="mine")
        up = await client.put(
            f"{BASE}/{t['id']}",
            json={"description": "edited"},
            headers=_auth(alice["token"]),
        )
        assert up.status_code == 200
        assert up.json()["description"] == "edited"
        dl = await client.delete(f"{BASE}/{t['id']}", headers=_auth(alice["token"]))
        assert dl.status_code == 200

    async def test_admin_can_update_others(self, two_teams):
        client, alice, _ = two_teams
        admin = await _register(client, "super")
        # grant admin via the first (root-admin) is not available; make 'super'
        # admin through the root admin instead.
        root = await client.post(
            "/api/auth/user-login", json={"nickname": "root-admin", "password": "secret123"}
        )
        root_token = root.json()["token"]
        g = await client.post(
            f"/api/auth/admin/grant/{admin['user_id']}", headers=_auth(root_token)
        )
        assert g.status_code == 200
        t = await _create(client, alice["token"], name="admin-edit")
        up = await client.put(
            f"{BASE}/{t['id']}",
            json={"description": "by admin"},
            headers=_auth(admin["token"]),
        )
        assert up.status_code == 200


# ---------------------------------------------------------------------------
# Publish lifecycle
# ---------------------------------------------------------------------------

class TestPublish:
    async def test_publish_upgrade_draft_to_team_to_global(self, two_teams):
        client, alice, _ = two_teams
        t = await _create(client, alice["token"], name="lifecycle", visibility="draft")
        r1 = await client.post(
            f"{BASE}/{t['id']}/publish", json={"visibility": "team"},
            headers=_auth(alice["token"]),
        )
        assert r1.status_code == 200
        assert r1.json()["visibility"] == "team"
        r2 = await client.post(
            f"{BASE}/{t['id']}/publish", json={"visibility": "global"},
            headers=_auth(alice["token"]),
        )
        assert r2.status_code == 200
        assert r2.json()["visibility"] == "global"

    async def test_publish_downgrade_rejected(self, two_teams):
        client, alice, _ = two_teams
        t = await _create(client, alice["token"], name="nodowngrade", visibility="global")
        r = await client.post(
            f"{BASE}/{t['id']}/publish", json={"visibility": "team"},
            headers=_auth(alice["token"]),
        )
        assert r.status_code == 400

    async def test_publish_by_non_owner_forbidden(self, two_teams):
        client, alice, bob = two_teams
        t = await _create(client, alice["token"], name="notyours", visibility="draft")
        r = await client.post(
            f"{BASE}/{t['id']}/publish", json={"visibility": "global"},
            headers=_auth(bob["token"]),
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Health dashboard
# ---------------------------------------------------------------------------

class TestHealth:
    async def test_health_returns_structure_with_last_alert(self, app_client_with_db):
        client, db = app_client_with_db
        from datetime import datetime
        from tests.conftest import create_test_array, inject_test_alert
        from backend.models.monitor_template import (
            MonitorAssignmentModel,
            MonitorDeploymentModel,
            MonitorTemplateModel,
        )

        await create_test_array(db, "arrH")
        tmpl = MonitorTemplateModel(
            name="health_obs", command="echo ok", match_expression="{}",
            template_key="obs_health", version=1, created_by="deployer1",
        )
        db.add(tmpl)
        await db.flush()
        assignment = MonitorAssignmentModel(
            template_id=tmpl.id, target_type="array", target_id=1,
            desired_version=1, created_by="deployer1",
        )
        db.add(assignment)
        await db.flush()
        db.add(MonitorDeploymentModel(
            assignment_id=assignment.id, template_id=tmpl.id, array_id="arrH",
            desired_version=1, status="active", confirmed_at=datetime.now(),
        ))
        # Alert stamped with the originating template_id in details.
        await inject_test_alert(
            db, "arrH", "health_obs@deployer1", "warning", "boom",
            details={"custom_observer": True, "template_id": tmpl.id},
        )
        await db.commit()

        r = await client.get(f"{BASE}/health")
        assert r.status_code == 200, r.text
        rows = [row for row in r.json() if row["template_id"] == tmpl.id]
        assert len(rows) == 1
        row = rows[0]
        assert row["template_name"] == "health_obs"
        assert row["array_id"] == "arrH"
        assert row["deployed_by"] == "deployer1"
        assert row["version"] == 1
        assert row["status"] == "active"
        assert row["confirmed_at"] is not None
        assert row["last_alert_at"] is not None

    async def test_health_requires_login(self, anonymous_client):
        r = await anonymous_client.get(f"{BASE}/health")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Same-array same-name coexistence (@owner suffix)
# ---------------------------------------------------------------------------

class TestCoexistence:
    async def test_same_name_different_owners_get_distinct_suffixed_names(self, db_session):
        from backend.models.array import ArrayModel
        from backend.models.monitor_template import (
            MonitorAssignmentModel,
            MonitorTemplateModel,
        )
        from backend.core.monitor_template_service import desired_monitors_for_array

        array = ArrayModel(array_id="arr-coexist", name="a", host="10.0.0.1")
        t_alice = MonitorTemplateModel(
            name="disk_check", command="df", match_expression="{}",
            template_key="obs_alice", version=1, created_by="alice",
        )
        t_bob = MonitorTemplateModel(
            name="disk_check", command="df", match_expression="{}",
            template_key="obs_bob", version=1, created_by="bob",
        )
        db_session.add_all([array, t_alice, t_bob])
        await db_session.flush()
        db_session.add_all([
            MonitorAssignmentModel(
                template_id=t_alice.id, target_type="array", target_id=array.id,
                desired_version=1, created_by="alice",
            ),
            MonitorAssignmentModel(
                template_id=t_bob.id, target_type="array", target_id=array.id,
                desired_version=1, created_by="bob",
            ),
        ])
        await db_session.commit()

        desired = await desired_monitors_for_array(db_session, "arr-coexist")
        names = sorted(item["name"] for item in desired)
        # Same base name coexists thanks to the @owner suffix.
        assert names == ["disk_check@alice", "disk_check@bob"]
        # Alerts carry their source owner via the suffixed observer name.
        for item in desired:
            assert item["deployed_by"] in {"alice", "bob"}
