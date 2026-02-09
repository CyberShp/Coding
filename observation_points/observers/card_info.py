"""
卡件信息监控观察点

归属：卡件级检查
监测阵列上所有卡件的运行状态、健康状态、型号等关键信息。

命令回显格式（一次返回所有卡件）：
    No001  BoardId: xxxx
    No001  Name: xxxx
    No001  Model: xxxx
    No001  RunningState: RUNNING
    No001  HealthState: NORMAL
    ...
    ------------------
    No002  BoardId: xxxx
    No002  Model:
    ...

解析逻辑：
1. 按 '---+' 分隔各卡件文本块
2. 从每个块中提取卡号 (No\\d+)
3. 对每个块逐行匹配 BoardId / RunningState / HealthState / Model
"""

import logging
import re
from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class CardInfoObserver(BaseObserver):
    """
    卡件信息监控

    检查每张卡件的：
    - BoardId:      解析并附带到告警详情中，用于定位具体卡件
    - RunningState: 必须是 RUNNING，否则 ERROR
    - HealthState:  必须是 NORMAL，否则 ERROR
    - Model:        不能为空或 undefined/none/null/n/a，否则 WARNING

    配置项：
    - command: 查询所有卡件信息的命令（留空待用户填写）
    - running_state_expect: RunningState 预期值 (默认 "RUNNING")
    - health_state_expect:  HealthState 预期值 (默认 "NORMAL")
    """

    # 卡号匹配：No001, No002, ...
    CARD_NO_PATTERN = re.compile(r'(No\d+)', re.IGNORECASE)
    # 分隔符：多个连续横杠
    SEPARATOR_PATTERN = re.compile(r'-{3,}')

    # 字段匹配（关键字与值之间支持 = : 空格 🟰 等）
    FIELD_PATTERN_TEMPLATE = r'{keyword}\s*[=:\s\U0001F7F0]*\s*(\S*)'

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        # TODO: 用户在 config.json -> observers.card_info.command 中填写查询命令
        self.command = config.get('command', '')
        self.running_expect = config.get('running_state_expect', 'RUNNING')
        self.health_expect = config.get('health_state_expect', 'NORMAL')

        # Model 异常值列表（视同为空）
        self._model_invalid_values = {'undefined', 'none', 'null', 'n/a', ''}

        # 编译匹配正则
        self._re_running = re.compile(
            self.FIELD_PATTERN_TEMPLATE.format(keyword='RunningState'),
            re.IGNORECASE,
        )
        self._re_health = re.compile(
            self.FIELD_PATTERN_TEMPLATE.format(keyword='HealthState'),
            re.IGNORECASE,
        )
        self._re_model = re.compile(
            self.FIELD_PATTERN_TEMPLATE.format(keyword='Model'),
            re.IGNORECASE,
        )
        self._re_board_id = re.compile(
            self.FIELD_PATTERN_TEMPLATE.format(keyword='BoardId'),
            re.IGNORECASE,
        )

    def check(self) -> ObserverResult:
        if not self.command:
            return self.create_result(
                has_alert=False,
                message="卡件信息监控未配置命令 (observers.card_info.command)",
            )

        ret, stdout, stderr = run_command(self.command, shell=True, timeout=15)
        if ret != 0:
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"卡件信息查询命令执行失败: {stderr[:200]}",
            )

        cards = self._parse_cards(stdout)
        if not cards:
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message="卡件信息查询无数据或解析失败",
            )

        alerts = []  # type: List[Dict[str, Any]]
        card_details = {}

        for card_no, fields in cards.items():
            card_details[card_no] = fields
            issues = []

            # 检查 RunningState
            running = fields.get('RunningState', '')
            if running and running != self.running_expect:
                issues.append({
                    'field': 'RunningState',
                    'value': running,
                    'expect': self.running_expect,
                    'level': 'error',
                })
            elif not running:
                issues.append({
                    'field': 'RunningState',
                    'value': '(未检测到)',
                    'expect': self.running_expect,
                    'level': 'warning',
                })

            # 检查 HealthState
            health = fields.get('HealthState', '')
            if health and health != self.health_expect:
                issues.append({
                    'field': 'HealthState',
                    'value': health,
                    'expect': self.health_expect,
                    'level': 'error',
                })
            elif not health:
                issues.append({
                    'field': 'HealthState',
                    'value': '(未检测到)',
                    'expect': self.health_expect,
                    'level': 'warning',
                })

            # 检查 Model（空值 或 undefined/none/null/n/a 均告警）
            model = fields.get('Model', '')
            if not model or model.lower() in self._model_invalid_values:
                display_value = f'({model})' if model else '(空)'
                issues.append({
                    'field': 'Model',
                    'value': display_value,
                    'expect': '非空且有效',
                    'level': 'warning',
                })

            # 提取 BoardId 用于定位
            board_id = fields.get('BoardId', '')

            for issue in issues:
                alert_entry = {
                    'card': card_no,
                    **issue,
                }
                if board_id:
                    alert_entry['board_id'] = board_id
                alerts.append(alert_entry)

        if alerts:
            # 构建消息
            error_alerts = [a for a in alerts if a['level'] == 'error']
            warn_alerts = [a for a in alerts if a['level'] == 'warning']

            msg_parts = []
            for a in (error_alerts + warn_alerts)[:6]:
                card_label = a['card']
                if a.get('board_id'):
                    card_label = f"{a['card']} (BoardId: {a['board_id']})"
                msg_parts.append(
                    f"卡件 {card_label} {a['field']} 异常: {a['value']} (预期: {a['expect']})"
                )
            if len(alerts) > 6:
                msg_parts.append(f"...共 {len(alerts)} 项异常")

            level = AlertLevel.ERROR if error_alerts else AlertLevel.WARNING

            return self.create_result(
                has_alert=True,
                alert_level=level,
                message='; '.join(msg_parts),
                details={
                    'alerts': alerts,
                    'cards': card_details,
                    'total_cards': len(cards),
                },
            )

        return self.create_result(
            has_alert=False,
            message=f"卡件信息正常 ({len(cards)} 张卡)",
            details={'cards': card_details, 'total_cards': len(cards)},
        )

    def _parse_cards(self, stdout: str) -> Dict[str, Dict[str, str]]:
        """
        解析命令回显，按卡件分组并提取关键字段。

        Returns:
            {card_no: {BoardId: ..., RunningState: ..., HealthState: ..., Model: ...}}
        """
        # 按分隔符切分
        blocks = self.SEPARATOR_PATTERN.split(stdout)
        cards = {}  # type: Dict[str, Dict[str, str]]

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # 提取卡号
            card_match = self.CARD_NO_PATTERN.search(block)
            card_no = card_match.group(1) if card_match else f"Unknown_{len(cards)}"

            fields = {}

            # 逐行匹配关键字段
            for line in block.split('\n'):
                line = line.strip()
                if not line:
                    continue

                m = self._re_board_id.search(line)
                if m:
                    fields['BoardId'] = m.group(1).strip()

                m = self._re_running.search(line)
                if m:
                    fields['RunningState'] = m.group(1).strip()

                m = self._re_health.search(line)
                if m:
                    fields['HealthState'] = m.group(1).strip()

                m = self._re_model.search(line)
                if m:
                    fields['Model'] = m.group(1).strip()

            cards[card_no] = fields

        return cards
