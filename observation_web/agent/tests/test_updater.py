"""Tests for core/updater.py — self-update backup retention & auto-rollback.

Regression focus: a failed/crashing update must be able to roll back to the .bak
backup instead of bricking the agent. Backups must survive until the new version
is confirmed healthy.
"""
import importlib
import json
from unittest.mock import MagicMock

import pytest

from observation_points.core.updater import AgentUpdater

# Resolve the exact module object whose globals AgentUpdater's methods read.
# (conftest aliasing can otherwise create two distinct module objects for
# observation_points.core.updater vs agent.core.updater, and patching the wrong
# one silently misses the real PENDING_UPDATE_FILE global.)
updater_mod = importlib.import_module(AgentUpdater.__module__)


@pytest.fixture
def marker(tmp_path, monkeypatch):
    """Redirect the pending-update marker to a temp file."""
    path = tmp_path / ".update_pending"
    monkeypatch.setattr(updater_mod, "PENDING_UPDATE_FILE", path)
    return path


def _updater():
    return AgentUpdater({})


class TestPendingMarker:
    def test_register_boot_noop_when_no_pending_marker(self, marker):
        # Arrange
        upd = _updater()
        upd._restart_self = MagicMock()
        # Act
        upd.register_boot()
        # Assert — normal boot untouched, no marker created
        assert not marker.exists()
        upd._restart_self.assert_not_called()

    def test_register_boot_increments_attempts_below_threshold(self, marker):
        # Arrange
        upd = _updater()
        upd._restart_self = MagicMock()
        upd._write_pending({"backup": "/x.bak", "hash": "h", "boot_attempts": 0})
        # Act
        upd.register_boot()
        # Assert — counted, but no rollback yet
        assert json.loads(marker.read_text())["boot_attempts"] == 1
        upd._restart_self.assert_not_called()

    def test_confirm_update_clears_marker_and_writes_hash(self, marker, tmp_path):
        # Arrange
        backup = tmp_path / "pkg.bak"
        backup.mkdir()
        upd = _updater()
        written = {}
        upd._write_local_hash = lambda h: written.setdefault("hash", h)
        upd._write_pending({"backup": str(backup), "hash": "abc123", "boot_attempts": 1})
        # Act
        upd.confirm_update()
        # Assert — backup deleted, hash committed, marker gone
        assert not backup.exists()
        assert written["hash"] == "abc123"
        assert not marker.exists()


class TestAutoRollback:
    def test_rollback_restores_backup_and_restarts(self, marker, tmp_path):
        """Rollback swaps the broken package for the .bak backup and re-execs."""
        # Arrange — simulate installed (broken) package + its good backup on disk
        pkg = tmp_path / "observation_points"
        pkg.mkdir()
        (pkg / "marker_new.txt").write_text("new-broken")
        backup = tmp_path / "observation_points.bak"
        backup.mkdir()
        (backup / "marker_old.txt").write_text("old-good")

        upd = _updater()
        restarted = {}
        upd._restart_self = lambda: restarted.setdefault("called", True)
        upd._write_pending({"backup": str(backup), "hash": "h", "boot_attempts": 99})

        # Act
        upd._rollback_to(str(backup), str(pkg))

        # Assert — old package restored in place, restart requested, marker cleared
        assert (pkg / "marker_old.txt").exists()
        assert not (pkg / "marker_new.txt").exists()
        assert restarted.get("called") is True
        assert not marker.exists()

    def test_register_boot_triggers_rollback_past_threshold(self, marker, tmp_path):
        """After too many unconfirmed boots register_boot() must roll back."""
        # Arrange
        pkg = tmp_path / "observation_points"
        pkg.mkdir()
        backup = tmp_path / "observation_points.bak"
        backup.mkdir()
        upd = _updater()
        upd._restart_self = MagicMock()
        # already at the threshold; this boot pushes it over
        upd._write_pending({
            "backup": str(backup),
            "hash": "h",
            "boot_attempts": updater_mod._MAX_BOOT_ATTEMPTS,
        })
        # Drive current_pkg deterministically (avoid real Path(__file__) resolution)
        orig_rollback = AgentUpdater._rollback
        AgentUpdater._rollback = lambda self, info: self._rollback_to(info.get("backup"), str(pkg))
        try:
            # Act
            upd.register_boot()
        finally:
            AgentUpdater._rollback = orig_rollback

        # Assert — rollback happened (backup consumed) and restart requested
        assert not marker.exists()
        upd._restart_self.assert_called_once()
