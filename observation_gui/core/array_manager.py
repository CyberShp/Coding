"""
阵列管理器

管理多台阵列的连接、状态、监控任务。
"""

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..ssh.connector import SSHConnector
from ..ssh.remote_ops import RemoteOperations

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ArrayConfig:
    """阵列配置"""
    id: str
    name: str
    host: str
    port: int = 22
    username: str = "root"
    password: str = ""
    key_path: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（不含密码，保留密钥路径）"""
        d = asdict(self)
        # 只排除密码，保留密钥路径（密钥路径不是敏感信息）
        d.pop('password', None)
        return d


@dataclass
class ArrayStatus:
    """阵列状态"""
    config: ArrayConfig
    state: ConnectionState = ConnectionState.DISCONNECTED
    last_error: str = ""
    last_refresh: Optional[datetime] = None
    agent_deployed: bool = False
    agent_running: bool = False
    observer_status: Dict[str, Dict[str, str]] = field(default_factory=dict)
    recent_alerts: List[Dict[str, Any]] = field(default_factory=list)


class ArrayManager:
    """
    阵列管理器
    
    功能：
    - 管理多台阵列的配置
    - 建立/维护 SSH 连接
    - 协调监控任务
    - 收集和汇总状态
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化阵列管理器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self._arrays = {}  # type: Dict[str, ArrayStatus]
        self._connectors = {}  # type: Dict[str, SSHConnector]
        self._remote_ops = {}  # type: Dict[str, RemoteOperations]
        self._lock = threading.RLock()
        self._callbacks = []  # type: List[Callable]
        
        # 从配置加载阵列
        if config_path and config_path.exists():
            self._load_config()
    
    def _load_config(self):
        """从配置文件加载阵列"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            for array_conf in config.get('arrays', []):
                self.add_array(ArrayConfig(**array_conf), save=False)
                
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    
    def _save_config(self) -> bool:
        """
        保存配置到文件
        
        使用原子写入（先写临时文件，再重命名）确保可靠性。
        
        Returns:
            是否保存成功
        """
        if not self.config_path:
            logger.warning("配置路径未设置，无法保存")
            return False
        
        try:
            # 确保配置目录存在
            config_dir = self.config_path.parent
            if not config_dir.exists():
                config_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"创建配置目录: {config_dir}")
            
            # 读取现有配置
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = {
                    'app': {
                        'title': '观察点监控平台',
                        'refresh_interval': 30,
                        'window_width': 1000,
                        'window_height': 700,
                    }
                }
            
            # 更新阵列配置（不保存密码，但保留密钥路径）
            config['arrays'] = [
                status.config.to_dict()
                for status in self._arrays.values()
            ]
            
            # 原子写入：先写临时文件，再重命名
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                prefix='config_',
                dir=str(config_dir)
            )
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                
                # 重命名（原子操作）
                os.replace(temp_path, str(self.config_path))
                
            except Exception:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
            
            # 验证保存结果
            with open(self.config_path, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
            
            saved_count = len(saved_config.get('arrays', []))
            expected_count = len(self._arrays)
            
            if saved_count != expected_count:
                logger.error(f"配置验证失败: 期望 {expected_count} 个阵列，实际保存 {saved_count} 个")
                return False
            
            logger.info(f"配置已保存: {self.config_path} ({saved_count} 个阵列)")
            return True
                
        except Exception as e:
            logger.error(f"保存配置失败: {e}", exc_info=True)
            return False
    
    def add_callback(self, callback: Callable):
        """添加状态变更回调"""
        self._callbacks.append(callback)
    
    def _notify_callbacks(self, event: str, array_id: str):
        """通知回调"""
        for cb in self._callbacks:
            try:
                cb(event, array_id)
            except Exception as e:
                logger.error(f"回调执行失败: {e}")
    
    def add_array(self, config: ArrayConfig, save: bool = True) -> bool:
        """
        添加阵列
        
        Args:
            config: 阵列配置
            save: 是否保存到配置文件
            
        Returns:
            是否成功
        """
        with self._lock:
            if config.id in self._arrays:
                logger.warning(f"阵列 {config.id} 已存在")
                return False
            
            self._arrays[config.id] = ArrayStatus(config=config)
            
            if save:
                self._save_config()
            
            logger.info(f"添加阵列: {config.name} ({config.host})")
            self._notify_callbacks('array_added', config.id)
            return True
    
    def remove_array(self, array_id: str) -> bool:
        """
        移除阵列
        
        Args:
            array_id: 阵列 ID
            
        Returns:
            是否成功
        """
        with self._lock:
            if array_id not in self._arrays:
                return False
            
            # 断开连接
            self.disconnect_array(array_id)
            
            del self._arrays[array_id]
            self._save_config()
            
            logger.info(f"移除阵列: {array_id}")
            self._notify_callbacks('array_removed', array_id)
            return True
    
    def get_array(self, array_id: str) -> Optional[ArrayStatus]:
        """获取阵列状态"""
        return self._arrays.get(array_id)
    
    def get_all_arrays(self) -> List[ArrayStatus]:
        """获取所有阵列状态"""
        return list(self._arrays.values())
    
    def connect_array(self, array_id: str) -> bool:
        """
        连接阵列
        
        Args:
            array_id: 阵列 ID
            
        Returns:
            是否成功
        """
        with self._lock:
            status = self._arrays.get(array_id)
            if status is None:
                return False
            
            status.state = ConnectionState.CONNECTING
            self._notify_callbacks('state_changed', array_id)
        
        try:
            config = status.config
            connector = SSHConnector(
                host=config.host,
                port=config.port,
                username=config.username,
                password=config.password or None,
                key_path=config.key_path or None,
            )
            
            if connector.connect():
                with self._lock:
                    self._connectors[array_id] = connector
                    self._remote_ops[array_id] = RemoteOperations(connector)
                    status.state = ConnectionState.CONNECTED
                    status.last_error = ""
                
                # 检查环境
                self._check_remote_environment(array_id)
                
                self._notify_callbacks('state_changed', array_id)
                return True
            else:
                with self._lock:
                    status.state = ConnectionState.ERROR
                    status.last_error = "连接失败"
                
                self._notify_callbacks('state_changed', array_id)
                return False
                
        except Exception as e:
            with self._lock:
                status.state = ConnectionState.ERROR
                status.last_error = str(e)
            
            self._notify_callbacks('state_changed', array_id)
            return False
    
    def disconnect_array(self, array_id: str):
        """断开阵列连接"""
        with self._lock:
            if array_id in self._connectors:
                self._connectors[array_id].disconnect()
                del self._connectors[array_id]
            
            if array_id in self._remote_ops:
                del self._remote_ops[array_id]
            
            if array_id in self._arrays:
                self._arrays[array_id].state = ConnectionState.DISCONNECTED
                self._notify_callbacks('state_changed', array_id)
    
    def _check_remote_environment(self, array_id: str):
        """检查远程环境"""
        ops = self._remote_ops.get(array_id)
        if ops is None:
            return
        
        env = ops.check_environment()
        
        with self._lock:
            status = self._arrays.get(array_id)
            if status:
                status.agent_deployed = env.get('agent_deployed', False)
                status.agent_running = env.get('agent_running', False)
    
    def start_monitoring(self, array_id: str) -> bool:
        """启动阵列监控"""
        ops = self._remote_ops.get(array_id)
        if ops is None:
            return False
        
        result = ops.start_monitoring(background=True)
        
        if result:
            with self._lock:
                status = self._arrays.get(array_id)
                if status:
                    status.agent_running = True
            self._notify_callbacks('state_changed', array_id)
        
        return result
    
    def stop_monitoring(self, array_id: str) -> bool:
        """停止阵列监控"""
        ops = self._remote_ops.get(array_id)
        if ops is None:
            return False
        
        result = ops.stop_monitoring()
        
        if result:
            with self._lock:
                status = self._arrays.get(array_id)
                if status:
                    status.agent_running = False
            self._notify_callbacks('state_changed', array_id)
        
        return result
    
    def refresh_array(self, array_id: str):
        """刷新单个阵列状态"""
        ops = self._remote_ops.get(array_id)
        if ops is None:
            return
        
        # 检查环境
        self._check_remote_environment(array_id)
        
        # 获取观察点状态
        observer_status = ops.get_observer_status()
        
        # 获取最近告警
        alerts_result = ops.fetch_alerts()
        
        with self._lock:
            status = self._arrays.get(array_id)
            if status:
                status.observer_status = observer_status
                status.recent_alerts = alerts_result.get('alerts', [])[-20:]
                status.last_refresh = datetime.now()
        
        self._notify_callbacks('status_updated', array_id)
    
    def refresh_all(self):
        """刷新所有已连接阵列的状态"""
        for array_id, status in self._arrays.items():
            if status.state == ConnectionState.CONNECTED:
                try:
                    self.refresh_array(array_id)
                except Exception as e:
                    logger.error(f"刷新阵列 {array_id} 失败: {e}")
    
    def get_summary(self) -> Dict[str, Any]:
        """获取汇总信息"""
        total = len(self._arrays)
        connected = sum(
            1 for s in self._arrays.values()
            if s.state == ConnectionState.CONNECTED
        )
        running = sum(
            1 for s in self._arrays.values()
            if s.agent_running
        )
        
        # 汇总告警
        all_alerts = []
        for status in self._arrays.values():
            for alert in status.recent_alerts:
                alert['array_id'] = status.config.id
                alert['array_name'] = status.config.name
                all_alerts.append(alert)
        
        # 按时间排序
        all_alerts.sort(
            key=lambda x: x.get('timestamp', ''),
            reverse=True
        )
        
        return {
            'total_arrays': total,
            'connected_arrays': connected,
            'running_arrays': running,
            'recent_alerts': all_alerts[:50],
        }
