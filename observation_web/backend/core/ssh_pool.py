"""
SSH Connection Pool Management.

Manages SSH connections to multiple storage arrays.
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_config
from ..models.array import ConnectionState

logger = logging.getLogger(__name__)

# Try to import paramiko
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    paramiko = None
    PARAMIKO_AVAILABLE = False
    logger.warning("paramiko not installed, SSH functionality disabled")


class SSHConnection:
    """Single SSH connection wrapper"""
    
    def __init__(
        self,
        array_id: str,
        host: str,
        port: int = 22,
        username: str = "root",
        password: Optional[str] = None,
        key_path: Optional[str] = None,
    ):
        self.array_id = array_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        
        self._client: Optional[Any] = None
        self._sftp: Optional[Any] = None
        self._state = ConnectionState.DISCONNECTED
        self._last_error = ""
        self._lock = threading.RLock()
    
    @property
    def state(self) -> ConnectionState:
        return self._state
    
    @property
    def last_error(self) -> str:
        return self._last_error
    
    def is_connected(self) -> bool:
        """Check if connection is active"""
        if self._client is None:
            return False
        try:
            transport = self._client.get_transport()
            return transport is not None and transport.is_active()
        except Exception:
            return False
    
    def connect(self) -> bool:
        """Establish SSH connection"""
        if not PARAMIKO_AVAILABLE:
            self._state = ConnectionState.ERROR
            self._last_error = "paramiko not installed"
            return False
        
        with self._lock:
            self._state = ConnectionState.CONNECTING
            
            try:
                self._client = paramiko.SSHClient()
                self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                config = get_config()
                
                connect_kwargs = {
                    'hostname': self.host,
                    'port': self.port,
                    'username': self.username,
                    'timeout': config.ssh.timeout,
                }
                
                if self.key_path:
                    connect_kwargs['key_filename'] = self.key_path
                elif self.password:
                    connect_kwargs['password'] = self.password
                
                self._client.connect(**connect_kwargs)
                
                # Enable keepalive
                transport = self._client.get_transport()
                if transport:
                    transport.set_keepalive(config.ssh.keepalive_interval)
                
                self._state = ConnectionState.CONNECTED
                self._last_error = ""
                logger.info(f"SSH connected to {self.host}:{self.port}")
                return True
                
            except Exception as e:
                self._state = ConnectionState.ERROR
                self._last_error = str(e)
                logger.error(f"SSH connection failed: {e}")
                return False
    
    def disconnect(self):
        """Close SSH connection"""
        with self._lock:
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
            
            self._state = ConnectionState.DISCONNECTED
            logger.info(f"SSH disconnected from {self.host}")
    
    def execute(self, command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """
        Execute command on remote host.
        
        Returns:
            (exit_code, stdout, stderr)
        """
        if not self.is_connected():
            return (-1, "", "Not connected")
        
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            return (exit_code, out, err)
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return (-1, "", str(e))
    
    def read_file(self, remote_path: str) -> Optional[str]:
        """Read remote file content"""
        if not self.is_connected():
            return None
        
        try:
            if self._sftp is None:
                self._sftp = self._client.open_sftp()
            
            with self._sftp.open(remote_path, 'r') as f:
                return f.read().decode('utf-8', errors='replace')
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to read file {remote_path}: {e}")
            return None

    def upload_file(self, local_path: str, remote_path: str) -> Tuple[bool, str]:
        """Upload local file to remote path"""
        if not self.is_connected():
            return (False, "Not connected")

        try:
            if self._sftp is None:
                self._sftp = self._client.open_sftp()

            self._sftp.put(local_path, remote_path)
            return (True, "")
        except Exception as e:
            logger.error(f"Failed to upload file {local_path} -> {remote_path}: {e}")
            return (False, str(e))


class SSHPool:
    """
    SSH Connection Pool.
    
    Manages multiple SSH connections to storage arrays.
    """
    
    def __init__(self):
        self._connections: Dict[str, SSHConnection] = {}
        self._lock = threading.RLock()
    
    def add_connection(
        self,
        array_id: str,
        host: str,
        port: int = 22,
        username: str = "root",
        password: Optional[str] = None,
        key_path: Optional[str] = None,
    ) -> SSHConnection:
        """Add a new connection to the pool"""
        with self._lock:
            if array_id in self._connections:
                self._connections[array_id].disconnect()
            
            conn = SSHConnection(
                array_id=array_id,
                host=host,
                port=port,
                username=username,
                password=password,
                key_path=key_path,
            )
            self._connections[array_id] = conn
            return conn
    
    def get_connection(self, array_id: str) -> Optional[SSHConnection]:
        """Get connection by array ID"""
        return self._connections.get(array_id)
    
    def remove_connection(self, array_id: str):
        """Remove and close connection"""
        with self._lock:
            if array_id in self._connections:
                self._connections[array_id].disconnect()
                del self._connections[array_id]
    
    def connect(self, array_id: str) -> bool:
        """Connect to array"""
        conn = self.get_connection(array_id)
        if conn:
            return conn.connect()
        return False
    
    def disconnect(self, array_id: str):
        """Disconnect from array"""
        conn = self.get_connection(array_id)
        if conn:
            conn.disconnect()
    
    def get_state(self, array_id: str) -> ConnectionState:
        """Get connection state"""
        conn = self.get_connection(array_id)
        if conn:
            return conn.state
        return ConnectionState.DISCONNECTED
    
    def execute(self, array_id: str, command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """Execute command on array"""
        conn = self.get_connection(array_id)
        if conn and conn.is_connected():
            return conn.execute(command, timeout)
        return (-1, "", "Not connected")
    
    def read_file(self, array_id: str, remote_path: str) -> Optional[str]:
        """Read file from array"""
        conn = self.get_connection(array_id)
        if conn and conn.is_connected():
            return conn.read_file(remote_path)
        return None
    
    def get_all_states(self) -> Dict[str, ConnectionState]:
        """Get all connection states"""
        return {
            array_id: conn.state
            for array_id, conn in self._connections.items()
        }
    
    def close_all(self):
        """Close all connections"""
        with self._lock:
            for conn in self._connections.values():
                conn.disconnect()
            self._connections.clear()


# Global SSH pool instance
_ssh_pool: Optional[SSHPool] = None


def get_ssh_pool() -> SSHPool:
    """Get global SSH pool instance"""
    global _ssh_pool
    if _ssh_pool is None:
        _ssh_pool = SSHPool()
    return _ssh_pool
