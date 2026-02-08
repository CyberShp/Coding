"""Tests for Session and SessionState."""

import pytest
import time

from packet_storm.core.session import (
    Session, SessionState, SessionStats, StateTransitionError,
)


class TestSessionStats:
    """Test suite for SessionStats."""

    def test_initial_stats(self):
        """Stats start at zero."""
        stats = SessionStats()
        assert stats.packets_sent == 0
        assert stats.packets_failed == 0
        assert stats.bytes_sent == 0
        assert stats.duration == 0.0

    def test_success_rate(self):
        """Success rate calculation."""
        stats = SessionStats()
        stats.packets_sent = 80
        stats.packets_failed = 20
        assert stats.success_rate == 0.8

    def test_success_rate_zero_total(self):
        """Success rate with zero packets."""
        stats = SessionStats()
        assert stats.success_rate == 0.0

    def test_duration(self):
        """Duration calculation."""
        stats = SessionStats()
        stats.start_time = time.time() - 10
        stats.end_time = time.time()
        assert 9.5 <= stats.duration <= 11.0

    def test_to_dict(self):
        """Stats serialization."""
        stats = SessionStats()
        stats.packets_sent = 100
        stats.bytes_sent = 5000
        d = stats.to_dict()
        assert d["packets_sent"] == 100
        assert d["bytes_sent"] == 5000
        assert "duration_seconds" in d
        assert "send_rate_pps" in d


class TestSession:
    """Test suite for Session."""

    def _make_config(self) -> dict:
        return {"protocol": {"type": "iscsi"}}

    def test_session_creation(self):
        """Session starts in CREATED state."""
        session = Session(self._make_config())
        assert session.state == SessionState.CREATED
        assert session.session_id.startswith("session-")

    def test_custom_session_id(self):
        """Session accepts custom ID."""
        session = Session(self._make_config(), session_id="my-test")
        assert session.session_id == "my-test"

    def test_valid_transitions(self):
        """Valid state transitions succeed."""
        session = Session(self._make_config())
        session.transition(SessionState.CONFIGURING)
        assert session.state == SessionState.CONFIGURING
        session.transition(SessionState.READY)
        assert session.state == SessionState.READY
        session.transition(SessionState.RUNNING)
        assert session.state == SessionState.RUNNING

    def test_invalid_transition_raises(self):
        """Invalid state transition raises error."""
        session = Session(self._make_config())
        with pytest.raises(StateTransitionError):
            session.transition(SessionState.RUNNING)  # Can't go CREATED -> RUNNING

    def test_record_send(self):
        """Record packet send updates stats."""
        session = Session(self._make_config())
        session.record_send(100)
        session.record_send(200)
        assert session.stats.packets_sent == 2
        assert session.stats.bytes_sent == 300

    def test_record_failure(self):
        """Record failure updates stats and errors."""
        session = Session(self._make_config())
        session.record_failure("timeout")
        assert session.stats.packets_failed == 1
        assert "timeout" in session.stats.errors

    def test_record_anomaly(self):
        """Record anomaly updates stats."""
        session = Session(self._make_config())
        session.record_anomaly()
        session.record_anomaly()
        assert session.stats.anomalies_applied == 2

    def test_is_active(self):
        """Session.is_active reflects running/paused state."""
        session = Session(self._make_config())
        assert not session.is_active
        session.transition(SessionState.CONFIGURING)
        session.transition(SessionState.READY)
        session.transition(SessionState.RUNNING)
        assert session.is_active
        session.transition(SessionState.PAUSED)
        assert session.is_active

    def test_to_dict(self):
        """Session serialization."""
        session = Session(self._make_config(), session_id="test-001")
        d = session.to_dict()
        assert d["session_id"] == "test-001"
        assert d["state"] == "created"
        assert "stats" in d

    def test_error_allows_retry(self):
        """Error state allows transition to READY for retry."""
        session = Session(self._make_config())
        session.transition(SessionState.CONFIGURING)
        session.transition(SessionState.ERROR)
        session.transition(SessionState.READY)  # Retry
        assert session.state == SessionState.READY
