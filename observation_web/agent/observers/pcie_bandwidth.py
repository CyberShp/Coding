"""
PCIe 带宽 downgrade 监测观察点

归属：卡件级检查
监测 PCIe 链路宽度/速率是否发生 downgrade（如 x16->x8, Gen4->Gen3）。

内置通用方式：
1. 通过 lspci -vvv 解析 LnkCap（最大能力）和 LnkSta（当前状态）
2. 如果 LnkSta < LnkCap，视为 downgrade
3. 同时对比上次读数，检测动态 downgrade

如果配置了 command 则优先使用自定义命令。
当降级恢复后，自动发出恢复告警，活跃问题面板中对应条目消失。
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class PcieBandwidthObserver(BaseObserver):
    """
    PCIe 带宽 downgrade 监测

    工作方式（二选一）：
    1. 内置模式（默认）：通过 lspci -vvv 自动解析各 PCIe 设备的
       LnkCap（链路能力）和 LnkSta（当前状态），检测 downgrade
    2. 自定义命令模式：配置 command 字段

    配置项：
    - command: 自定义命令（可选，留空则使用内置 lspci）
    - parse_pattern: 自定义命令的解析正则
    - device_filter: 只监测含有特定关键字的 PCIe 设备（如 "Non-Volatile", "Ethernet"）
    """

    # lspci -vvv 输出解析
    # 设备行: "0000:3b:00.0 Non-Volatile memory controller: ..."
    DEVICE_PATTERN = re.compile(r'^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)\s+(.*)')
    # LnkCap: Speed 16GT/s (Gen4), Width x16  或  Speed 16GT/s, Width x16
    LNKCAP_PATTERN = re.compile(r'LnkCap:.*?Speed\s+(\S+?)[\s(,].*?Width\s+(x\d+)', re.IGNORECASE)
    # LnkSta: Speed 8GT/s (Gen3), Width x8  或  Speed 16GT/s, Width x16
    LNKSTA_PATTERN = re.compile(r'LnkSta:.*?Speed\s+(\S+?)[\s(,].*?Width\s+(x\d+)', re.IGNORECASE)

    # 自定义命令的默认解析正则
    DEFAULT_PATTERN = r'(?P<device>\S+)\s+(?P<width>x\d+)\s+(?P<speed>\S+)'

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get('command', '')
        self.parse_pattern = re.compile(
            config.get('parse_pattern', self.DEFAULT_PATTERN)
        )
        self.device_filter = config.get('device_filter', [])
        self._last_link = {}  # type: Dict[str, Dict[str, str]]
        self._first_run = True
        self._was_alerting = False  # 用于检测降级→恢复的状态转换

    def check(self) -> ObserverResult:
        if self.command:
            current_link, cap_downgrades = self._collect_via_command()
        else:
            current_link, cap_downgrades = self._collect_via_lspci()

        if not current_link:
            return self.create_result(
                has_alert=False,
                message="PCIe 带宽查询无数据（可能 lspci 不可用）",
            )

        downgrades = list(cap_downgrades)  # 来自 LnkCap vs LnkSta 的 downgrade

        # 检测动态 downgrade（与上次读数对比）
        if not self._first_run:
            for dev, info in current_link.items():
                old_info = self._last_link.get(dev)
                if old_info is None:
                    continue
                old_w = self._parse_width(old_info.get('width', ''))
                new_w = self._parse_width(info.get('width', ''))
                if old_w > 0 and new_w > 0 and new_w < old_w:
                    downgrades.append(
                        f"{dev} 宽度动态降级: x{old_w} -> x{new_w}"
                    )
                old_s = old_info.get('speed', '')
                new_s = info.get('speed', '')
                if old_s and new_s and self._speed_rank(new_s) < self._speed_rank(old_s):
                    downgrades.append(
                        f"{dev} 速率动态降级: {old_s} -> {new_s}"
                    )

        self._last_link = current_link
        self._first_run = False

        if downgrades:
            self._was_alerting = True
            logger.warning(f"[PCIeBW] {'; '.join(downgrades)}")
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"PCIe 带宽降级: {'; '.join(downgrades[:5])}",
                details={
                    'downgrades': downgrades,
                    'current': current_link,
                },
            )

        # 之前有降级，现在恢复了 → 发出恢复告警
        if self._was_alerting:
            self._was_alerting = False
            message = f"PCIe 带宽恢复正常 ({len(current_link)} 设备)"
            logger.info(f"[PCIeBW] {message}")
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message=message,
                details={
                    'recovered': True,
                    'current': current_link,
                },
                sticky=True,  # bypass cooldown 确保恢复事件被上报
            )

        return self.create_result(
            has_alert=False,
            message=f"PCIe 带宽正常 ({len(current_link)} 设备)",
            details={'current': current_link},
        )

    # ---------- 内置 lspci 模式 ----------

    def _collect_via_lspci(self) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
        """
        使用 lspci -vvv 解析 PCIe 链路信息。

        Returns:
            (current_link, cap_downgrades)
            current_link: {device_addr: {width, speed, cap_width, cap_speed, desc}}
            cap_downgrades: 当前 LnkSta < LnkCap 的设备告警列表
        """
        ret, stdout, _ = run_command('lspci -vvv 2>/dev/null', shell=True, timeout=15)
        if ret != 0:
            return {}, []

        current_link = {}
        cap_downgrades = []
        current_device = None
        current_desc = ''
        cap_speed = cap_width = ''
        sta_speed = sta_width = ''

        for line in stdout.split('\n'):
            # 设备头
            dm = self.DEVICE_PATTERN.match(line)
            if dm:
                # 先保存上一个设备
                if current_device and sta_width:
                    self._save_device(
                        current_device, current_desc,
                        cap_speed, cap_width, sta_speed, sta_width,
                        current_link, cap_downgrades,
                    )
                current_device = dm.group(1)
                current_desc = dm.group(2)
                cap_speed = cap_width = sta_speed = sta_width = ''
                continue

            # LnkCap
            cm = self.LNKCAP_PATTERN.search(line)
            if cm:
                cap_speed = cm.group(1)
                cap_width = cm.group(2)

            # LnkSta
            sm = self.LNKSTA_PATTERN.search(line)
            if sm:
                sta_speed = sm.group(1)
                sta_width = sm.group(2)

        # 最后一个设备
        if current_device and sta_width:
            self._save_device(
                current_device, current_desc,
                cap_speed, cap_width, sta_speed, sta_width,
                current_link, cap_downgrades,
            )

        return current_link, cap_downgrades

    def _save_device(
        self, device: str, desc: str,
        cap_speed: str, cap_width: str,
        sta_speed: str, sta_width: str,
        current_link: Dict, cap_downgrades: List,
    ):
        """保存解析后的设备信息，并检测 Cap vs Sta downgrade"""
        # 过滤设备
        if self.device_filter:
            if not any(kw.lower() in desc.lower() for kw in self.device_filter):
                return

        current_link[device] = {
            'width': sta_width,
            'speed': sta_speed,
            'cap_width': cap_width,
            'cap_speed': cap_speed,
            'desc': desc[:80],
        }

        # Cap vs Sta 比较
        cw = self._parse_width(cap_width)
        sw = self._parse_width(sta_width)
        if cw > 0 and sw > 0 and sw < cw:
            cap_downgrades.append(
                f"{device} 宽度降级: 能力 {cap_width} / 当前 {sta_width} ({desc[:40]})"
            )

        cs = self._speed_rank(cap_speed)
        ss = self._speed_rank(sta_speed)
        if cs > 0 and ss > 0 and ss < cs:
            cap_downgrades.append(
                f"{device} 速率降级: 能力 {cap_speed} / 当前 {sta_speed} ({desc[:40]})"
            )

    # ---------- 自定义命令模式 ----------

    def _collect_via_command(self) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
        """使用用户自定义命令收集"""
        ret, stdout, stderr = run_command(self.command, shell=True, timeout=10)
        if ret != 0:
            logger.warning(f"[PCIeBW] 自定义命令执行失败: {stderr[:200]}")
            return {}, []

        result = {}
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            m = self.parse_pattern.search(line)
            if m:
                result[m.group('device')] = {
                    'width': m.group('width'),
                    'speed': m.group('speed'),
                }
        return result, []

    # ---------- 工具方法 ----------

    @staticmethod
    def _parse_width(w: str) -> int:
        """解析 x16 -> 16"""
        m = re.search(r'x?(\d+)', w)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _speed_rank(speed: str) -> int:
        """将速率字符串转为排序值，越高越好"""
        if not speed:
            return 0
        speed_lower = speed.lower()
        ranks = {
            'gen1': 1, '2.5gt': 1, '2.5gt/s': 1,
            'gen2': 2, '5gt': 2, '5.0gt': 2, '5gt/s': 2, '5.0gt/s': 2,
            'gen3': 3, '8gt': 3, '8.0gt': 3, '8gt/s': 3, '8.0gt/s': 3,
            'gen4': 4, '16gt': 4, '16.0gt': 4, '16gt/s': 4, '16.0gt/s': 4,
            'gen5': 5, '32gt': 5, '32.0gt': 5, '32gt/s': 5, '32.0gt/s': 5,
        }
        for k, v in ranks.items():
            if k in speed_lower:
                return v
        return 0
