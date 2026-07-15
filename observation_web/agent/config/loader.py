"""
配置加载器

仅支持 JSON 格式配置文件（无需 PyYAML，便于离线 ARM 等环境）。
"""

import json
import logging
from pathlib import Path

from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ConfigLoader:
    """配置加载器"""

    # 默认配置
    DEFAULT_CONFIG = {
        'global': {
            'check_interval': 30,
            'max_memory_mb': 50,
            'subprocess_timeout': 10,
            'update_check_interval_seconds': 1800,
            'max_workers': 4,
            'health_report_interval_seconds': 30,
            'state_path': '/var/lib/observation-points/state.json',
        },
        'reporter': {
            'output': 'file',
            'file_path': '/var/log/observation-points/alerts.log',
            'syslog_facility': 'local0',
            'cooldown_seconds': 300,
            'max_alert_file_size_mb': 100,
            'alert_backup_count': 3,
            'push_timeout': 5,
            'push_queue_max': 10000,
            'push_batch_size': 100,
            'outbox_path': '/var/lib/observation-points/outbox.sqlite3',
            'cooldown_path': '/var/lib/observation-points/cooldown.json',
        },
        'observers': {
            'error_code': {
                'enabled': True,
                'interval': 30,
                'threshold': 0,
                'ports': [],
                'pcie_enabled': True,
            },
            'link_status': {
                'enabled': True,
                'interval': 5,
                'whitelist': [],
                'protocols': ['iscsi', 'nvme', 'nas'],
            },
            'card_recovery': {
                'enabled': True,
                'log_path': '/OSM/log/coffer_log/cur_debug/messages',
                'keywords': ['recovery', 'probe', 'remove'],
                'exclude_patterns': [],
            },
            'sensitive_info': {
                'enabled': True,
                'log_paths': ['/OSM/log/coffer_log/cur_debug/messages'],
                'patterns': [
                    r'password\s*[=:]\s*\S+',
                    r'passwd\s*[=:]\s*\S+',
                    r'nqn\.[a-zA-Z0-9.\-:]+',
                    r'iqn\.[a-zA-Z0-9.\-:]+',
                    r'secret\s*[=:]\s*\S+',
                ],
            },
            'custom_commands': {
                'enabled': False,
                'commands': [],
            },
            'port_fec': {
                'enabled': True,
                'interval': 60,
                'ports': [],
            },
            'port_speed': {
                'enabled': True,
                'interval': 60,
                'ports': [],
            },
            'pcie_bandwidth': {
                'enabled': True,
                'interval': 120,
                'device_filter': [],
            },
            'card_info': {
                'enabled': True,
                'interval': 120,
                'command': 'anytest intfboardallinfo',
                'running_state_expect': 'RUNNING',
                'health_state_expect': 'NORMAL',
            },
            'port_traffic': {
                'enabled': True,
                'interval': 30,
                'output_path': '/var/log/observation-points/traffic.jsonl',
                'retention_hours': 2,
                'ports': [],
            },
            'controller_state': {
                'enabled': False,
                'interval': 60,
                'command': '',
            },
            'disk_state': {
                'enabled': False,
                'interval': 60,
                'command': '',
            },
            'process_crash': {
                'enabled': True,
                'interval': 30,
                'log_paths': ['/var/log/messages', '/var/log/syslog'],
            },
            'io_timeout': {
                'enabled': True,
                'interval': 30,
                'log_paths': ['/var/log/messages', '/var/log/syslog'],
            },
            'port_error_code': {
                'enabled': True,
                'interval': 60,
                'command_list_ports': 'anytest portallinfo -t 2',
                'command_get_errors': 'anytest portgeterr -p {port_id} -n 0',
            },
            'process_restart': {
                'enabled': True,
                'interval': 30,
                'processes': ['app_data', 'devm', 'memf'],
            },
            'sfp_monitor': {
                'enabled': True,
                'interval': 120,
                'command': 'anytest sfpallinfo',
                'temp_threshold': 105,
            },
            'abnormal_reset': {
                'enabled': True,
                'interval': 120,
                'os_cli_cmd': 'os_cli',
                'inner_cmd': 'cat log_reset.txt',
                'ready_timeout': 10,
                'ready_keyword': 'succeed',
                'abnormal_reasons': [
                    'watchDog reset', 'oops reset', 'unknown reset',
                    'oom reset', 'panic reset', 'kernel reset',
                    'mce reset', 'bios reset', 'software unknown reset',
                    'failure recovery reset',
                ],
            },
            'start_work': {
                'enabled': False,
                'interval': 180,
                'command': 'anytest sysgetstartwork',
            },
        },
    }

    @classmethod
    def load(cls, config_path: Path) -> Dict[str, Any]:
        """
        加载配置文件（仅 JSON）

        Args:
            config_path: 配置文件路径

        Returns:
            合并后的配置字典
        """
        config_path = Path(config_path)

        if not config_path.exists():
            logger.warning("配置文件不存在: %s，使用默认配置", config_path)
            return cls.DEFAULT_CONFIG.copy()

        suffix = config_path.suffix.lower()
        if suffix != '.json':
            logger.warning("仅支持 .json 配置文件，当前: %s", suffix)
            return cls.DEFAULT_CONFIG.copy()

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f) or {}
        except Exception as e:
            logger.error("读取配置文件失败: %s", e)
            raise

        merged = cls._deep_merge(cls.DEFAULT_CONFIG.copy(), user_config)
        card_info = merged.get('observers', {}).get('card_info', {})
        if isinstance(card_info, dict) and not str(card_info.get('command', '')).strip():
            card_info['command'] = 'anytest intfboardallinfo'
        errors = cls.validate(merged)
        if errors:
            raise ValueError("配置校验失败: " + "; ".join(errors))
        logger.info("配置加载成功: %s", config_path)
        return merged

    @classmethod
    def _deep_merge(cls, base: Dict, override: Dict) -> Dict:
        """深度合并两个字典"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def validate(cls, config: Dict) -> List[str]:
        """验证配置有效性，返回错误消息列表"""
        errors = []
        global_cfg = config.get('global', {})
        if global_cfg.get('check_interval', 0) < 1:
            errors.append("global.check_interval 必须 >= 1")
        if global_cfg.get('subprocess_timeout', 0) < 1:
            errors.append("global.subprocess_timeout 必须 >= 1")
        if global_cfg.get('max_memory_mb', 50) < 1:
            errors.append("global.max_memory_mb 必须 >= 1")
        if not 1 <= global_cfg.get('max_workers', 4) <= 16:
            errors.append("global.max_workers 必须在 1 到 16 之间")
        reporter = config.get('reporter', {})
        if reporter.get('push_enabled') and not reporter.get('push_url'):
            errors.append("reporter.push_enabled=true 时必须配置 push_url")
        if reporter.get('push_enabled') and not str(reporter.get('array_id', '')).strip():
            errors.append("reporter.push_enabled=true 时必须配置 array_id")
        if reporter.get('push_timeout', 5) <= 0:
            errors.append("reporter.push_timeout 必须 > 0")
        observers = config.get('observers', {})
        for name, obs_config in observers.items():
            if not isinstance(obs_config, dict):
                errors.append("observers.%s 必须是字典类型" % name)
                continue
            interval = obs_config.get('interval', 0)
            if interval and interval < 1:
                errors.append("observers.%s.interval 必须 >= 1" % name)
            if name in ('card_info', 'controller_state', 'disk_state'):
                if obs_config.get('enabled') and not str(obs_config.get('command', '')).strip():
                    errors.append("observers.%s 启用时必须配置 command" % name)
        return errors
