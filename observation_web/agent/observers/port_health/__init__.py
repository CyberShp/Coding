"""
port_health – 端口健康观察点

监测网络端口各维度的健康状态。

包含:
- PortCountersObserver (port_counters): 端口计数器 / 误码 / 丢包
- LinkStatusObserver  (link_status):   端口链路状态
- PortSpeedObserver   (port_speed):    端口速率
- PortFecObserver     (port_fec):      端口 FEC 状态
- SfpMonitorObserver  (sfp_monitor):   光模块监测
"""

__all__ = [
    'PortCountersObserver',
    'LinkStatusObserver',
    'PortSpeedObserver',
    'PortFecObserver',
    'SfpMonitorObserver',
]

# Re-export from sibling modules to allow `from observers.port_health import ...`
from ..port_counters import PortCountersObserver
from ..link_status import LinkStatusObserver
from ..port_speed import PortSpeedObserver
from ..port_fec import PortFecObserver
from ..sfp_monitor import SfpMonitorObserver
