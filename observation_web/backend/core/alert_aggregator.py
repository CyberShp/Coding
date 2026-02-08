"""
Alert Aggregation & Storm Suppression Engine.

Groups related alerts by root cause, suppresses alert storms,
and provides aggregated views for the frontend.

Aggregation rules:
- Time-window: same array + same observer within 10s → merge
- Root-cause: link_down + fec_change + speed_change on same port → group
- Storm: >20 alerts in 60s from same array → storm mode summary
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Storm detection thresholds
STORM_WINDOW_SEC = 60
STORM_THRESHOLD = 20
# Time-window aggregation
AGG_WINDOW_SEC = 10


def _extract_port_key(alert: dict) -> Optional[str]:
    """Extract port name from alert details or message."""
    details = alert.get('details') or {}
    # From changes list
    changes = details.get('changes', [])
    if changes and isinstance(changes[0], dict):
        return changes[0].get('port', '')
    # From message text
    msg = alert.get('message', '')
    m = re.search(r'(eth\d+|bond\d+|ens\w+)', msg)
    return m.group(1) if m else None


def _extract_card_key(alert: dict) -> Optional[str]:
    """Extract card identifier from alert details or message."""
    details = alert.get('details') or {}
    alerts_list = details.get('alerts', [])
    if alerts_list and isinstance(alerts_list[0], dict):
        return alerts_list[0].get('card', '')
    msg = alert.get('message', '')
    m = re.search(r'(No\d+)', msg, re.IGNORECASE)
    return m.group(1) if m else None


# Root-cause correlation groups — alerts that commonly co-occur
CORRELATION_RULES = [
    {
        'name': 'port_link_event',
        'label': '端口链路事件',
        'observers': {'link_status', 'port_fec', 'port_speed', 'error_code'},
        'key_extractor': _extract_port_key,
        'summary_template': '端口 {key} 链路事件（{count} 项关联告警）',
    },
    {
        'name': 'card_event',
        'label': '卡件异常事件',
        'observers': {'card_info', 'pcie_bandwidth', 'card_recovery'},
        'key_extractor': _extract_card_key,
        'summary_template': '卡件 {key} 异常事件（{count} 项关联告警）',
    },
]


class AggregatedAlert:
    """A group of related alerts presented as one."""

    def __init__(self, group_type: str, label: str, key: str = ''):
        self.group_type = group_type  # 'time_window' | 'root_cause' | 'storm'
        self.label = label
        self.key = key
        self.alerts: List[dict] = []
        self.earliest: Optional[datetime] = None
        self.latest: Optional[datetime] = None

    def add(self, alert: dict):
        ts = alert.get('timestamp')
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace('Z', ''))
            except (ValueError, TypeError):
                ts = datetime.now()
        elif not isinstance(ts, datetime):
            ts = datetime.now()

        self.alerts.append(alert)
        if self.earliest is None or ts < self.earliest:
            self.earliest = ts
        if self.latest is None or ts > self.latest:
            self.latest = ts

    @property
    def count(self) -> int:
        return len(self.alerts)

    @property
    def worst_level(self) -> str:
        rank = {'info': 0, 'warning': 1, 'error': 2, 'critical': 3}
        worst = 'info'
        for a in self.alerts:
            lvl = a.get('level', 'info')
            if rank.get(lvl, 0) > rank.get(worst, 0):
                worst = lvl
        return worst

    def to_dict(self) -> dict:
        return {
            'group_type': self.group_type,
            'label': self.label,
            'key': self.key,
            'count': self.count,
            'worst_level': self.worst_level,
            'earliest': self.earliest.isoformat() if self.earliest else None,
            'latest': self.latest.isoformat() if self.latest else None,
            'alerts': self.alerts,
        }


def aggregate_alerts(alerts: List[dict], array_id: str = '') -> List[dict]:
    """
    Aggregate a list of alerts using correlation rules and time-window grouping.

    Args:
        alerts: List of alert dicts (sorted by timestamp desc or asc)
        array_id: Optional array filter

    Returns:
        List of dicts — mix of individual alerts and aggregated groups.
        Aggregated groups have 'is_aggregated': True and 'group' field.
    """
    if not alerts:
        return []

    # Step 1: Detect storm
    storm_groups = _detect_storms(alerts)

    # Step 2: Apply root-cause correlation
    correlated, uncorrelated = _correlate_root_cause(alerts)

    # Step 3: Time-window aggregation on remaining
    time_grouped, remaining = _time_window_aggregate(uncorrelated)

    # Build output
    output = []

    # Storm banners first
    for sg in storm_groups:
        output.append({
            'is_aggregated': True,
            'group': sg.to_dict(),
        })

    # Root-cause groups
    for cg in correlated:
        if cg.count > 1:
            output.append({
                'is_aggregated': True,
                'group': cg.to_dict(),
            })
        else:
            output.append(cg.alerts[0])

    # Time-window groups
    for tg in time_grouped:
        if tg.count > 1:
            output.append({
                'is_aggregated': True,
                'group': tg.to_dict(),
            })
        else:
            output.append(tg.alerts[0])

    # Remaining individual alerts
    output.extend(remaining)

    # Sort by timestamp (newest first)
    def _sort_key(item):
        if item.get('is_aggregated'):
            return item['group'].get('latest', '')
        return item.get('timestamp', '')

    output.sort(key=_sort_key, reverse=True)
    return output


def _detect_storms(alerts: List[dict]) -> List[AggregatedAlert]:
    """Detect alert storms: >STORM_THRESHOLD alerts in STORM_WINDOW_SEC."""
    storms = []
    # Group by array_id
    by_array = defaultdict(list)
    for a in alerts:
        by_array[a.get('array_id', '')].append(a)

    for arr_id, arr_alerts in by_array.items():
        if len(arr_alerts) < STORM_THRESHOLD:
            continue

        # Parse timestamps and check windows
        timed = []
        for a in arr_alerts:
            ts = a.get('timestamp', '')
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace('Z', ''))
                except (ValueError, TypeError):
                    continue
            timed.append((ts, a))

        timed.sort(key=lambda x: x[0])

        # Sliding window
        i = 0
        for j in range(len(timed)):
            while (timed[j][0] - timed[i][0]).total_seconds() > STORM_WINDOW_SEC:
                i += 1
            window_size = j - i + 1
            if window_size >= STORM_THRESHOLD:
                sg = AggregatedAlert(
                    'storm',
                    f'告警风暴：{arr_id} 在 {STORM_WINDOW_SEC}s 内产生 {window_size} 条告警',
                )
                for k in range(i, j + 1):
                    sg.add(timed[k][1])
                storms.append(sg)
                break  # One storm per array is enough

    return storms


def _correlate_root_cause(alerts: List[dict]) -> tuple:
    """Group alerts by root-cause correlation rules."""
    correlated_groups = []
    used_indices = set()

    for rule in CORRELATION_RULES:
        # Find alerts matching this rule's observers
        candidates = []
        for idx, a in enumerate(alerts):
            if idx in used_indices:
                continue
            if a.get('observer_name', '') in rule['observers']:
                candidates.append((idx, a))

        if len(candidates) < 2:
            continue

        # Group by extracted key
        by_key = defaultdict(list)
        for idx, a in candidates:
            key = rule['key_extractor'](a)
            if key:
                by_key[key].append((idx, a))

        for key, items in by_key.items():
            if len(items) < 2:
                continue
            # Check time proximity (within 30s)
            timestamps = []
            for idx, a in items:
                ts = a.get('timestamp', '')
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace('Z', ''))
                    except (ValueError, TypeError):
                        ts = datetime.now()
                timestamps.append(ts)

            if timestamps:
                time_span = (max(timestamps) - min(timestamps)).total_seconds()
                if time_span <= 30:
                    label = rule['summary_template'].format(key=key, count=len(items))
                    group = AggregatedAlert('root_cause', label, key)
                    for idx, a in items:
                        group.add(a)
                        used_indices.add(idx)
                    correlated_groups.append(group)

    uncorrelated = [a for idx, a in enumerate(alerts) if idx not in used_indices]
    return correlated_groups, uncorrelated


def _time_window_aggregate(alerts: List[dict]) -> tuple:
    """Group alerts from same observer within AGG_WINDOW_SEC."""
    groups = []
    used = set()

    for i, a in enumerate(alerts):
        if i in used:
            continue

        ts_a = _parse_ts(a)
        if ts_a is None:
            continue

        obs = a.get('observer_name', '')
        arr = a.get('array_id', '')

        group = AggregatedAlert(
            'time_window',
            f'{obs} {AGG_WINDOW_SEC}s 内连续触发',
        )
        group.add(a)
        used.add(i)

        for j in range(i + 1, len(alerts)):
            if j in used:
                continue
            b = alerts[j]
            if b.get('observer_name') != obs or b.get('array_id') != arr:
                continue
            ts_b = _parse_ts(b)
            if ts_b is None:
                continue
            if abs((ts_b - ts_a).total_seconds()) <= AGG_WINDOW_SEC:
                group.add(b)
                used.add(j)

        groups.append(group)

    remaining = [a for i, a in enumerate(alerts) if i not in used]
    return groups, remaining


def _parse_ts(alert: dict) -> Optional[datetime]:
    ts = alert.get('timestamp', '')
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace('Z', ''))
        except (ValueError, TypeError):
            return None
    return None
