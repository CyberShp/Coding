"""
SSH 连接器

封装 paramiko 提供简洁的 SSH 连接和命令执行接口。
"""

import logging
import socket
from typing import Any, Optional, Tuple, TYPE_CHECKING

# 类型检查时导入，运行时延迟导入
if TYPE_CHECKING:
    import paramiko

logger = logging.getLogger(__name__)

# 运行时检查 paramiko 是否可用
_paramiko = None
try:
    import paramiko as _paramiko
except ImportError:
    pass


class SSHConnector:
    """
    SSH 连接器
    
    提供：
    - 连接/断开
    - 命令执行
    - 文件上传/下载
    - 连接状态检查
    """
    
    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "root",
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        timeout: int = 10,
    ):
        """
        初始化 SSH 连接器
        
        Args:
            host: 主机地址
            port: SSH 端口
            username: 用户名
            password: 密码（与 key_path 二选一）
            key_path: 私钥文件路径（与 password 二选一）
            timeout: 连接超时（秒）
        """
        if _paramiko is None:
            raise ImportError("请安装 paramiko: pip install paramiko")
        
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        self.timeout = timeout
        
        self._client = None  # type: Optional[Any]
        self._sftp = None  # type: Optional[Any]
    
    def connect(self) -> bool:
        """
        建立 SSH 连接
        
        Returns:
            是否连接成功
        """
        if self._client is not None:
            return True
        
        try:
            self._client = _paramiko.SSHClient()
            self._client.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                'hostname': self.host,
                'port': self.port,
                'username': self.username,
                'timeout': self.timeout,
                'allow_agent': False,
                'look_for_keys': False,
            }
            
            if self.key_path:
                connect_kwargs['key_filename'] = self.key_path
            elif self.password:
                connect_kwargs['password'] = self.password
            else:
                raise ValueError("必须提供密码或密钥文件")
            
            self._client.connect(**connect_kwargs)
            
            logger.info(f"SSH 连接成功: {self.username}@{self.host}:{self.port}")
            return True
            
        except _paramiko.AuthenticationException:
            logger.error(f"SSH 认证失败: {self.host}")
            self._cleanup()
            return False
        except _paramiko.SSHException as e:
            logger.error(f"SSH 连接错误: {self.host}, {e}")
            self._cleanup()
            return False
        except socket.timeout:
            logger.error(f"SSH 连接超时: {self.host}")
            self._cleanup()
            return False
        except socket.error as e:
            logger.error(f"网络错误: {self.host}, {e}")
            self._cleanup()
            return False
        except Exception as e:
            logger.error(f"SSH 连接异常: {self.host}, {e}")
            self._cleanup()
            return False
    
    def disconnect(self):
        """断开 SSH 连接"""
        self._cleanup()
        logger.info(f"SSH 已断开: {self.host}")
    
    def _cleanup(self):
        """清理连接资源"""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
    
    def is_connected(self) -> bool:
        """检查连接是否有效"""
        if self._client is None:
            return False
        
        try:
            transport = self._client.get_transport()
            if transport is None:
                return False
            return transport.is_active()
        except Exception:
            return False
    
    def execute(
        self,
        command: str,
        timeout: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        """
        执行远程命令
        
        Args:
            command: 要执行的命令
            timeout: 命令超时（秒），None 表示使用默认值
            
        Returns:
            (返回码, stdout, stderr)
        """
        if not self.is_connected():
            if not self.connect():
                return -1, "", "SSH 连接失败"
        
        try:
            stdin, stdout, stderr = self._client.exec_command(
                command,
                timeout=timeout or self.timeout * 3,
            )
            
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode('utf-8', errors='ignore')
            err = stderr.read().decode('utf-8', errors='ignore')
            
            return exit_code, out, err
            
        except socket.timeout:
            logger.error(f"命令执行超时: {command[:50]}...")
            return -1, "", "命令执行超时"
        except Exception as e:
            logger.error(f"命令执行失败: {e}")
            return -1, "", str(e)
    
    def _get_sftp(self) -> Optional[Any]:
        """获取 SFTP 客户端"""
        if not self.is_connected():
            if not self.connect():
                return None
        
        if self._sftp is None:
            try:
                self._sftp = self._client.open_sftp()
            except Exception as e:
                logger.error(f"SFTP 连接失败: {e}")
                return None
        
        return self._sftp
    
    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """
        上传文件
        
        Args:
            local_path: 本地文件路径
            remote_path: 远程文件路径
            
        Returns:
            是否成功
        """
        sftp = self._get_sftp()
        if sftp is None:
            return False
        
        try:
            sftp.put(local_path, remote_path)
            logger.info(f"文件上传成功: {local_path} -> {remote_path}")
            return True
        except Exception as e:
            logger.error(f"文件上传失败: {e}")
            return False
    
    def download_file(self, remote_path: str, local_path: str) -> bool:
        """
        下载文件
        
        Args:
            remote_path: 远程文件路径
            local_path: 本地文件路径
            
        Returns:
            是否成功
        """
        sftp = self._get_sftp()
        if sftp is None:
            return False
        
        try:
            sftp.get(remote_path, local_path)
            logger.info(f"文件下载成功: {remote_path} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"文件下载失败: {e}")
            return False
    
    def read_remote_file(self, remote_path: str) -> Optional[str]:
        """
        读取远程文件内容
        
        Args:
            remote_path: 远程文件路径
            
        Returns:
            文件内容，或 None（如果失败）
        """
        sftp = self._get_sftp()
        if sftp is None:
            return None
        
        try:
            with sftp.open(remote_path, 'r') as f:
                return f.read().decode('utf-8', errors='ignore')
        except FileNotFoundError:
            logger.debug(f"远程文件不存在: {remote_path}")
            return None
        except Exception as e:
            logger.error(f"读取远程文件失败: {e}")
            return None
    
    def file_exists(self, remote_path: str) -> bool:
        """检查远程文件是否存在"""
        sftp = self._get_sftp()
        if sftp is None:
            return False
        
        try:
            sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False
    
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.disconnect()
        return False
    
    def __repr__(self) -> str:
        status = "已连接" if self.is_connected() else "未连接"
        return f"<SSHConnector {self.username}@{self.host}:{self.port} [{status}]>"
