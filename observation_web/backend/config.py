"""
Configuration management for the backend service.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SSHConfig:
    """SSH connection defaults"""
    default_port: int = 22
    timeout: int = 10
    keepalive_interval: int = 30


@dataclass
class DatabaseConfig:
    """Database configuration"""
    path: str = "observation_web.db"
    echo: bool = False


@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


@dataclass
class RemoteConfig:
    """Remote agent configuration"""
    agent_path: str = "/opt/observation_points"
    log_path: str = "/var/log/observation-points/alerts.log"
    python_cmd: str = "python3"


@dataclass
class AppConfig:
    """Application configuration"""
    server: ServerConfig = field(default_factory=ServerConfig)
    ssh: SSHConfig = field(default_factory=SSHConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    
    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> 'AppConfig':
        """Load configuration from file"""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.json"
        
        config = cls()
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'server' in data:
                    config.server = ServerConfig(**data['server'])
                if 'ssh' in data:
                    config.ssh = SSHConfig(**data['ssh'])
                if 'database' in data:
                    config.database = DatabaseConfig(**data['database'])
                if 'remote' in data:
                    config.remote = RemoteConfig(**data['remote'])
                    
            except Exception as e:
                print(f"Warning: Failed to load config: {e}")
        
        return config
    
    def save(self, config_path: Optional[Path] = None):
        """Save configuration to file"""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.json"
        
        data = {
            'server': {
                'host': self.server.host,
                'port': self.server.port,
                'debug': self.server.debug,
                'cors_origins': self.server.cors_origins,
            },
            'ssh': {
                'default_port': self.ssh.default_port,
                'timeout': self.ssh.timeout,
                'keepalive_interval': self.ssh.keepalive_interval,
            },
            'database': {
                'path': self.database.path,
                'echo': self.database.echo,
            },
            'remote': {
                'agent_path': self.remote.agent_path,
                'log_path': self.remote.log_path,
                'python_cmd': self.remote.python_cmd,
            },
        }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# Global config instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get global configuration instance"""
    global _config
    if _config is None:
        _config = AppConfig.load()
    return _config
