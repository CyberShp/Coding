"""
process – 进程级观察点

监测关键进程的运行状态。

包含 (计划迁入):
- ProcessCrashObserver   (process_crash):   进程崩溃
- ProcessRestartObserver (process_restart): 进程重启
- ZombieProcessesObserver (zombie_processes): 僵尸进程
- IoTimeoutObserver      (io_timeout):      IO 超时
"""

__all__: list = []
