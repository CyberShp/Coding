"""F208 custom observer studio contract tests."""

from unittest.mock import MagicMock

import pytest

from backend.api.auth import _create_token
from backend.core.custom_observer_deployer import (
    AGENT_CONFIG_PATH,
    AGENT_RUNTIME_RECEIPT_PATH,
    deploy_agent_config,
    fingerprint_custom_monitors,
)
from backend.core.monitor_template_service import (
    desired_monitors_for_array,
    resolve_assignment_arrays,
    template_to_agent_config,
)
from backend.models.array import ArrayModel
from backend.models.monitor_template import MonitorAssignmentModel, MonitorTemplateModel
from backend.models.tag import ArrayTagModel, TagModel


def _admin_headers():
    return {"Authorization": f"Bearer {_create_token('admin')}"}


def _template_payload(**overrides):
    payload = {
        "name": "controller_health",
        "description": "检查控制器状态",
        "command": "anytest controllerallinfo",
        "command_type": "shell",
        "interval": 30,
        "timeout": 10,
        "match_type": "lines",
        "match_expression": '{"pattern":"offline","mode":"count"}',
        "match_condition": "gt",
        "match_threshold": "0",
        "alert_level": "error",
        "alert_message_template": "发现 {value} 个离线控制器",
        "cooldown": 120,
        "consecutive_threshold": 2,
        "visibility": "team",
        "team_scope": "storage-test",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_template_update_creates_immutable_version_history(app_client):
    created = await app_client.post(
        "/api/admin/monitor-templates",
        json=_template_payload(),
        headers=_admin_headers(),
    )
    assert created.status_code == 200, created.text
    template = created.json()
    assert template["version"] == 1
    assert template["visibility"] == "team"
    assert template["template_key"]

    updated = await app_client.put(
        f"/api/admin/monitor-templates/{template['id']}",
        json={"command": "anytest controllerallinfo --detail"},
        headers=_admin_headers(),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2

    history = await app_client.get(
        f"/api/admin/monitor-templates/{template['id']}/versions",
        headers=_admin_headers(),
    )
    assert history.status_code == 200, history.text
    versions = history.json()
    assert [item["version"] for item in versions] == [2, 1]
    assert versions[0]["snapshot"]["command"].endswith("--detail")
    assert versions[1]["snapshot"]["command"] == "anytest controllerallinfo"

    restored = await app_client.post(
        f"/api/admin/monitor-templates/{template['id']}/versions/1/restore",
        headers=_admin_headers(),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["version"] == 3
    assert restored.json()["command"] == "anytest controllerallinfo"
    history = await app_client.get(
        f"/api/admin/monitor-templates/{template['id']}/versions",
        headers=_admin_headers(),
    )
    versions = history.json()
    assert [item["version"] for item in versions] == [3, 2, 1]
    assert versions[1]["snapshot"]["command"].endswith("--detail")


@pytest.mark.asyncio
async def test_listing_repairs_legacy_template_identity_and_version(app_client_with_db):
    client, db = app_client_with_db
    from backend.models.monitor_template import MonitorTemplateModel

    legacy = MonitorTemplateModel(
        name="legacy_custom",
        command="echo ok",
        match_expression="{}",
        template_key=None,
        config_fingerprint="",
    )
    db.add(legacy)
    await db.commit()

    response = await client.get(
        "/api/admin/monitor-templates",
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    repaired = response.json()[0]
    assert repaired["template_key"].startswith("obs_")
    versions = await client.get(
        f"/api/admin/monitor-templates/{repaired['id']}/versions",
        headers=_admin_headers(),
    )
    assert [item["version"] for item in versions.json()] == [1]


@pytest.mark.asyncio
async def test_assignment_is_persistent_and_idempotent(app_client):
    created = await app_client.post(
        "/api/admin/monitor-templates",
        json=_template_payload(),
        headers=_admin_headers(),
    )
    template_id = created.json()["id"]

    for _ in range(2):
        response = await app_client.put(
            f"/api/admin/monitor-templates/{template_id}/assignments",
            json={"target_type": "array", "target_ids": [11, 12]},
            headers=_admin_headers(),
        )
        assert response.status_code == 200, response.text

    assignments = await app_client.get(
        f"/api/admin/monitor-templates/{template_id}/assignments",
        headers=_admin_headers(),
    )
    assert assignments.status_code == 200
    assert [(item["target_type"], item["target_id"]) for item in assignments.json()] == [
        ("array", 11),
        ("array", 12),
    ]
    assert all(item["status"] == "pending" for item in assignments.json())

    replaced = await app_client.put(
        f"/api/admin/monitor-templates/{template_id}/assignments",
        json={"target_type": "tag", "target_ids": [7]},
        headers=_admin_headers(),
    )
    assert replaced.status_code == 200
    assignments = await app_client.get(
        f"/api/admin/monitor-templates/{template_id}/assignments",
        headers=_admin_headers(),
    )
    assert [(item["target_type"], item["target_id"]) for item in assignments.json()] == [
        ("tag", 7),
    ]


@pytest.mark.asyncio
async def test_reassignment_reconciles_old_array_and_reports_removal(
    app_client_with_db,
    monkeypatch,
):
    client, db = app_client_with_db
    first = ArrayModel(array_id="array-reconcile-a", name="first", host="10.8.1.1")
    second = ArrayModel(array_id="array-reconcile-b", name="second", host="10.8.1.2")
    db.add_all([first, second])
    await db.commit()
    await db.refresh(first)
    await db.refresh(second)
    created = await client.post(
        "/api/admin/monitor-templates",
        json=_template_payload(),
        headers=_admin_headers(),
    )
    template_id = created.json()["id"]
    captured_plans = []

    async def fake_deploy(plans):
        captured_plans.append(plans)
        return [
            {
                "array_id": array_id,
                "ok": True,
                "status": "active",
                "desired_hash": f"hash:{array_id}",
                "loaded_hash": f"hash:{array_id}",
            }
            for array_id in plans
        ]

    monkeypatch.setattr("backend.api.monitor_deployments._deploy_plans", fake_deploy)
    first_deploy = await client.post(
        "/api/admin/monitor-templates/deploy",
        json={"template_ids": [template_id], "target_type": "array", "target_ids": [first.id]},
        headers=_admin_headers(),
    )
    assert first_deploy.status_code == 200, first_deploy.text
    moved = await client.post(
        "/api/admin/monitor-templates/deploy",
        json={"template_ids": [template_id], "target_type": "array", "target_ids": [second.id]},
        headers=_admin_headers(),
    )
    assert moved.status_code == 200, moved.text

    assert set(captured_plans[-1]) == {first.array_id, second.array_id}
    assert captured_plans[-1][first.array_id] == []
    # Phase 2: agent instance names carry an @owner suffix so same-name monitors
    # from different owners coexist on one array (creator here is legacy admin).
    assert [item["name"] for item in captured_plans[-1][second.array_id]] == ["controller_health@admin"]
    deployments = await client.get(
        f"/api/admin/monitor-templates/{template_id}/deployments",
        headers=_admin_headers(),
    )
    states = {item["array_id"]: item["status"] for item in deployments.json()}
    assert states == {first.array_id: "removed", second.array_id: "active"}
    assignments = await client.get(
        f"/api/admin/monitor-templates/{template_id}/assignments",
        headers=_admin_headers(),
    )
    assert [(item["target_type"], item["target_id"]) for item in assignments.json()] == [
        ("array", second.id),
    ]


@pytest.mark.asyncio
async def test_tag_assignment_resolves_many_to_many_array_tags(db_session):
    tag = TagModel(name="multi-tag", level=2)
    array = ArrayModel(array_id="array-multi-tag", name="array", host="10.8.0.1")
    template = MonitorTemplateModel(
        name="multi_tag_observer",
        command="echo ok",
        match_expression="{}",
        template_key="obs_multi_tag",
        version=1,
    )
    db_session.add_all([tag, array, template])
    await db_session.flush()
    db_session.add(ArrayTagModel(array_id=array.array_id, tag_id=tag.id))
    assignment = MonitorAssignmentModel(
        template_id=template.id,
        target_type="tag",
        target_id=tag.id,
        desired_version=1,
        created_by="admin",
    )
    db_session.add(assignment)
    await db_session.commit()

    resolved = await resolve_assignment_arrays(db_session, [assignment])
    desired = await desired_monitors_for_array(db_session, array.array_id)

    assert list(resolved) == [array.array_id]
    assert resolved[array.array_id][0].template_id == template.id
    assert [item["name"] for item in desired] == [template.name]
    assert desired[0]["template_key"] == "obs_multi_tag"


def test_legacy_regex_template_is_normalized_before_agent_deployment():
    template = MonitorTemplateModel(
        id=9,
        name="legacy_regex",
        command="cat /proc/loadavg",
        match_type="regex",
        match_expression="([0-9.]+)",
        template_key="obs_legacy_regex",
        version=1,
    )

    config = template_to_agent_config(template)

    assert config["strategy"] == "lines"
    assert config["strategy_config"] == {"pattern": "([0-9.]+)", "mode": "first"}
    assert config["match_type"] == "lines"


def test_config_deploy_is_atomic_and_requires_matching_agent_receipt():
    monitors = [{"name": "controller_health", "template_version": 2}]
    expected_hash = fingerprint_custom_monitors(monitors)
    conn = MagicMock()
    conn.is_connected.return_value = True
    conn.read_file.side_effect = [
        '{"reporter":{"backend_url":"http://backend"}}',
        '{"config_fingerprint":"wrong","loaded_observers":[],"load_errors":[]}',
    ]
    conn.execute.return_value = (0, "", "")

    result = deploy_agent_config(conn, monitors, restart=lambda: {"ok": True})

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["desired_hash"] == expected_hash
    commands = [call.args[0] for call in conn.execute.call_args_list]
    assert any(f"{AGENT_CONFIG_PATH}.tmp" in cmd for cmd in commands)
    assert any("json.load" in cmd for cmd in commands)
    assert any(f"mv {AGENT_CONFIG_PATH}.tmp {AGENT_CONFIG_PATH}" in cmd for cmd in commands)
    conn.read_file.assert_any_call(AGENT_RUNTIME_RECEIPT_PATH)


def test_config_deploy_reports_loaded_only_for_exact_receipt():
    monitors = [{"name": "controller_health", "template_version": 3}]
    expected_hash = fingerprint_custom_monitors(monitors)
    conn = MagicMock()
    conn.is_connected.return_value = True
    conn.read_file.side_effect = [
        "{}",
        '{"config_fingerprint":"%s","loaded_observers":["controller_health"],"load_errors":[]}'
        % expected_hash,
    ]
    conn.execute.return_value = (0, "", "")

    result = deploy_agent_config(conn, monitors, restart=lambda: {"ok": True})

    assert result["ok"] is True
    assert result["status"] == "active"
    assert result["loaded_hash"] == expected_hash
