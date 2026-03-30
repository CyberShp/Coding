"""
gate – 前置检查观察点

此目录存放在正式巡检前执行的"门控"检查，例如阵列开工状态。
只有门控检查通过，后续观察点才有意义。

包含:
- StartWorkObserver: 阵列开工状态检查
"""

from .start_work import StartWorkObserver

__all__ = ['StartWorkObserver']
