"""
system – 系统级观察点

监测操作系统层面的资源与健康状态。

包含 (计划迁入):
- CpuUsageObserver        (cpu_usage):        CPU 使用率
- MemoryLeakObserver      (memory_leak):      内存泄漏
- LoadAverageObserver     (load_average):     系统负载
- SwapUsageObserver       (swap_usage):       Swap 使用率
- DiskSpaceObserver       (disk_space):       磁盘空间
- DiskIoObserver          (disk_io):          磁盘 IO
- FileDescriptorsObserver (file_descriptors): 文件描述符
- SystemUptimeObserver    (system_uptime):    系统运行时间
- DmesgErrorsObserver     (dmesg_errors):     dmesg 错误
- TcpConnectionsObserver  (tcp_connections):  TCP 连接数
"""

__all__: list = []
