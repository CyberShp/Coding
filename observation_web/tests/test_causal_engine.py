"""
F200: Causal Inference Engine tests.

Covers episode splitting, pair mining, DAG construction,
and critically: temporal order enforcement within episodes.
"""

from datetime import datetime, timedelta

from backend.core.causal import (
    _split_episodes,
    _mine_pairs,
    build_causal_dag,
)


class FakeRule:
    """Minimal stand-in for CausalRuleModel in tests."""
    def __init__(self, ant, con, conf=0.8, lag=5.0, count=10):
        self.antecedent = ant
        self.consequent = con
        self.confidence = conf
        self.avg_lag_seconds = lag
        self.co_occurrence_count = count


BASE = datetime(2026, 4, 21, 10, 0, 0)


def _alert(id, obs, ts_offset_sec=0, **kw):
    return {
        "id": id,
        "observer_name": obs,
        "level": kw.get("level", "warning"),
        "message": kw.get("message", f"{obs} alert"),
        "timestamp": (BASE + timedelta(seconds=ts_offset_sec)).isoformat(),
    }


# ── Episode splitting ─────────────────────────────────────────

def test_episode_split_by_gap():
    alerts = [
        (BASE, "a"),
        (BASE + timedelta(seconds=10), "b"),
        (BASE + timedelta(seconds=120), "c"),  # >60s gap
    ]
    episodes = _split_episodes(alerts, gap_sec=60)
    assert len(episodes) == 2
    assert len(episodes[0]) == 2
    assert len(episodes[1]) == 1


def test_episode_single_alert():
    alerts = [(BASE, "a")]
    episodes = _split_episodes(alerts, gap_sec=60)
    assert len(episodes) == 1
    assert len(episodes[0]) == 1


def test_episode_empty():
    assert _split_episodes([], gap_sec=60) == []


# ── Pair mining ───────────────────────────────────────────────

def test_mine_pairs_ordered():
    episodes = [
        [(BASE, "disk_smart"), (BASE + timedelta(seconds=5), "alarm_type")],
    ]
    pairs = _mine_pairs(episodes)
    assert ("disk_smart", "alarm_type") in pairs
    assert ("alarm_type", "disk_smart") not in pairs


def test_mine_pairs_no_cross_episode():
    episodes = [
        [(BASE, "disk_smart")],
        [(BASE + timedelta(seconds=120), "alarm_type")],
    ]
    pairs = _mine_pairs(episodes)
    assert ("disk_smart", "alarm_type") not in pairs


# ── DAG construction — normal order ──────────────────────────

def test_dag_normal_order_linked():
    """A before B → A is root, B is consequence."""
    rules = [FakeRule("disk_smart", "alarm_type")]
    alerts = [_alert(1, "disk_smart", 0), _alert(2, "alarm_type", 10)]
    dag = build_causal_dag(alerts, rules)

    roots = [n for n in dag if n["causal_role"] == "root"]
    assert len(roots) == 1
    assert roots[0]["observer_name"] == "disk_smart"
    assert len(roots[0]["consequences"]) == 1
    assert roots[0]["consequences"][0]["observer_name"] == "alarm_type"


# ── DAG construction — reverse order (regression test) ───────

def test_dag_reverse_order_isolated():
    """B before A → both isolated, rule direction not applied."""
    rules = [FakeRule("disk_smart", "alarm_type")]
    alerts = [_alert(3, "alarm_type", 0), _alert(4, "disk_smart", 10)]
    dag = build_causal_dag(alerts, rules)

    isolated = [n for n in dag if n["causal_role"] == "isolated"]
    assert len(isolated) == 2


def test_dag_same_timestamp_isolated():
    """Same timestamp → no strict ordering → isolated."""
    rules = [FakeRule("disk_smart", "alarm_type")]
    alerts = [_alert(5, "disk_smart", 0), _alert(6, "alarm_type", 0)]
    dag = build_causal_dag(alerts, rules)

    isolated = [n for n in dag if n["causal_role"] == "isolated"]
    assert len(isolated) == 2


# ── DAG construction — cross-episode isolation ────────────────

def test_dag_cross_episode_not_linked():
    """Alerts in separate episodes are not causally linked."""
    rules = [FakeRule("disk_smart", "alarm_type")]
    alerts = [_alert(7, "disk_smart", 0), _alert(8, "alarm_type", 300)]
    dag = build_causal_dag(alerts, rules)

    isolated = [n for n in dag if n["causal_role"] == "isolated"]
    assert len(isolated) == 2


# ── DAG construction — chain A→B→C ────────────────────────────

def test_dag_three_level_chain():
    """A→B→C chain with correct temporal order."""
    rules = [
        FakeRule("disk_smart", "alarm_type"),
        FakeRule("alarm_type", "rebuild"),
    ]
    alerts = [
        _alert(10, "disk_smart", 0),
        _alert(11, "alarm_type", 10),
        _alert(12, "rebuild", 25),
    ]
    dag = build_causal_dag(alerts, rules)

    roots = [n for n in dag if n["causal_role"] == "root"]
    assert len(roots) == 1
    assert roots[0]["observer_name"] == "disk_smart"
    child = roots[0]["consequences"][0]
    assert child["observer_name"] == "alarm_type"
    assert len(child["consequences"]) == 1
    assert child["consequences"][0]["observer_name"] == "rebuild"


# ── DAG construction — no rules → all isolated ────────────────

def test_dag_no_rules():
    alerts = [_alert(20, "disk_smart", 0), _alert(21, "alarm_type", 10)]
    dag = build_causal_dag(alerts, [])
    assert all(n["causal_role"] == "isolated" for n in dag)
    assert len(dag) == 2


# ── DAG construction — multiple episodes ──────────────────────

def test_dag_multiple_episodes_independent():
    """Two separate episodes should have independent DAGs."""
    rules = [FakeRule("disk_smart", "alarm_type")]
    alerts = [
        _alert(30, "disk_smart", 0),
        _alert(31, "alarm_type", 10),
        # Episode 2 — 5 min later, only alarm_type (no disk_smart)
        _alert(32, "alarm_type", 300),
    ]
    dag = build_causal_dag(alerts, rules)

    roots = [n for n in dag if n["causal_role"] == "root"]
    isolated = [n for n in dag if n["causal_role"] == "isolated"]
    assert len(roots) == 1  # disk_smart from episode 1
    assert len(isolated) == 1  # alarm_type from episode 2
    assert isolated[0]["id"] == 32
