import json

import pytest

from observation_points.observers.custom_monitor import CustomMonitorObserver
from observation_points.core.runtime_receipt import (
    build_runtime_receipt,
    write_runtime_receipt,
)


def test_runtime_receipt_records_loaded_custom_observers_and_errors(tmp_path):
    config = {
        "_observer_studio": {"config_fingerprint": "sha256:abc", "revision": 7},
        "custom_monitors": [
            {"name": "healthy_custom"},
            {"name": "broken_custom"},
        ],
    }
    receipt = build_runtime_receipt(
        config,
        loaded_observers=["healthy_custom"],
        load_errors=[{"name": "broken_custom", "error": "bad strategy"}],
    )

    assert receipt["config_fingerprint"] == "sha256:abc"
    assert receipt["config_revision"] == 7
    assert receipt["loaded_observers"] == ["healthy_custom"]
    assert receipt["load_errors"][0]["name"] == "broken_custom"

    path = tmp_path / "runtime.json"
    write_runtime_receipt(path, receipt)
    assert json.loads(path.read_text())["config_fingerprint"] == "sha256:abc"


def test_custom_observer_rejects_unknown_strategy_during_agent_load():
    with pytest.raises(ValueError, match="Unknown extraction strategy"):
        CustomMonitorObserver("broken", {"command": "echo ok", "strategy": "magic"})
