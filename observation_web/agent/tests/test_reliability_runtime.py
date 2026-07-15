import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.core.base import BaseObserver, ObserverResult
from agent.core.reporter import PersistentPushQueue, Reporter
from agent.core.scheduler import Scheduler
from agent.core.state_store import StateStore
from agent.observers.process_crash import ProcessCrashObserver
from agent.utils.helpers import tail_file_cursor


class StatefulObserver(BaseObserver):
    persistent_state_fields = BaseObserver.persistent_state_fields + ('_history', '_flag')

    def __init__(self):
        super().__init__('stateful', {})
        self._flag = False

    def check(self):
        return ObserverResult(observer_name=self.name)


def test_state_store_round_trip_preserves_runtime_containers(tmp_path):
    path = tmp_path / 'state.json'
    store = StateStore(str(path), flush_interval=0.1)
    store.set('observer', {'seen': {'a'}, 'when': datetime(2026, 1, 1)})
    store.flush(force=True)

    restored = StateStore(str(path)).get('observer')
    assert restored['seen'] == {'a'}
    assert restored['when'] == datetime(2026, 1, 1)


def test_observer_state_restore_keeps_deque_limit():
    observer = StatefulObserver()
    observer.restore_state({'_last_values': {'x': 1}, '_history': [1, 2, 3], '_flag': True})
    assert isinstance(observer._history, deque)
    assert list(observer._history) == [1, 2, 3]
    assert observer._flag is True


def test_push_queue_batches_and_removes_confirmed_rows(tmp_path):
    with patch.object(PersistentPushQueue, '_send', return_value=None) as send:
        queue = PersistentPushQueue(
            'http://backend/api/ingest', 'array-1', tmp_path / 'outbox.sqlite3',
            batch_size=10,
        )
        queue.enqueue_many('metrics', [{'value': 1}, {'value': 2}])
        deadline = time.time() + 2
        while queue.stats()['pending'] and time.time() < deadline:
            time.sleep(0.02)
        assert queue.stats()['pending'] == 0
        assert send.call_count == 1
        queue.close(drain_timeout=0)


def test_reporter_cooldown_survives_restart(tmp_path):
    config = {
        'output': 'file',
        'file_path': str(tmp_path / 'alerts.log'),
        'cooldown_path': str(tmp_path / 'cooldown.json'),
        'cooldown_seconds': 300,
    }
    result = ObserverResult(observer_name='disk', has_alert=True, message='same')
    first = Reporter(config)
    first.report(result)
    first.close(0)

    second = Reporter(config)
    assert second._is_in_cooldown(result) is True
    second.close(0)


def test_metric_samples_receive_stable_identity(tmp_path):
    reporter = Reporter({
        'output': 'file',
        'file_path': str(tmp_path / 'alerts.log'),
        'cooldown_path': str(tmp_path / 'cooldown.json'),
    })
    reporter.record_metrics_batch([{'observer': 'cpu'}, {'observer': 'cpu'}])
    records = [
        json.loads(line)
        for line in (tmp_path / 'metrics.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert records[0]['sample_id']
    assert records[0]['sample_id'] != records[1]['sample_id']
    reporter.close(0)


def test_scheduler_does_not_retry_internal_type_error():
    class Broken:
        def __init__(self):
            self.calls = 0

        def check(self, reporter=None):
            self.calls += 1
            raise TypeError('internal parser error')

    observer = Broken()
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.reporter = object()
    with pytest.raises(TypeError):
        scheduler._invoke_observer(observer)
    assert observer.calls == 1


def test_scheduler_runs_independent_observers_concurrently(tmp_path):
    class Slow(StatefulObserver):
        def __init__(self, name):
            super().__init__()
            self.name = name

        def check(self):
            time.sleep(0.2)
            return ObserverResult(observer_name=self.name)

    scheduler = Scheduler.__new__(Scheduler)
    scheduler.reporter = Reporter({
        'output': 'file',
        'file_path': str(tmp_path / 'alerts.log'),
        'cooldown_path': str(tmp_path / 'cooldown.json'),
    })
    scheduler._executor = ThreadPoolExecutor(max_workers=2)
    scheduler._futures = {}
    scheduler._health = {
        'one': {'consecutive_failures': 0, 'runs': 0},
        'two': {'consecutive_failures': 0, 'runs': 0},
    }
    scheduler._state_store = StateStore(str(tmp_path / 'state.json'))
    started = time.monotonic()
    scheduler._submit_observer(Slow('one'), started)
    scheduler._submit_observer(Slow('two'), started)
    wait([entry[0] for entry in scheduler._futures.values()])
    scheduler._collect_completed()
    elapsed = time.monotonic() - started
    scheduler._executor.shutdown()
    scheduler.reporter.close(0)
    assert elapsed < 0.35
    assert scheduler._health['one']['status'] == 'ok'
    assert scheduler._health['two']['status'] == 'ok'


def test_tail_cursor_reads_new_file_from_start_after_rotation(tmp_path):
    path = tmp_path / 'messages'
    path.write_text('old\n', encoding='utf-8')
    _, cursor = tail_file_cursor(path, {}, skip_existing=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write('new-before-rotate\n')
    lines, cursor = tail_file_cursor(path, cursor)
    assert lines == ['new-before-rotate']

    path.rename(tmp_path / 'messages.1')
    path.write_text('first-after-rotate\n', encoding='utf-8')
    lines, _ = tail_file_cursor(path, cursor)
    assert lines == ['first-after-rotate']


def test_dmesg_events_are_baselined_then_deduplicated():
    observer = ProcessCrashObserver('process_crash', {'log_paths': []})
    first = 'app[1]: segfault at 0x1'
    second = 'app[2]: segfault at 0x2'
    with patch('agent.observers.process_crash.run_command') as command:
        command.return_value = (0, first, '')
        assert observer._scan_dmesg()[0] == []
        assert observer._scan_dmesg()[0] == []
        command.return_value = (0, first + '\n' + second, '')
        events, ok = observer._scan_dmesg()
    assert ok is True
    assert [event['process'] for event in events] == ['app[2]']
