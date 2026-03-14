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
    CARD_BLOCK_START_PATTERN = re.compile(r'^\s*(No0\d+)\b', re.IGNORECASE)
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
        self._model_invalid_values = {'undefined', 'undefine', 'none', 'null', 'n/a', ''}

        # 用于检测异常→恢复的状态转换
        self._was_alerting = False

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
                has_alert=False,
                message="卡件信息本轮无有效卡件数据，已忽略",
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

            if issues:
                alert_entry = {
                    'card': card_no,
                    'fields': issues,
                    'level': 'error' if any(i.get('level') == 'error' for i in issues) else 'warning',
                }
                if board_id:
                    alert_entry['board_id'] = board_id
                alerts.append(alert_entry)

        if alerts:
            self._was_alerting = True
            # 构建消息
            error_alerts = [a for a in alerts if a['level'] == 'error']
            warn_alerts = [a for a in alerts if a['level'] == 'warning']

            msg_parts = []
            for a in (error_alerts + warn_alerts)[:6]:
                card_label = a['card']
                if a.get('board_id'):
                    card_label = f"{a['card']} (BoardId: {a['board_id']})"
                field_msgs = []
                for issue in a.get('fields', []):
                    field_msgs.append(f"{issue.get('field')}: {issue.get('value')} (预期: {issue.get('expect')})")
                msg_parts.append(f"卡件 {card_label} 异常: {', '.join(field_msgs)}")
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

        # 之前有异常，现在全部正常 → 发出恢复告警
        if self._was_alerting:
            self._was_alerting = False
            message = f"卡件信息恢复正常 ({len(cards)} 张卡)"
            logger.info(message)
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message=message,
                details={
                    'recovered': True,
                    'cards': card_details,
                    'total_cards': len(cards),
                },
                sticky=True,  # bypass cooldown 确保恢复事件被上报
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
        cards = {}  # type: Dict[str, Dict[str, str]]
        current_card_no = None  # type: Optional[str]
        current_fields = {}  # type: Dict[str, str]

        def flush_current():
            nonlocal current_card_no, current_fields
            if current_card_no:
                cards[current_card_no] = dict(current_fields)
            current_card_no = None
            current_fields = {}

        for raw_line in (stdout or '').splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if self.SEPARATOR_PATTERN.fullmatch(line):
                flush_current()
                continue

            card_start = self.CARD_BLOCK_START_PATTERN.match(line)
            if card_start:
                card_no = card_start.group(1)
                if current_card_no and card_no != current_card_no:
                    flush_current()
                current_card_no = card_no
                self._parse_card_line(line, current_fields)
                continue

            if current_card_no:
                self._parse_card_line(line, current_fields)

        flush_current()
        return cards

    def _parse_card_line(self, line: str, fields: Dict[str, str]) -> None:
        """Parse one line inside a valid card block."""
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
