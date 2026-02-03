"""
命令响应时间监测观察点

通过 time 命令执行指定命令，检查响应时间是否在阈值内。
"""

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class CmdResponseObserver(BaseObserver):
    """
    命令响应时间监测观察点
    
    功能：
    - 执行指定命令并测量执行时间
    - 如果执行时间超过阈值则告警
    """
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        # 超时阈值（秒）
        self.timeout_seconds = config.get('timeout_seconds', 1.0)
        
        # 要监测的命令列表
        self.commands = config.get('commands', ['lscpu', 'anytest frameallinfo'])
        
        # 命令执行超时（秒）- 比阈值稍长，防止卡死
        self.execution_timeout = config.get('execution_timeout', 10)
    
    def check(self) -> ObserverResult:
        """检查命令响应时间"""
        alerts = []
        details = {
            'results': [],
            'timeout_seconds': self.timeout_seconds,
        }
        
        for cmd in self.commands:
            result = self._check_command(cmd)
            details['results'].append(result)
            
            if result['exceeded']:
                alerts.append(f"{cmd} 耗时 {result['elapsed_seconds']:.3f}s")
                logger.warning(
                    f"命令响应超时: {cmd} 耗时 {result['elapsed_seconds']:.3f}s (阈值: {self.timeout_seconds}s)"
                )
        
        if alerts:
            message = f"命令响应超时: {', '.join(alerts)}"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message=f"命令响应检查正常 (阈值: {self.timeout_seconds}s)",
            details=details,
        )
    
    def _check_command(self, cmd: str) -> Dict[str, Any]:
        """
        检查单个命令的响应时间
        
        Returns:
            包含执行结果的字典
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 使用 Python 的 time 模块测量时间
        start_time = time.time()
        
        try:
            ret, stdout, stderr = run_command(
                cmd, 
                shell=True, 
                timeout=self.execution_timeout
            )
            
            elapsed = time.time() - start_time
            
            return {
                'command': cmd,
                'timestamp': timestamp,
                'elapsed_seconds': elapsed,
                'exceeded': elapsed > self.timeout_seconds,
                'return_code': ret,
                'success': ret == 0,
                'error': stderr[:200] if ret != 0 else None,
            }
            
        except Exception as e:
            elapsed = time.time() - start_time
            
            return {
                'command': cmd,
                'timestamp': timestamp,
                'elapsed_seconds': elapsed,
                'exceeded': True,
                'return_code': -1,
                'success': False,
                'error': str(e),
            }
