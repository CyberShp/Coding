"""
[DEPRECATED] 此模块已合并至 port_counters.py (PortCountersObserver)。
保留此文件以兼容旧的 import 路径和配置中的类名引用。
"""

from .port_counters import PortCountersObserver

# Backward-compatible alias
PortErrorCodeObserver = PortCountersObserver

__all__ = ['PortErrorCodeObserver']
