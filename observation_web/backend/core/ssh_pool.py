"""
SSH Connection Pool Management.

Manages SSH connections to multiple storage arrays.
Supports auto-reconnect, idle timeout, and async command execution.
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_config
from ..models.array import ConnectionState
from .system_alert import sys_error, sys_warning, sys_info

logger = logging.getLogger(__name__)

# Try to import paramiko
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    paramiko = None
    PARAMIKO_AVAILABLE = False
    logger.warning("paramiko not installed, SSH functionality disabled")

# Thread pool for async SSH operations
_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="ssh-worker")


class SSHConnection:
    """Single SSH connection wrapper with auto-reconnect and idle timeout"""
    
    MAX_RECONNECT_ATTEMPTS = 3
    IDLE_TIMEOUT = 600  # 10 minutes idle timeout
    
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
        self._reconnect_attempts = 0
        self._last_activity = time.time()
        self._connected_at: Optional[float] = None
    
    @property
    def state(self) -> ConnectionState:
        return self._state
    
    @property
    def last_error(self) -> str:
        return self._last_error
    
    @property
    def idle_seconds(self) -> float:
        """Seconds since last activity"""
        return time.time() - self._last_activity
    
    @property
    def uptime_seconds(self) -> float:
        """Seconds since connection was established"""
        if self._connected_at is None:
            return 0
        return time.time() - self._connected_at
    
    def is_connected(self) -> bool:
        """Check if connection is truly active using a real probe, auto-reconnect if needed"""
        if self._client is None:
            return False
        try:
            transport = self._client.get_transport()
            if transport is None or not transport.is_active():
                return self._try_reconnect()
            # Probe the connection with a real command to detect stale sockets
            # send_ignore is a lightweight SSH keepalive packet
            transport.send_ignore()
            self._reconnect_attempts = 0  # Reset on successful probe
            return True
        except (EOFError, OSError, Exception):
            # Connection is truly dead — probe failed
            logger.info(f"SSH probe failed for {self.host}, attempting reconnect")
            return self._try_reconnect()
    
    def _try_reconnect(self) -> bool:
        """Attempt to reconnect if credentials are available"""
        if self._reconnect_attempts >= self.MAX_RECONNECT_ATTEMPTS:
            logger.warning(f"Max reconnect attempts reached for {self.host}")
            return False
        
        if not self.password and not self.key_path:
            return False
        
        self._reconnect_attempts += 1
        logger.info(f"Attempting reconnect to {self.host} (attempt {self._reconnect_attempts})")
        
        # Close existing connection
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
        
        # Reconnect
        return self.connect()
    
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
                self._last_activity = time.time()
                self._connected_at = time.time()
                logger.info(f"SSH connected to {self.host}:{self.port}")
                return True
                
            except Exception as e:
                self._state = ConnectionState.ERROR
                self._last_error = str(e)
                logger.error(f"SSH connection failed: {e}")
                sys_error(
                    "ssh_pool",
                    f"SSH connection failed to {self.host}:{self.port}",
                    {"host": self.host, "port": self.port, "username": self.username},
                    exception=e
                )
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
        
        self._last_activity = time.time()
        
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            channel = stdout.channel
            channel.settimeout(timeout)  # Channel-level timeout for read operations
            # IMPORTANT: Read stdout/stderr BEFORE recv_exit_status() to avoid
            # deadlock when the output buffer is full (paramiko known issue)
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            exit_code = channel.recv_exit_status()
            return (exit_code, out, err)
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return (-1, "", str(e))
    
    async def execute_async(self, command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """
        Execute command asynchronously using thread pool.
        Use this from async code to avoid blocking the event loop.
        Wraps with asyncio.wait_for to prevent thread pool stalls.
        """
        loop = asyncio.get_event_loop()
        # Add extra buffer (2x) for asyncio timeout to allow the SSH-level timeout to fire first
        async_timeout = timeout * 2
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(_executor, self.execute, command, timeout),
                timeout=async_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Async execute timed out after {async_timeout}s for command: {command[:80]}")
            return (-1, "", f"Async timeout after {async_timeout}s")
    
    def read_file(self, remote_path: str) -> Optional[str]:
        """Read remote file content via SSH exec (avoids SFTP permission issues)"""
        if not self.is_connected():
            return None
        
        try:
            # Use cat command instead of SFTP to avoid permission issues
            exit_code, content, err = self.execute(f"cat {remote_path}", timeout=10)
            if exit_code == 0:
                return content
            elif "No such file" in err or "not found" in err.lower():
                return None
            else:
                logger.error(f"Failed to read file {remote_path}: {err}")
                sys_warning(
                    "ssh_pool",
                    f"Failed to read remote file",
                    {"host": self.host, "path": remote_path, "error": err}
                )
                return None
        except Exception as e:
            logger.error(f"Failed to read file {remote_path}: {e}")
            sys_error(
                "ssh_pool",
                f"Exception reading remote file",
                {"host": self.host, "path": remote_path},
                exception=e
            )
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
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics"""
        total = len(self._connections)
        connected = sum(1 for c in self._connections.values() if c.state == ConnectionState.CONNECTED)
        return {
            "total_connections": total,
            "connected": connected,
            "disconnected": total - connected,
            "connections": {
                aid: {
                    "state": conn.state.value if hasattr(conn.state, 'value') else str(conn.state),
                    "host": conn.host,
                    "idle_seconds": round(conn.idle_seconds, 1),
                    "uptime_seconds": round(conn.uptime_seconds, 1),
                }
                for aid, conn in self._connections.items()
            }
        }
    
    def cleanup_idle_connections(self, max_idle_seconds: int = 600):
        """
        Disconnect idle connections to free resources.
        Called periodically by the background task.
        """
        with self._lock:
            for array_id, conn in list(self._connections.items()):
                if conn.state == ConnectionState.CONNECTED and conn.idle_seconds > max_idle_seconds:
                    logger.info(f"Disconnecting idle connection: {array_id} ({conn.host}), idle {conn.idle_seconds:.0f}s")
                    conn.disconnect()
    
    async def batch_execute(self, command: str, array_ids: Optional[List[str]] = None, timeout: int = 30) -> Dict[str, Tuple[int, str, str]]:
        """
        Execute a command on multiple arrays concurrently.
        
        Args:
            command: Command to execute
            array_ids: List of array IDs (None = all connected)
            timeout: Command timeout
            
        Returns:
            Dict of array_id -> (exit_code, stdout, stderr)
        """
        if array_ids is None:
            array_ids = [
                aid for aid, conn in self._connections.items()
                if conn.state == ConnectionState.CONNECTED
            ]
        
        async def _exec_one(aid: str) -> Tuple[str, Tuple[int, str, str]]:
            conn = self.get_connection(aid)
            if conn and conn.is_connected():
                result = await conn.execute_async(command, timeout)
                return (aid, result)
            return (aid, (-1, "", "Not connected"))
        
        results = await asyncio.gather(*[_exec_one(aid) for aid in array_ids])
        return dict(results)
    
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
