"""
AI service for alert interpretation.
Calls internal LLM API to generate human-readable alert summaries.
Gracefully degrades when API is unavailable - never affects core functionality.
"""

import json
import logging
from typing import Optional

import httpx

from ..config import get_config

logger = logging.getLogger(__name__)

# Observer Chinese names for prompt context (mirrors frontend OBSERVER_NAMES)
OBSERVER_NAMES = {
    "error_code": "误码监测",
    "link_status": "链路状态",
    "port_fec": "FEC 模式",
    "port_speed": "端口速率",
    "port_traffic": "端口流量",
    "card_recovery": "卡修复",
    "card_info": "卡件信息",
    "pcie_bandwidth": "PCIe 带宽",
    "alarm_type": "告警事件",
    "memory_leak": "内存监测",
    "cpu_usage": "CPU 监测",
    "cmd_response": "命令响应",
    "sig_monitor": "SIG 信号",
    "sensitive_info": "敏感信息",
    "controller_state": "控制器状态",
    "disk_state": "磁盘状态",
    "process_crash": "进程崩溃",
    "io_timeout": "IO 超时",
}

LEVEL_NAMES = {
    "info": "信息",
    "warning": "警告",
    "error": "错误",
    "critical": "严重",
}


def _build_prompt(observer_name: str, level: str, message: str, details: dict) -> str:
    """Build the prompt for alert interpretation."""
    obs_cn = OBSERVER_NAMES.get(observer_name, observer_name)
    level_cn = LEVEL_NAMES.get(level, level)
    details_str = json.dumps(details, ensure_ascii=False, indent=2) if details else "{}"

    return f"""你是存储阵列测试监控专家。请用通俗中文解读以下告警，帮助测试人员快速理解。

【告警信息】
- 观察点：{observer_name}（{obs_cn}）
- 级别：{level_cn}
- 原始消息：
{message}

- 结构化数据：
{details_str}

【要求】
1. 用日常语言解释这条告警的含义，将英文缩写和专业术语翻译为易理解的中文
   （如 objType:ETH_PORT → 以太网端口对象，AlarmId:0xA001 → 告警编号 A001）
2. 分析可能原因（2-3 条）
3. 给出具体排查建议
4. 输出控制在 300 字以内
"""


async def interpret_alert(
    observer_name: str,
    level: str,
    message: str,
    details: dict,
) -> Optional[str]:
    """
    Call LLM API to interpret an alert. Returns None on any failure.
    Never raises - always degrades gracefully.
    """
    config = get_config()
    if not config.ai.enabled:
        logger.debug("AI interpretation disabled in config")
        return None

    api_url = config.ai.api_url
    api_key = config.ai.api_key
    model = config.ai.model
    timeout = config.ai.timeout
    max_tokens = config.ai.max_tokens

    prompt = _build_prompt(observer_name, level, message, details)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(api_url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # OpenAI-compatible response format
        choices = data.get("choices", [])
        if not choices:
            logger.warning("AI API returned empty choices")
            return None

        content = choices[0].get("message", {}).get("content", "")
        if not content or not content.strip():
            return None

        return content.strip()
    except httpx.TimeoutException:
        logger.warning("AI API timeout after %ds", timeout)
        return None
    except httpx.HTTPStatusError as e:
        logger.warning("AI API HTTP error: %s %s", e.response.status_code, e.response.text[:200])
        return None
    except Exception as e:
        logger.warning("AI interpretation failed: %s", e, exc_info=True)
        return None


def is_ai_available() -> bool:
    """Check if AI service is configured and enabled."""
    config = get_config()
    return bool(config.ai.enabled and config.ai.api_url)
