"""Event-driven sync: arrays with a fresh push skip the redundant SSH pull.

Both the push channel and the SSH pull read the same alerts.log, so when push is
active the pull is wasted work. alert_sync._push_is_fresh gates that.
"""
from backend.api.ingest import mark_pushed, get_last_push_at, _last_push_at
from backend.core.alert_sync import _push_is_fresh


def test_mark_pushed_makes_array_fresh():
    mark_pushed("arr-fresh")
    assert get_last_push_at("arr-fresh") > 0
    assert _push_is_fresh("arr-fresh") is True


def test_never_pushed_is_not_fresh():
    _last_push_at.pop("arr-silent", None)
    assert _push_is_fresh("arr-silent") is False


def test_stale_push_is_not_fresh():
    # Simulate a push far in the past (beyond the freshness window).
    _last_push_at["arr-stale"] = 1.0  # ~1970
    assert _push_is_fresh("arr-stale") is False
