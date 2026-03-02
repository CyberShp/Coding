"""
CPU 温度监测观察点

监测 CPU 和其他热区温度。
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class ThermalObserver(BaseObserver):
    """CPU 温度监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.temp_warning_celsius = config.get('temp_warning_celsius', 75)
        self.temp_critical_celsius = config.get('temp_critical_celsius', 90)
        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查温度"""
        temps = self._get_temperatures()

        if not temps:
            return self.create_result(
                has_alert=False,
                message="无法获取温度信息",
                details={'error': '未找到温度传感器'},
            )

        max_temp = max(t['temp_celsius'] for t in temps)

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'max_temp_celsius': max_temp,
                'thermal_zones': len(temps),
                'observer': self.name,
            })

        details = {
            'temperatures': temps,
            'max_temp_celsius': max_temp,
            'thresholds': {
                'warning_celsius': self.temp_warning_celsius,
                'critical_celsius': self.temp_critical_celsius,
            },
        }

        if max_temp >= self.temp_critical_celsius:
            self._was_alerting = True
            message = f"CPU 温度过高 (临界): {max_temp}°C >= {self.temp_critical_celsius}°C"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.CRITICAL,
                message=message,
                details=details,
                sticky=True,
            )

        if max_temp >= self.temp_warning_celsius:
            self._was_alerting = True
            message = f"CPU 温度偏高: {max_temp}°C >= {self.temp_warning_celsius}°C"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
                sticky=True,
            )

        if self._was_alerting:
            self._was_alerting = False
            details['recovered'] = True
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message="CPU 温度恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message=f"温度正常 (最高: {max_temp}°C)",
            details=details,
        )

    def _get_temperatures(self) -> List[Dict]:
        """获取温度信息"""
        temps = []

        thermal_path = Path('/sys/class/thermal')
        if thermal_path.exists():
            for zone in thermal_path.glob('thermal_zone*'):
                temp_file = zone / 'temp'
                type_file = zone / 'type'

                if temp_file.exists():
                    try:
                        temp_milli = int(temp_file.read_text().strip())
                        temp_celsius = temp_milli / 1000.0

                        zone_type = 'unknown'
                        if type_file.exists():
                            zone_type = type_file.read_text().strip()

                        temps.append({
                            'zone': zone.name,
                            'type': zone_type,
                            'temp_celsius': round(temp_celsius, 1),
                        })
                    except (ValueError, IOError):
                        pass

        if not temps:
            temps = self._get_temps_from_sensors()

        return temps

    def _get_temps_from_sensors(self) -> List[Dict]:
        """通过 sensors 命令获取温度"""
        temps = []
        ret, stdout, _ = run_command('sensors -u 2>/dev/null', shell=True, timeout=10)

        if ret != 0 or not stdout:
            return temps

        current_chip = 'unknown'
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            if ':' not in line and line:
                current_chip = line

            if '_input:' in line and 'temp' in line.lower():
                try:
                    value = float(line.split(':')[1].strip())
                    temps.append({
                        'zone': current_chip,
                        'type': 'sensors',
                        'temp_celsius': round(value, 1),
                    })
                except (ValueError, IndexError):
                    pass

        return temps
