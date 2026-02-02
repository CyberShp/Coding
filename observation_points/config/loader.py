"""
配置加载器

支持 YAML 和 JSON 格式的配置文件。
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 尝试导入 PyYAML，如果不存在则仅支持 JSON
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    logger.warning("PyYAML 未安装，仅支持 JSON 配置文件")


class ConfigLoader:
    """配置加载器"""
    
    # 默认配置
    DEFAULT_CONFIG = {
        'global': {
            'check_interval': 30,  # 默认检查间隔(秒)
            'max_memory_mb': 50,   # 内存上限(MB)
            'subprocess_timeout': 10,  # 子进程超时(秒)
        },
        'reporter': {
            'output': 'file',  # file, syslog, both
            'file_path': '/var/log/observation-points/alerts.log',
            'syslog_facility': 'local0',
            'cooldown_seconds': 300,  # 告警冷却时间
        },
        'observers': {
            'error_code': {
                'enabled': True,
                'interval': 30,
                'threshold': 0,  # 误码增量阈值，0表示任何新增都告警
                'ports': [],  # 空表示监控所有端口
                'pcie_enabled': True,
            },
            'link_status': {
                'enabled': True,
                'interval': 5,
                'whitelist': [],  # 白名单端口，这些端口的变化不告警
                'protocols': ['iscsi', 'nvme', 'nas'],
            },
            'card_recovery': {
                'enabled': True,
                'log_path': '/OSM/log/coffer_log/cur_debug/messages',
                'keywords': ['recovery', 'probe', 'remove'],
                'exclude_patterns': [],  # 排除的模式（如已知的故障注入）
            },
            'subhealth': {
                'enabled': True,
                'interval': 15,
                'window_size': 5,  # 滑动窗口大小
                'spike_threshold_percent': 50,  # 激增阈值百分比
                'metrics': ['latency', 'packet_loss', 'out_of_order'],
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
            'performance': {
                'enabled': True,
                'interval': 10,
                'window_size': 5,
                'fluctuation_threshold_percent': 10,
                'min_iops_threshold': 100,  # 低于此值不检测波动
                'min_bandwidth_threshold_mbps': 10,
                'metrics': ['iops', 'bandwidth', 'latency'],
                'dimensions': ['bond', 'port'],  # bond级、端口级
            },
            'custom_commands': {
                'enabled': False,
                'commands': [],  # 自定义命令列表
            },
        },
    }
    
    @classmethod
    def load(cls, config_path: Path) -> dict[str, Any]:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            合并后的配置字典
        """
        config_path = Path(config_path)
        
        if not config_path.exists():
            logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
            return cls.DEFAULT_CONFIG.copy()
        
        suffix = config_path.suffix.lower()
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                if suffix in ('.yaml', '.yml'):
                    if not HAS_YAML:
                        raise RuntimeError("需要安装 PyYAML 来解析 YAML 配置文件")
                    user_config = yaml.safe_load(f) or {}
                elif suffix == '.json':
                    user_config = json.load(f)
                else:
                    raise ValueError(f"不支持的配置文件格式: {suffix}")
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            raise
        
        # 深度合并配置
        merged = cls._deep_merge(cls.DEFAULT_CONFIG.copy(), user_config)
        
        logger.info(f"配置加载成功: {config_path}")
        return merged
    
    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        """
        深度合并两个字典
        
        Args:
            base: 基础配置
            override: 覆盖配置
            
        Returns:
            合并后的配置
        """
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    @classmethod
    def validate(cls, config: dict) -> list[str]:
        """
        验证配置有效性
        
        Args:
            config: 配置字典
            
        Returns:
            错误消息列表，空列表表示验证通过
        """
        errors = []
        
        # 验证全局配置
        global_cfg = config.get('global', {})
        if global_cfg.get('check_interval', 0) < 1:
            errors.append("global.check_interval 必须 >= 1")
        if global_cfg.get('subprocess_timeout', 0) < 1:
            errors.append("global.subprocess_timeout 必须 >= 1")
        
        # 验证观察点配置
        observers = config.get('observers', {})
        
        for name, obs_config in observers.items():
            if not isinstance(obs_config, dict):
                errors.append(f"observers.{name} 必须是字典类型")
                continue
            
            interval = obs_config.get('interval', 0)
            if interval and interval < 1:
                errors.append(f"observers.{name}.interval 必须 >= 1")
        
        return errors
