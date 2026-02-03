"""
远程操作封装

提供部署、启动、停止、获取结果等高级操作。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .connector import SSHConnector

logger = logging.getLogger(__name__)


class RemoteOperations:
    """
    远程操作封装
    
    提供：
    - 检查远程环境
    - 部署 observation_points
    - 启动/停止监控
    - 获取监控结果
    """
    
    def __init__(
        self,
        connector: SSHConnector,
        agent_path: str = "/opt/observation_points",
        log_path: str = "/var/log/observation-points/alerts.log",
        python_cmd: str = "python3",
    ):
        """
        初始化远程操作
        
        Args:
            connector: SSH 连接器
            agent_path: 远程 agent 安装路径
            log_path: 远程告警日志路径
            python_cmd: Python 命令
        """
        self.connector = connector
        self.agent_path = agent_path
        self.log_path = log_path
        self.python_cmd = python_cmd
    
    def check_environment(self) -> Dict[str, Any]:
        """
        检查远程环境
        
        Returns:
            环境检查结果
        """
        result = {
            'connected': False,
            'python_available': False,
            'python_version': None,
            'agent_deployed': False,
            'agent_running': False,
        }
        
        # 检查连接
        if not self.connector.is_connected():
            if not self.connector.connect():
                return result
        result['connected'] = True
        
        # 检查 Python
        ret, out, err = self.connector.execute(f"{self.python_cmd} --version")
        if ret == 0:
            result['python_available'] = True
            result['python_version'] = out.strip() or err.strip()
        
        # 检查 agent 是否部署
        ret, out, err = self.connector.execute(f"test -d {self.agent_path} && echo 'yes'")
        result['agent_deployed'] = 'yes' in out
        
        # 检查 agent 是否运行中
        ret, out, err = self.connector.execute(
            f"pgrep -f 'python.*observation_points'"
        )
        result['agent_running'] = ret == 0 and out.strip() != ''
        
        return result
    
    def deploy_agent(self, local_source: str) -> bool:
        """
        部署 observation_points 到远程
        
        Args:
            local_source: 本地 observation_points 源码路径
            
        Returns:
            是否成功
        """
        local_path = Path(local_source)
        if not local_path.exists():
            logger.error(f"本地源码不存在: {local_source}")
            return False
        
        # 创建远程目录
        ret, _, err = self.connector.execute(f"mkdir -p {self.agent_path}")
        if ret != 0:
            logger.error(f"创建远程目录失败: {err}")
            return False
        
        # 使用 tar 打包上传（更高效）
        # 这里简化为逐文件上传，实际可优化
        logger.info(f"开始部署 agent 到 {self.connector.host}:{self.agent_path}")
        
        # 上传关键文件
        files_to_upload = [
            '__init__.py',
            '__main__.py',
            'config.json',
            'requirements.txt',
        ]
        
        dirs_to_upload = [
            'core',
            'config',
            'observers',
            'utils',
        ]
        
        # 创建子目录
        for dir_name in dirs_to_upload:
            remote_dir = f"{self.agent_path}/{dir_name}"
            self.connector.execute(f"mkdir -p {remote_dir}")
        
        # 上传文件（简化实现，实际应使用 rsync 或 tar）
        for file_name in files_to_upload:
            local_file = local_path / file_name
            if local_file.exists():
                remote_file = f"{self.agent_path}/{file_name}"
                if not self.connector.upload_file(str(local_file), remote_file):
                    logger.warning(f"上传文件失败: {file_name}")
        
        # 上传目录中的文件
        for dir_name in dirs_to_upload:
            local_dir = local_path / dir_name
            if local_dir.exists():
                for file_path in local_dir.glob("*.py"):
                    remote_file = f"{self.agent_path}/{dir_name}/{file_path.name}"
                    self.connector.upload_file(str(file_path), remote_file)
        
        logger.info("Agent 部署完成")
        return True
    
    def start_monitoring(self, background: bool = True) -> bool:
        """
        启动远程监控
        
        Args:
            background: 是否后台运行
            
        Returns:
            是否成功
        """
        if not self.connector.is_connected():
            return False
        
        # 检查是否已在运行
        env = self.check_environment()
        if env.get('agent_running'):
            logger.info("监控进程已在运行")
            return True
        
        # 启动命令
        if background:
            cmd = (
                f"cd {self.agent_path} && "
                f"nohup {self.python_cmd} -m observation_points "
                f"> /var/log/observation-points/stdout.log 2>&1 &"
            )
        else:
            cmd = f"cd {self.agent_path} && {self.python_cmd} -m observation_points"
        
        # 确保日志目录存在
        self.connector.execute("mkdir -p /var/log/observation-points")
        
        ret, out, err = self.connector.execute(cmd)
        
        if background:
            # 检查是否启动成功
            import time
            time.sleep(1)
            env = self.check_environment()
            if env.get('agent_running'):
                logger.info("监控进程启动成功")
                return True
            else:
                logger.error("监控进程启动失败")
                return False
        
        return ret == 0
    
    def stop_monitoring(self) -> bool:
        """
        停止远程监控
        
        Returns:
            是否成功
        """
        if not self.connector.is_connected():
            return False
        
        # 发送 SIGTERM
        ret, out, err = self.connector.execute(
            "pkill -f 'python.*observation_points'"
        )
        
        # pkill 返回 0 表示找到并杀死了进程，1 表示没找到进程
        if ret in (0, 1):
            logger.info("监控进程已停止")
            return True
        
        logger.error(f"停止监控进程失败: {err}")
        return False
    
    def fetch_alerts(self, last_position: int = 0) -> Dict[str, Any]:
        """
        获取告警日志
        
        Args:
            last_position: 上次读取的位置（字节）
            
        Returns:
            {
                'alerts': [...],
                'new_position': int,
                'error': str or None,
            }
        """
        result = {
            'alerts': [],
            'new_position': last_position,
            'error': None,
        }
        
        if not self.connector.is_connected():
            result['error'] = "未连接"
            return result
        
        # 读取日志文件
        content = self.connector.read_remote_file(self.log_path)
        
        if content is None:
            # 文件可能不存在（还没有告警）
            return result
        
        # 只处理新增内容
        if last_position > 0 and last_position < len(content):
            content = content[last_position:]
        elif last_position >= len(content):
            # 没有新内容
            return result
        
        # 解析 JSON 行
        alerts = []
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                alert = json.loads(line)
                alerts.append(alert)
            except json.JSONDecodeError:
                logger.debug(f"无法解析告警行: {line[:100]}")
        
        result['alerts'] = alerts
        result['new_position'] = last_position + len(content)
        
        return result
    
    def get_observer_status(self) -> Dict[str, Any]:
        """
        获取各观察点的当前状态
        
        Returns:
            观察点状态字典
        """
        # 尝试读取状态文件或执行命令获取
        # 这里简化为从告警日志分析最近状态
        
        status = {
            'error_code': {'status': 'unknown', 'message': ''},
            'link_status': {'status': 'unknown', 'message': ''},
            'card_recovery': {'status': 'unknown', 'message': ''},
            'alarm_type': {'status': 'unknown', 'message': ''},
            'memory_leak': {'status': 'unknown', 'message': ''},
            'cpu_usage': {'status': 'unknown', 'message': ''},
            'cmd_response': {'status': 'unknown', 'message': ''},
            'sig_monitor': {'status': 'unknown', 'message': ''},
            'sensitive_info': {'status': 'unknown', 'message': ''},
        }
        
        # 获取最近的告警
        result = self.fetch_alerts()
        
        if result['error']:
            return status
        
        # 分析告警，更新状态
        for alert in result['alerts'][-50:]:  # 只看最近50条
            observer_name = alert.get('observer_name', '')
            level = alert.get('level', 'info')
            message = alert.get('message', '')
            
            if observer_name in status:
                if level in ('error', 'critical'):
                    status[observer_name] = {
                        'status': 'error',
                        'message': message[:100],
                    }
                elif level == 'warning':
                    if status[observer_name]['status'] != 'error':
                        status[observer_name] = {
                            'status': 'warning',
                            'message': message[:100],
                        }
        
        # 没有告警的观察点标记为正常
        for name, info in status.items():
            if info['status'] == 'unknown':
                status[name] = {'status': 'ok', 'message': '正常'}
        
        return status
