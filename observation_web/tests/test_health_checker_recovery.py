"""Health checker regressions for SSH recovery and agent readiness."""

import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_health_checker_waits_for_ready_before_restart(monkeypatch):
    """After SSH recovers, readiness probing should happen before any forced start."""
    import backend.main as main_mod
    from backend.api import arrays as arrays_api
    from backend.core import agent_deployer as deployer_mod
    from backend.core import ssh_pool as ssh_pool_mod

    class FakeConn:
        host = "10.0.0.9"
        port = 22
        state = "connected"

        def check_alive(self):
            return True

    class FakePool:
        def get_connection(self, array_id):
            assert array_id == "arr-ready"
            return FakeConn()

    class FakeDeployer:
        instances = []

        def __init__(self, conn, config):
            self.start_calls = 0
            self.wait_calls = 0
            FakeDeployer.instances.append(self)

        def check_running(self):
            return False

        def check_deployed(self):
            return True

        async def wait_for_ready(self, timeout=1200, interval=30):
            self.wait_calls += 1
            return True

        def start_agent(self):
            self.start_calls += 1
            return {"ok": True}

        def deploy(self):
            return {"ok": True}

    class FakeSleep:
        def __init__(self):
            self.calls = 0

        async def __call__(self, seconds):
            self.calls += 1
            if self.calls >= 11:
                raise asyncio.CancelledError()

    fake_status = SimpleNamespace(host="10.0.0.9", state="connected", agent_running=True, agent_deployed=True)

    monkeypatch.setattr(main_mod, "get_ssh_pool", lambda: FakePool())
    monkeypatch.setattr(main_mod, "get_config", lambda: SimpleNamespace(remote=SimpleNamespace(auto_redeploy=True)))
    monkeypatch.setattr(main_mod.asyncio, "sleep", FakeSleep())
    monkeypatch.setattr(main_mod, "sys_warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_mod, "sys_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(ssh_pool_mod, "tcp_probe", lambda host, port, timeout=2.0: True)
    monkeypatch.setattr(deployer_mod, "AgentDeployer", FakeDeployer)
    monkeypatch.setattr(arrays_api, "_array_status_cache", {"arr-ready": fake_status})

    await main_mod._health_checker()

    assert FakeDeployer.instances
    deployer = FakeDeployer.instances[0]
    assert deployer.wait_calls == 1
    assert deployer.start_calls == 0
    assert fake_status.agent_running is True
