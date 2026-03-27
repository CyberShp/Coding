"""
统一端口计数器监测观察点

合并自 error_code.py、port_error_code.py、network_errors.py，
统一监测 Linux sysfs 端口计数器与 anytest 端口误码。

告警分类:
- physical_error: 链路层物理误码 (CRC, FCS, frame, carrier, FC 误码等)
- drop: 丢包统计
- fifo_overrun: FIFO 队列溢出 / overrun
- generic_error: 聚合统计 (rx_errors, tx_errors, collisions)
- collector_failure: 数据采集失败
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, read_sysfs, safe_int

logger = logging.getLogger(__name__)

# ── anytest port-id regex ──────────────────────────────────────────
PORT_ID_PATTERN = re.compile(r'portId\s*[=:]\s*(0x[0-9a-fA-F]+)', re.IGNORECASE)

# ── FC card error fields (0x11 prefix) ─────────────────────────────
FC_ERROR_FIELDS = [
    ('LossOfSignal Count', 'LossOfSignal Count'),
    ('BadRXChar Count', 'BadRXChar Count'),
    ('LossOfSync Count', 'LossOfSync Count'),
    ('InvalidCRC Count', 'InvalidCRC Count'),
    ('ProtocolErr Count', 'ProtocolErr Count'),
    ('LinkFail Count', 'LinkFail Count'),
    ('LinkLoss Count', 'LinkLoss Count'),
]

# ── Ethernet card error fields (0x2 prefix) ────────────────────────
ETH_ERROR_FIELDS = [
    ('Rx Errors', 'Rx Errors'),
    ('Tx Errors', 'Tx Errors'),
    ('Rx Dropped', 'Rx Dropped'),
    ('Tx Dropped', 'Tx Dropped'),
    ('Collisions', 'Collisions'),
]

# ── sysfs counter → alert category mapping ─────────────────────────
_SYSFS_COUNTER_MAP: Dict[str, Tuple[str, AlertLevel]] = {
    # physical_error
    'rx_crc_errors':     ('physical_error', AlertLevel.WARNING),
    'fcs_errors':        ('physical_error', AlertLevel.WARNING),
    'rx_frame_errors':   ('physical_error', AlertLevel.WARNING),
    'tx_carrier_errors': ('physical_error', AlertLevel.WARNING),
    # drop
    'rx_dropped':        ('drop', AlertLevel.INFO),
    'tx_dropped':        ('drop', AlertLevel.INFO),
    # fifo_overrun
    'rx_fifo_errors':    ('fifo_overrun', AlertLevel.INFO),
    'tx_fifo_errors':    ('fifo_overrun', AlertLevel.INFO),
    'rx_missed_errors':  ('fifo_overrun', AlertLevel.INFO),
    'rx_overruns':       ('fifo_overrun', AlertLevel.INFO),
    'tx_overruns':       ('fifo_overrun', AlertLevel.INFO),
    # generic_error
    'rx_errors':         ('generic_error', AlertLevel.INFO),
    'tx_errors':         ('generic_error', AlertLevel.INFO),
    'collisions':        ('generic_error', AlertLevel.INFO),
}

_SYSFS_COUNTERS = list(_SYSFS_COUNTER_MAP.keys())

# ── anytest counter → alert category ───────────────────────────────
_ANYTEST_ETH_CATEGORY: Dict[str, str] = {
    'Rx Errors':   'generic_error',
    'Tx Errors':   'generic_error',
    'Rx Dropped':  'drop',
    'Tx Dropped':  'drop',
    'Collisions':  'generic_error',
}
_ANYTEST_FC_CATEGORY: Dict[str, str] = {
    'LossOfSignal Count': 'physical_error',
    'BadRXChar Count':    'physical_error',
    'LossOfSync Count':   'physical_error',
    'InvalidCRC Count':   'physical_error',
    'ProtocolErr Count':  'physical_error',
    'LinkFail Count':     'physical_error',
    'LinkLoss Count':     'physical_error',
}

# Single-cycle anomaly ceiling (10 million) – deltas above this are
# treated as counter resets (driver reload / card swap), not real errors.
_DEFAULT_DELTA_ANOMALY = 10_000_000


class PortCountersObserver(BaseObserver):
    """
    统一端口计数器观察点

    数据源:
    1. Linux sysfs / ethtool (原 ErrorCodeObserver + NetworkErrorsObserver)
    2. anytest portgeterr  (原 PortErrorCodeObserver)

    告警分类: physical_error, drop, fifo_overrun, generic_error,
              collector_failure
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        # ── thresholds ──────────────────────────────────────────────
        self.threshold = config.get('threshold', 0)
        self.error_rate_threshold = config.get('error_rate_threshold', 10)
        self.delta_anomaly_threshold = config.get(
            'delta_anomaly_threshold', _DEFAULT_DELTA_ANOMALY,
        )

        # ── interface filtering (sysfs source) ──────────────────────
        self.ports = config.get('ports', [])
        self.include_interfaces = config.get('include_interfaces', [])
        self.exclude_interfaces = config.get(
            'exclude_interfaces', ['lo', 'docker0', 'br-'],
        )

        # ── PCIe AER (from error_code.py) ───────────────────────────
        self.pcie_enabled = config.get('pcie_enabled', True)

        # ── anytest commands (from port_error_code.py) ──────────────
        self.anytest_enabled = config.get('anytest_enabled', True)
        self.cmd_list_ports = config.get(
            'command_list_ports', 'anytest portallinfo -t 2',
        )
        self.cmd_list_ports_fc = config.get(
            'command_list_ports_fc', 'anytest portallinfo -t 1',
        )
        self.cmd_get_errors = config.get(
            'command_get_errors', 'anytest portgeterr -p {port_id} -n 0',
        )

        # ── internal state ──────────────────────────────────────────
        self._last_sysfs: Dict[str, Dict[str, int]] = {}
        self._last_pcie: Dict[str, Dict[str, int]] = {}
        self._was_alerting = False

    # ================================================================
    #  Public interface
    # ================================================================

    def check(self) -> ObserverResult:
        alerts: List[Dict[str, Any]] = []

        # 1. Linux sysfs / ethtool counters
        alerts.extend(self._check_sysfs_counters())

        # 2. PCIe AER
        if self.pcie_enabled:
            alerts.extend(self._check_pcie_errors())

        # 3. anytest-based port counters
        if self.anytest_enabled:
            alerts.extend(self._check_anytest_counters())

        if not alerts:
            if self._was_alerting:
                self._was_alerting = False
                return self.create_result(
                    has_alert=True,
                    alert_level=AlertLevel.INFO,
                    message="端口计数器恢复正常",
                    sticky=True,
                )
            return self.create_result(
                has_alert=False,
                message="端口计数器检查正常",
            )

        self._was_alerting = True

        # Build per-category summary
        by_cat: Dict[str, List[Dict[str, Any]]] = {}
        max_level = AlertLevel.INFO
        for a in alerts:
            cat = a['category']
            by_cat.setdefault(cat, []).append(a)
            if a['level'].value > max_level.value:
                max_level = a['level']

        # Compact message – only WARNING+ categories in the message
        msg_parts: List[str] = []
        for cat, items in by_cat.items():
            cat_level = max(
                (i['level'] for i in items),
                key=lambda lv: lv.value,
            )
            if cat_level.value >= AlertLevel.WARNING.value:
                preview = '; '.join(i['message'] for i in items[:3])
                suffix = f' (共{len(items)}项)' if len(items) > 3 else ''
                msg_parts.append(f"{cat}: {preview}{suffix}")

        if not msg_parts:
            info_parts = [f"{c} {len(v)}项" for c, v in by_cat.items()]
            message = f"端口计数器: {', '.join(info_parts)}"
        else:
            message = ' | '.join(msg_parts)

        # details: only the delta records that triggered alerts
        details_list = []
        for a in alerts:
            entry: Dict[str, Any] = {
                'port': a['port'],
                'counter_name': a['counter_name'],
                'source': a['source'],
            }
            if 'previous' in a:
                entry['previous'] = a['previous']
            if 'current' in a:
                entry['current'] = a['current']
            if 'delta' in a:
                entry['delta'] = a['delta']
            if 'threshold' in a:
                entry['threshold'] = a['threshold']
            details_list.append(entry)

        return self.create_result(
            has_alert=True,
            alert_level=max_level,
            message=message,
            details={'alerts': details_list},
            sticky=True,
        )

    # ================================================================
    #  sysfs / ethtool source
    # ================================================================

    def _check_sysfs_counters(self) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        ports = self._get_sysfs_ports()

        for port in ports:
            counters = self._read_sysfs_counters(port)
            if not counters:
                continue

            last = self._last_sysfs.get(port, {})

            # First run – record baseline, no alerts
            if port not in self._last_sysfs:
                self._last_sysfs[port] = counters
                continue

            for name, value in counters.items():
                prev = last.get(name, 0)
                delta = value - prev

                if delta <= 0:
                    continue
                if delta > self.delta_anomaly_threshold:
                    logger.warning(
                        "[PortCounters] %s.%s 异常跳变 +%d，已忽略",
                        port, name, delta,
                    )
                    # Update baseline so subsequent checks don't keep warning
                    self._last_sysfs.setdefault(port, {})[name] = value
                    continue

                cat, level = _SYSFS_COUNTER_MAP.get(
                    name, ('generic_error', AlertLevel.INFO),
                )
                effective_threshold = (
                    self.error_rate_threshold
                    if cat in ('drop', 'fifo_overrun', 'generic_error')
                    else self.threshold
                )

                if delta > effective_threshold:
                    alerts.append({
                        'category': cat,
                        'level': level,
                        'message': f"{port}.{name} +{delta}",
                        'port': port,
                        'counter_name': name,
                        'previous': prev,
                        'current': value,
                        'delta': delta,
                        'threshold': effective_threshold,
                        'source': 'sysfs',
                    })

            self._last_sysfs[port] = counters

        return alerts

    def _get_sysfs_ports(self) -> List[str]:
        if self.ports:
            return self.ports

        ports: List[str] = []
        net_path = Path('/sys/class/net')
        if not net_path.exists():
            return ports

        for item in net_path.iterdir():
            name = item.name
            if self.include_interfaces and name not in self.include_interfaces:
                continue
            if any(name.startswith(p) or name == p for p in self.exclude_interfaces):
                continue
            if name.startswith(('veth', 'docker', 'eth-m', 'eno')):
                continue
            ports.append(name)

        return sorted(ports)

    def _read_sysfs_counters(self, port: str) -> Dict[str, int]:
        counters: Dict[str, int] = {}
        stats_path = Path(f'/sys/class/net/{port}/statistics')
        if stats_path.exists():
            for name in _SYSFS_COUNTERS:
                val = read_sysfs(stats_path / name)
                if val is not None:
                    counters[name] = safe_int(val)

        if not counters:
            counters = self._read_ethtool_counters(port)

        return counters

    def _read_ethtool_counters(self, port: str) -> Dict[str, int]:
        counters: Dict[str, int] = {}
        ret, stdout, _ = run_command(['ethtool', '-S', port], timeout=5)
        if ret != 0:
            return counters

        for line in stdout.split('\n'):
            line = line.strip()
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            key = key.strip().lower()
            if any(kw in key for kw in (
                'error', 'drop', 'crc', 'fifo', 'miss',
                'collision', 'carrier', 'fcs', 'frame', 'overrun',
            )):
                counters[key] = safe_int(value.strip())

        return counters

    # ================================================================
    #  PCIe AER source
    # ================================================================

    PCIE_AER_ERRORS = [
        'BadTLP', 'BadDLLP', 'CorrIntErr', 'RxErr', 'Rollover',
        'Timeout', 'NonFatalErr', 'FatalErr', 'UnsupReq',
    ]

    def _check_pcie_errors(self) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        pcie_errors = self._get_pcie_aer_errors()

        for device, errors in pcie_errors.items():
            last = self._last_pcie.get(device, {})

            if device not in self._last_pcie:
                self._last_pcie[device] = errors
                continue

            for etype, count in errors.items():
                prev = last.get(etype, 0)
                delta = count - prev
                if delta <= 0:
                    continue
                if delta > self.delta_anomaly_threshold:
                    logger.warning(
                        "[PortCounters] PCIe %s %s 异常跳变 +%d，已忽略",
                        device, etype, delta,
                    )
                    # Update baseline so subsequent checks don't keep warning
                    self._last_pcie.setdefault(device, {})[etype] = count
                    continue
                if delta > self.threshold:
                    alerts.append({
                        'category': 'physical_error',
                        'level': AlertLevel.WARNING,
                        'message': f"PCIe {device} {etype} +{delta}",
                        'port': device,
                        'counter_name': etype,
                        'previous': prev,
                        'current': count,
                        'delta': delta,
                        'threshold': self.threshold,
                        'source': 'pcie_aer',
                    })

            self._last_pcie[device] = errors

        return alerts

    def _get_pcie_aer_errors(self) -> Dict[str, Dict[str, int]]:
        result: Dict[str, Dict[str, int]] = {}
        pci_path = Path('/sys/bus/pci/devices')
        if not pci_path.exists():
            return result

        for device_path in pci_path.iterdir():
            errors: Dict[str, int] = {}
            correctable = read_sysfs(device_path / 'aer_dev_correctable')
            if correctable:
                errors.update(self._parse_aer_stats(correctable))
            uncorrectable = read_sysfs(device_path / 'aer_dev_nonfatal')
            if uncorrectable:
                errors.update(self._parse_aer_stats(uncorrectable, prefix='nonfatal_'))
            fatal = read_sysfs(device_path / 'aer_dev_fatal')
            if fatal:
                errors.update(self._parse_aer_stats(fatal, prefix='fatal_'))
            if errors:
                result[device_path.name] = errors

        return result

    @staticmethod
    def _parse_aer_stats(content: str, prefix: str = '') -> Dict[str, int]:
        errors: Dict[str, int] = {}
        for line in content.split('\n'):
            parts = line.split()
            if len(parts) >= 2:
                count = safe_int(parts[-1])
                if count > 0:
                    errors[prefix + parts[0]] = count
        return errors

    # ================================================================
    #  anytest source
    # ================================================================

    def _check_anytest_counters(self) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        try:
            ports_0x2, ports_0x11 = self._get_anytest_ports()
        except Exception as exc:
            logger.debug("[PortCounters] anytest 端口列表不可用: %s", exc)
            return alerts

        if not ports_0x2 and not ports_0x11:
            return alerts

        for port_id in ports_0x2:
            errs = self._get_anytest_eth_errors(port_id)
            for field, val in errs:
                if val > 0:
                    cat = _ANYTEST_ETH_CATEGORY.get(field, 'generic_error')
                    alerts.append({
                        'category': cat,
                        'level': AlertLevel.WARNING,
                        'message': f"{port_id} {field}: {val}",
                        'port': port_id,
                        'counter_name': field,
                        'current': val,
                        'threshold': 0,
                        'source': 'anytest',
                    })

        for port_id in ports_0x11:
            errs = self._get_anytest_fc_errors(port_id)
            for field, val in errs:
                if val > 0:
                    cat = _ANYTEST_FC_CATEGORY.get(field, 'physical_error')
                    alerts.append({
                        'category': cat,
                        'level': AlertLevel.WARNING,
                        'message': f"{port_id} {field}: {val}",
                        'port': port_id,
                        'counter_name': field,
                        'current': val,
                        'threshold': 0,
                        'source': 'anytest',
                    })

        return alerts

    def _get_anytest_ports(self) -> Tuple[List[str], List[str]]:
        ports_0x2: List[str] = []
        ports_0x11: List[str] = []

        for cmd in (self.cmd_list_ports, self.cmd_list_ports_fc):
            pipe_cmd = f"{cmd} | grep -iE 'portId' | grep -aiE '0x2|0x11'"
            ret, stdout, stderr = run_command(pipe_cmd, shell=True, timeout=15)
            if ret != 0:
                continue
            for line in stdout.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                m = PORT_ID_PATTERN.search(line)
                if not m:
                    continue
                pid = m.group(1)
                upper = pid.upper()
                if upper.startswith('0X11') and pid not in ports_0x11:
                    ports_0x11.append(pid)
                elif upper.startswith('0X2') and pid not in ports_0x2:
                    ports_0x2.append(pid)

        return ports_0x2, ports_0x11

    def _get_anytest_fc_errors(self, port_id: str) -> List[Tuple[str, int]]:
        cmd = self.cmd_get_errors.format(port_id=port_id)
        ret, stdout, _ = run_command(cmd, shell=True, timeout=10)
        if ret != 0:
            return []
        result: List[Tuple[str, int]] = []
        for display_name, field_name in FC_ERROR_FIELDS:
            pat = re.compile(
                rf'{re.escape(field_name)}\s*[=:]\s*(\d+)', re.IGNORECASE,
            )
            m = pat.search(stdout)
            if m:
                result.append((display_name, safe_int(m.group(1), 0)))
        return result

    def _get_anytest_eth_errors(self, port_id: str) -> List[Tuple[str, int]]:
        cmd = self.cmd_get_errors.format(port_id=port_id)
        ret, stdout, _ = run_command(cmd, shell=True, timeout=10)
        if ret != 0:
            return []
        result: List[Tuple[str, int]] = []
        for display_name, field_name in ETH_ERROR_FIELDS:
            pat = re.compile(
                rf'{re.escape(field_name)}\s*[=:]\s*(\d+)', re.IGNORECASE,
            )
            m = pat.search(stdout)
            if m:
                result.append((display_name, safe_int(m.group(1), 0)))
        return result
