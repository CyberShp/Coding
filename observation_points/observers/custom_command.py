"""
自定义命令观察点

支持通过配置添加内部命令作为观察点。
便于扩展和调用内部工具进行监测。
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class CustomCommandObserver(BaseObserver):
    """
    自定义命令观察点
    
    功能：
    - 执行配置的内部命令
    - 解析命令输出
    - 根据条件触发告警
    
    配置示例：
    ```yaml
    custom_commands:
      enabled: true
      commands:
        - name: check_port_health
          command: /opt/internal/check_port.sh
          interval: 30
          timeout: 10
          parse_type: json  # json, key_value, regex, raw
          alert_conditions:
            - field: status
              operator: '!='
              value: 'OK'
              level: error
        - name: check_firmware
          command: /opt/internal/fw_version.sh
          interval: 3600
          parse_type: key_value
          alert_conditions:
            - field: version
              operator: contains
              value: 'BETA'
              level: warning
    ```
    """
    
    OPERATORS = {
        '==': lambda a, b: str(a) == str(b),
        '!=': lambda a, b: str(a) != str(b),
        '>': lambda a, b: float(a) > float(b),
        '>=': lambda a, b: float(a) >= float(b),
        '<': lambda a, b: float(a) < float(b),
        '<=': lambda a, b: float(a) <= float(b),
        'contains': lambda a, b: str(b).lower() in str(a).lower(),
        'not_contains': lambda a, b: str(b).lower() not in str(a).lower(),
        'matches': lambda a, b: bool(re.search(b, str(a))),
        'not_matches': lambda a, b: not bool(re.search(b, str(a))),
    }
    
    def __init__(self, name: str, config: dict[str, Any]):
        super().__init__(name, config)
        
        self.commands = config.get('commands', [])
        self.default_timeout = config.get('default_timeout', 10)
        
        # 白名单：允许执行的命令路径前缀
        self.allowed_paths = config.get('allowed_paths', [
            '/opt/',
            '/usr/local/bin/',
            '/OSM/',
        ])
        
        # 每个命令的上次执行时间和结果
        self._last_run: dict[str, dict[str, Any]] = {}
        
        # 验证命令配置
        self._validate_commands()
    
    def _validate_commands(self):
        """验证命令配置的安全性"""
        validated = []
        
        for cmd_config in self.commands:
            cmd_name = cmd_config.get('name', 'unnamed')
            command = cmd_config.get('command', '')
            
            if not command:
                logger.warning(f"命令 {cmd_name} 未配置 command，跳过")
                continue
            
            # 安全检查：命令路径白名单
            cmd_path = command.split()[0] if command else ''
            is_allowed = any(cmd_path.startswith(p) for p in self.allowed_paths)
            
            if not is_allowed and not cmd_config.get('allow_any_path', False):
                logger.warning(f"命令 {cmd_name} 的路径 {cmd_path} 不在白名单中，跳过")
                continue
            
            validated.append(cmd_config)
        
        self.commands = validated
        logger.info(f"已验证 {len(validated)} 个自定义命令")
    
    def check(self) -> ObserverResult:
        """执行自定义命令检查"""
        if not self.commands:
            return self.create_result(
                has_alert=False,
                message="无自定义命令配置",
            )
        
        alerts = []
        details = {
            'command_results': {},
        }
        
        now = datetime.now()
        
        for cmd_config in self.commands:
            cmd_name = cmd_config.get('name', 'unnamed')
            interval = cmd_config.get('interval', self.interval)
            
            # 检查是否到执行时间
            last_info = self._last_run.get(cmd_name, {})
            last_time = last_info.get('timestamp')
            
            if last_time:
                elapsed = (now - last_time).total_seconds()
                if elapsed < interval:
                    # 使用上次结果
                    if last_info.get('alerts'):
                        alerts.extend(last_info['alerts'])
                    details['command_results'][cmd_name] = last_info.get('result', {})
                    continue
            
            # 执行命令
            result, cmd_alerts = self._execute_command(cmd_config)
            
            details['command_results'][cmd_name] = result
            alerts.extend(cmd_alerts)
            
            # 更新缓存
            self._last_run[cmd_name] = {
                'timestamp': now,
                'result': result,
                'alerts': cmd_alerts,
            }
        
        if alerts:
            message = f"自定义命令告警: {'; '.join(alerts[:3])}"
            if len(alerts) > 3:
                message += f" (共 {len(alerts)} 项)"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message="自定义命令检查正常",
            details=details,
        )
    
    def _execute_command(self, cmd_config: dict) -> tuple[dict, list[str]]:
        """执行单个命令"""
        cmd_name = cmd_config.get('name', 'unnamed')
        command = cmd_config.get('command', '')
        timeout = cmd_config.get('timeout', self.default_timeout)
        parse_type = cmd_config.get('parse_type', 'raw')
        alert_conditions = cmd_config.get('alert_conditions', [])
        
        result = {
            'command': command,
            'timestamp': datetime.now().isoformat(),
        }
        alerts = []
        
        # 执行命令
        ret, stdout, stderr = run_command(command, timeout=timeout, shell=True)
        
        result['return_code'] = ret
        result['stderr'] = stderr[:500] if stderr else ''
        
        if ret != 0:
            # 命令执行失败
            alerts.append(f"{cmd_name} 执行失败 (返回码: {ret})")
            logger.error(f"命令 {cmd_name} 执行失败: {stderr[:200]}")
            result['error'] = True
            return result, alerts
        
        # 解析输出
        parsed = self._parse_output(stdout, parse_type)
        result['parsed'] = parsed
        
        # 检查告警条件
        for condition in alert_conditions:
            triggered, alert_msg = self._check_condition(cmd_name, parsed, condition)
            if triggered:
                alerts.append(alert_msg)
        
        return result, alerts
    
    def _parse_output(self, output: str, parse_type: str) -> dict[str, Any]:
        """解析命令输出"""
        output = output.strip()
        
        if parse_type == 'json':
            try:
                return json.loads(output)
            except json.JSONDecodeError as e:
                logger.debug(f"JSON 解析失败: {e}")
                return {'raw': output, 'parse_error': str(e)}
        
        elif parse_type == 'key_value':
            result = {}
            for line in output.split('\n'):
                line = line.strip()
                for sep in ['=', ':', '\t']:
                    if sep in line:
                        parts = line.split(sep, 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip()
                            result[key] = value
                        break
            return result
        
        elif parse_type == 'regex':
            # 正则模式需要在配置中指定
            return {'raw': output}
        
        else:  # raw
            return {'raw': output}
    
    def _check_condition(self, cmd_name: str, parsed: dict, 
                        condition: dict) -> tuple[bool, str]:
        """检查告警条件"""
        field = condition.get('field', '')
        operator = condition.get('operator', '==')
        expected = condition.get('value', '')
        level = condition.get('level', 'warning')
        
        # 获取字段值（支持嵌套，如 "status.code"）
        actual = self._get_nested_value(parsed, field)
        
        if actual is None:
            # 字段不存在
            if condition.get('alert_on_missing', False):
                return True, f"{cmd_name}: 字段 '{field}' 不存在"
            return False, ""
        
        # 执行比较
        op_func = self.OPERATORS.get(operator)
        if op_func is None:
            logger.warning(f"未知操作符: {operator}")
            return False, ""
        
        try:
            triggered = op_func(actual, expected)
        except (ValueError, TypeError) as e:
            logger.debug(f"条件比较失败: {e}")
            return False, ""
        
        if triggered:
            return True, f"{cmd_name}: {field}={actual} ({operator} {expected})"
        
        return False, ""
    
    def _get_nested_value(self, data: dict, field: str) -> Any:
        """获取嵌套字段值"""
        if not field:
            return None
        
        parts = field.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            else:
                return None
            
            if current is None:
                return None
        
        return current
    
    def add_command(self, cmd_config: dict):
        """动态添加命令"""
        cmd_name = cmd_config.get('name', 'unnamed')
        command = cmd_config.get('command', '')
        
        if not command:
            raise ValueError("命令不能为空")
        
        # 安全检查
        cmd_path = command.split()[0]
        is_allowed = any(cmd_path.startswith(p) for p in self.allowed_paths)
        
        if not is_allowed:
            raise ValueError(f"命令路径 {cmd_path} 不在白名单中")
        
        self.commands.append(cmd_config)
        logger.info(f"已添加自定义命令: {cmd_name}")
    
    def remove_command(self, cmd_name: str):
        """移除命令"""
        self.commands = [c for c in self.commands if c.get('name') != cmd_name]
        if cmd_name in self._last_run:
            del self._last_run[cmd_name]
        logger.info(f"已移除自定义命令: {cmd_name}")
