"""Offline acceptance using synthetic Huawei-shaped outputs; no device access."""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.core.topology_parsers import (
    TopologyParseError, parse_interfaces, parse_neighbors, parse_storage_ports, port_key,
)
from backend.core.topology_graph import build_graph
from backend.core.topology_collector import read_reply
from backend.models.topology import TopologySnapshotModel

FIXTURES = Path(__file__).parent / 'fixtures' / 'topology'

def fixture(name):
    return (FIXTURES / name).read_text()


def sample():
    now = datetime.utcnow()
    devices = [
        {'id': 'storage:a', 'name': '自定义存储名称', 'host': '192.0.2.10', 'kind': 'storage'},
        {'id': 'switch:b', 'name': '交换机 B', 'host': '192.0.2.20', 'kind': 'switch'},
        {'id': 'storage:c', 'name': '未采集存储', 'host': '192.0.2.30', 'kind': 'storage'},
    ]
    snapshots = {
        'storage:a': {'collected_at': now, 'payload': {'system_name': 'storage-a', 'ports': parse_storage_ports(fixture('oceanstor-ports.txt')), 'neighbors': []}},
        'switch:b': {'collected_at': now, 'payload': {'system_name': 'switch-b', 'chassis_id': 'aabb-ccdd-0020', 'ports': parse_interfaces(fixture('vrp-interfaces.txt')), 'neighbors': parse_neighbors(fixture('vrp-neighbors.txt'))}},
    }
    return devices, snapshots


def test_ethernet_port_parsers():
    ports = parse_interfaces(fixture('vrp-interfaces.txt'))
    assert [p['id'] for p in ports] == ['10ge1/0/1', 'ge1/0/2']
    assert ports[1]['state'] == 'down'
    ports = parse_storage_ports(fixture('oceanstor-ports.txt'))
    assert ports[0]['location'] == 'CTE0.A.IOM0'
    assert ports[0]['mac'] == 'aabbccdd0010'
    assert ports[0]['kind'] == 'card'
    assert ports[1]['kind'] == 'onboard'
    assert port_key('XGigabitEthernet 1/0/1') == '10ge1/0/1'


def test_neighbors_and_explicit_empty():
    records = parse_neighbors(fixture('vrp-neighbors.txt'))
    assert len(records) == 1
    assert records[0]['remote_address'] == '192.0.2.10'
    assert parse_neighbors('Total neighbors: 0') == []
    assert parse_neighbors('10GE1/0/1 has 0 neighbor(s):') == []


@pytest.mark.parametrize('text', ['', 'Error: Unrecognized command', '10GE1/0/1 has 2 neighbor(s):\nNeighbor index:1\nChassis ID:abc\nPort ID:xyz'])
def test_unknown_or_truncated_neighbors_are_not_empty(text):
    with pytest.raises(TopologyParseError):
        parse_neighbors(text)


def test_all_devices_and_known_link():
    devices, snaps = sample()
    graph = build_graph(devices, snaps)
    assert len(graph['devices']) == 3
    assert graph['devices'][2]['state'] == 'uncollected'
    assert len(graph['links']) == 1
    link = graph['links'][0]
    assert {link['source'], link['target']} == {'storage:a', 'switch:b'}
    assert link['state'] == 'observed'
    assert link['confirmation'] == 'unilateral'


def test_port_mac_can_resolve_storage_without_lldp_identity():
    devices, snaps = sample()
    neighbor = snaps['switch:b']['payload']['neighbors'][0]
    neighbor.update(remote_name='', remote_address='', remote_chassis='unknown-chassis', remote_port='aa:bb:cc:dd:00:10')
    link = build_graph(devices, snaps)['links'][0]
    assert link['source'] == 'storage:a'
    assert link['source_port'] == 'cte0.a.iom0.p0'


def test_bilateral_reports_are_one_cable_and_parallel_ports_remain_distinct():
    devices, snaps = sample()
    reverse = {'local_port': 'cte0.a.iom0.p0', 'remote_chassis': 'aabb-ccdd-0020', 'remote_name': 'switch-b', 'remote_address': '192.0.2.20', 'remote_port': '10GE1/0/1'}
    snaps['storage:a']['payload']['neighbors'] = [reverse]
    graph = build_graph(devices, snaps)
    assert len(graph['links']) == 1
    assert graph['links'][0]['confirmation'] == 'bilateral'
    second = copy.deepcopy(snaps['switch:b']['payload']['neighbors'][0])
    second.update(local_port='ge1/0/2', remote_port='CTE0.A.NET0.P0')
    snaps['switch:b']['payload']['neighbors'].append(second)
    assert len(build_graph(devices, snaps)['links']) == 2


def test_unrecognized_peer_not_guessed_from_subnet_or_display_name():
    devices, snaps = sample()
    neighbor = snaps['switch:b']['payload']['neighbors'][0]
    neighbor.update(remote_name='自定义存储名称', remote_address='192.0.2.99', remote_chassis='unknown', remote_port='Ethernet42')
    graph = build_graph(devices, snaps)
    assert len(graph['devices']) == 4
    assert graph['links'][0]['state'] == 'unresolved'


def test_conflicting_identity_stays_unresolved():
    devices, snaps = sample()
    snaps['switch:b']['payload']['neighbors'][0]['remote_address'] = '192.0.2.30'
    assert build_graph(devices, snaps)['links'][0]['state'] == 'unresolved'


def test_failure_or_age_preserves_but_marks_link_stale():
    devices, snaps = sample()
    snaps['switch:b']['last_error'] = 'SSH 登录失败'
    assert build_graph(devices, snaps)['links'][0]['state'] == 'stale'
    snaps['switch:b']['last_error'] = ''
    snaps['switch:b']['collected_at'] -= timedelta(minutes=6)
    assert build_graph(devices, snaps)['links'][0]['state'] == 'stale'


def test_successful_empty_neighbors_removes_old_cable():
    devices, snaps = sample()
    snaps['switch:b']['payload']['neighbors'] = []
    assert build_graph(devices, snaps)['links'] == []


class FakeChannel:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.sent = []
    def recv_ready(self):
        return bool(self.chunks)
    def recv(self, size):
        return self.chunks.pop(0)
    def sendall(self, value):
        self.sent.append(value)


def test_cli_pagination_and_prompt():
    channel = FakeChannel([b'Interface table\r\n---- More ----', b'\r\nsecond page\r\n<HUAWEI>'])
    text = read_reply(channel)
    assert 'second page' in text
    assert channel.sent == [' ']


def test_cli_timeout_does_not_return_partial_output():
    with pytest.raises(TimeoutError):
        read_reply(FakeChannel([b'partial table']), timeout=0.03)


@pytest.mark.asyncio
async def test_switch_crud_credentials_and_collection_persistence(app_client, monkeypatch):
    from backend.api import topology
    response = await app_client.post('/api/topology/switches', json={'name': 'test-switch', 'host': '192.0.2.20', 'username': 'admin', 'password': 'offline-secret'})
    assert response.status_code == 201, response.text
    device = response.json()
    assert 'offline-secret' not in response.text and 'saved_password' not in device
    assert device['has_saved_password']
    identifier = device['id']
    graph = (await app_client.get('/api/topology')).json()
    assert graph['devices'][0]['state'] == 'uncollected'
    _, snaps = sample()
    def fake_collect(row, password):
        assert password == 'offline-secret'
        return snaps['switch:b']['payload']
    monkeypatch.setattr(topology, 'collect_device', fake_collect)
    response = await app_client.post('/api/topology/collect/' + identifier)
    assert response.json()['success'], response.text
    graph = (await app_client.get('/api/topology')).json()
    assert graph['devices'][0]['ports']
    assert 'offline-secret' not in json.dumps(graph)
    def failed_collect(*args):
        raise ConnectionError('SSH 登录失败')
    monkeypatch.setattr(topology, 'collect_device', failed_collect)
    response = await app_client.post('/api/topology/collect/' + identifier)
    assert not response.json()['success']
    graph = (await app_client.get('/api/topology')).json()
    assert graph['devices'][0]['state'] == 'stale'
    assert graph['devices'][0]['ports']
    response = await app_client.put('/api/topology/switches/' + identifier, json={'name': 'new', 'host': '192.0.2.20', 'username': 'admin'})
    assert response.status_code == 200 and response.json()['has_saved_password']
    assert (await app_client.delete('/api/topology/switches/' + identifier)).status_code == 204
    assert (await app_client.get('/api/topology')).json()['devices'] == []


@pytest.mark.asyncio
async def test_write_requires_login_and_missing_device(anonymous_client, app_client):
    response = await anonymous_client.post('/api/topology/switches', json={'name':'s', 'host':'192.0.2.1', 'username':'admin'})
    assert response.status_code == 401
    assert (await app_client.post('/api/topology/collect/switch:missing')).status_code == 404


@pytest.mark.asyncio
async def test_collection_lock(app_client_with_db):
    client, db = app_client_with_db
    device = (await client.post('/api/topology/switches', json={'name':'s', 'host':'192.0.2.1', 'username':'admin'})).json()
    db.add(TopologySnapshotModel(device_id=device['id'], attempted_at=datetime.utcnow(), last_error='采集中'))
    await db.commit()
    assert (await client.post('/api/topology/collect/' + device['id'])).status_code == 409


def test_same_name_cannot_override_wrong_chassis_and_address():
    devices, snaps = sample()
    n = snaps['switch:b']['payload']['neighbors'][0]
    n.update(remote_chassis='ffffffffffff', remote_address='192.0.2.99', remote_name='storage-a')
    graph = build_graph(devices, snaps)
    assert graph['links'][0]['state'] == 'unresolved'
    assert len(graph['devices']) == 4


@pytest.mark.asyncio
async def test_storage_edit_invalidates_snapshot(app_client_with_db):
    client, db = app_client_with_db
    device = (await client.post('/api/arrays', json={'name': 'A', 'host': '192.0.2.10'})).json()
    identifier = 'storage:' + device['array_id']
    db.add(TopologySnapshotModel(device_id=identifier, payload='{"ports": []}', collected_at=datetime.utcnow()))
    await db.commit()
    response = await client.put('/api/arrays/' + device['array_id'], json={'host': '192.0.2.11'})
    assert response.status_code == 200
    result = await db.execute(select(TopologySnapshotModel).where(TopologySnapshotModel.device_id == identifier))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_manual_direct_cable_persists_and_has_separate_provenance(app_client_with_db):
    client, db = app_client_with_db
    devices = []
    for suffix in ['a', 'b']:
        device = (await client.post('/api/arrays', json={'name': suffix, 'host': '192.0.2.' + ('10' if suffix == 'a' else '11')})).json()
        identifier = 'storage:' + device['array_id']
        db.add(TopologySnapshotModel(device_id=identifier, payload=json.dumps({'ports': parse_storage_ports(fixture('oceanstor-ports.txt')), 'neighbors': []}), collected_at=datetime.utcnow()))
        devices.append(identifier)
    await db.commit()
    body = dict(source=devices[0], source_port='cte0.a.iom0.p0', target=devices[1], target_port='cte0.a.iom0.p0')
    response = await client.post('/api/topology/links', json=body)
    assert response.status_code == 201, response.text
    cable_id = response.json()['id']
    link = (await client.get('/api/topology')).json()['links'][0]
    assert link['confirmation'] == 'manual' and link['state'] == 'manual'
    assert link['evidence'][0]['source'] == '人工确认'
    assert (await client.post('/api/topology/links', json=body)).status_code == 409
    assert (await client.post('/api/topology/links', json={**body, 'source_port': 'missing'})).status_code == 422
    assert (await client.delete('/api/topology/links/' + cable_id)).status_code == 204
    assert (await client.get('/api/topology')).json()['links'] == []


def test_migration_preserves_legacy_tables_and_is_idempotent():
    import importlib.util
    from sqlalchemy import create_engine, inspect, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'backend/alembic/versions/c9a12e4d7b60_ethernet_topology.py'
    spec = importlib.util.spec_from_file_location('topology_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE legacy_data (value TEXT)'))
        conn.execute(text("INSERT INTO legacy_data VALUES ('keep')"))
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        migration.upgrade()
        assert {'topology_snapshots', 'topology_switches', 'topology_cables'} <= set(inspect(conn).get_table_names())
        assert conn.execute(text('SELECT value FROM legacy_data')).scalar() == 'keep'
        migration.downgrade()
        assert inspect(conn).get_table_names() == ['legacy_data']
    engine.dispose()


def test_watchdog_closes_client_and_rejects_late_result(monkeypatch):
    import threading
    from backend.core import topology_collector as collector
    original_timer = threading.Timer
    closed = threading.Event()
    monkeypatch.setattr(collector.threading, 'Timer', lambda seconds, callback: original_timer(0.03, callback))
    connection = collector.TopologySSHConnection('test', '192.0.2.1')
    class Client:
        def close(self):
            closed.set()
    connection._client = Client()
    def blocked(kind):
        assert closed.wait(1), 'watchdog did not close the client'
        return {'ports': []}
    monkeypatch.setattr(connection, '_collect', blocked)
    with pytest.raises(TimeoutError):
        connection.collect('switch')
    assert closed.is_set()
