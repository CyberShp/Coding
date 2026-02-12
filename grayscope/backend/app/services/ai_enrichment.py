"""AI 增强分析服务（增强版）。

对静态分析结果进行 AI 增强处理，生成测试建议、风险解释和结构化测试用例。
增强: 支持跨模块上下文、调用链信息、数据流路径传入 AI 提示词。
支持 synthesize_cross_module() 进行全局综合分析。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.ai import prompt_engine
from app.ai.provider_registry import get_provider
from app.analyzers.registry import get_display_name

logger = logging.getLogger(__name__)

# ── 模块 → 提示词模板映射 ──────────────────────────────────────────────
_MODULE_TEMPLATES: dict[str, str] = {
    "branch_path": "branch_path_analysis",
    "boundary_value": "boundary_value_analysis",
    "error_path": "error_path_analysis",
    "concurrency": "concurrency_analysis",
    "diff_impact": "diff_impact_analysis",
    "data_flow": "data_flow_analysis",
}


async def _call_model_async(
    provider_name: str,
    model: str,
    messages: list[dict[str, str]],
) -> dict:
    """异步调用 AI 模型并返回解析后的响应。"""
    provider = get_provider(provider_name, model=model)
    try:
        result = await provider.chat(messages, model=model)
        return {
            "content": result.get("content", ""),
            "usage": result.get("usage", {}),
            "success": True,
        }
    except Exception as exc:
        logger.warning("AI 调用失败 (%s/%s): %s", provider_name, model, exc)
        return {
            "content": "",
            "usage": {},
            "success": False,
            "error": str(exc),
        }


def _call_model_sync(
    provider_name: str,
    model: str,
    messages: list[dict[str, str]],
) -> dict:
    """同步调用 AI 模型。"""
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                _call_model_async(provider_name, model, messages)
            )
        finally:
            loop.close()
    except Exception as exc:
        logger.warning("AI 同步调用失败 (%s/%s): %s", provider_name, model, exc)
        return {
            "content": "",
            "usage": {},
            "success": False,
            "error": str(exc),
        }


def _build_cross_context(
    module_id: str,
    findings: list[dict[str, Any]],
    upstream_results: dict[str, dict] | None = None,
) -> dict[str, str]:
    """构建跨模块上下文信息，传入 AI 提示词模板。"""
    context: dict[str, str] = {}

    if not upstream_results:
        return context

    # 调用链上下文
    call_chain_parts = []
    cg_data = upstream_results.get("call_graph", {})
    for finding in cg_data.get("findings", [])[:5]:
        ev = finding.get("evidence", {})
        sym = finding.get("symbol_name", "")
        if ev.get("callees"):
            call_chain_parts.append(f"  {sym}() 调用: {', '.join(ev['callees'][:5])}")
        if ev.get("callers"):
            call_chain_parts.append(f"  {sym}() 被调用: {', '.join(ev['callers'][:5])}")
        if ev.get("caller_chains"):
            for chain in ev["caller_chains"][:2]:
                call_chain_parts.append(f"  调用链: {' → '.join(chain)}")

    if call_chain_parts:
        context["call_chain_context"] = "\n".join(call_chain_parts[:10])

    # 数据流路径
    df_parts = []
    df_data = upstream_results.get("data_flow", {})
    for finding in df_data.get("findings", [])[:5]:
        ev = finding.get("evidence", {})
        chain = ev.get("propagation_chain", [])
        if chain:
            path_str = " → ".join(
                f"{s['function']}({s['param']})" for s in chain[:6]
            )
            external = "外部输入" if ev.get("is_external_input") else "内部"
            df_parts.append(f"  [{external}] {path_str}")
            if ev.get("sensitive_ops"):
                df_parts.append(f"    到达敏感操作: {', '.join(ev['sensitive_ops'])}")

    if df_parts:
        context["data_flow_paths"] = "\n".join(df_parts[:10])

    # 跨模块发现
    cross_parts = []
    for mod_id, mod_data in upstream_results.items():
        if mod_id == module_id:
            continue
        mod_findings = mod_data.get("findings", [])
        high_risk = [f for f in mod_findings if f.get("risk_score", 0) > 0.7]
        if high_risk:
            mod_name = get_display_name(mod_id)
            for f in high_risk[:3]:
                cross_parts.append(
                    f"  [{mod_name}] {f.get('title', '')} (风险={f.get('risk_score', 0):.0%})"
                )

    if cross_parts:
        context["cross_module_findings"] = "\n".join(cross_parts[:10])

    return context


def enrich_module(
    module_id: str,
    findings: list[dict[str, Any]],
    source_snippets: dict[str, str],
    ai_config: dict,
    upstream_results: dict[str, dict] | None = None,
) -> dict:
    """对分析发现进行 AI 增强处理（增强版 —— 含跨模块上下文）。

    参数
    ----------
    module_id : str
        分析器模块标识
    findings : list
        静态分析器产出的原始发现列表
    source_snippets : dict
        {函数名: 源代码} 上下文信息
    ai_config : dict
        {"provider": "...", "model": "...", "prompt_profile": "..."}
    upstream_results : dict, optional
        所有上游模块的分析结果（用于构建跨模块上下文）

    返回
    -------
    dict，包含: ai_summary, test_suggestions, enriched_findings
    """
    display_name = get_display_name(module_id)
    template_id = _MODULE_TEMPLATES.get(module_id)
    if not template_id:
        return {
            "ai_summary": f"{display_name}暂无对应的提示词模板",
            "test_suggestions": [],
            "enriched_findings": findings,
            "success": False,
        }

    provider_name = ai_config.get("provider", "ollama")
    model = ai_config.get("model", "qwen2.5-coder")

    # 从最高风险的发现中构建上下文
    top_findings = findings[:10]
    findings_text = json.dumps(top_findings, indent=2, ensure_ascii=False)

    # 选取代表性的源代码片段
    snippet_text = ""
    for fn_name, src in list(source_snippets.items())[:3]:
        snippet_text += f"\n// --- {fn_name} ---\n{src[:2000]}\n"

    # 构建跨模块上下文
    cross_context = _build_cross_context(module_id, findings, upstream_results)

    # 构建提示词变量
    variables: dict[str, Any] = {
        "function_name": top_findings[0].get("symbol_name", "unknown") if top_findings else "unknown",
        "source_code": snippet_text[:4000],
        "cfg_summary": f"静态分析产出 {len(findings)} 条发现",
        "module_path": "",
        "shared_vars": "",
        "lock_usage": "",
        "changed_files": "",
        "changed_symbols": "",
        "diff_text": "",
        "depth": 2,
        "impacted_symbols": "",
        # 新增: 跨模块上下文变量
        "call_chain_context": cross_context.get("call_chain_context", ""),
        "data_flow_paths": cross_context.get("data_flow_paths", ""),
        "cross_module_findings": cross_context.get("cross_module_findings", ""),
    }

    try:
        messages = prompt_engine.render(template_id, variables)
    except Exception as exc:
        logger.warning("提示词渲染失败 [%s]: %s", display_name, exc)
        return {
            "ai_summary": f"提示词渲染失败: {exc}",
            "test_suggestions": [],
            "enriched_findings": findings,
            "success": False,
        }

    # 追加发现上下文作为后续用户消息
    messages.append({
        "role": "user",
        "content": (
            f"静态分析产出 {len(findings)} 条发现:\n"
            f"{findings_text[:3000]}\n\n"
            "基于这些发现和上面的调用链/数据流上下文，请提供:\n"
            "1. 风险摘要（特别注意跨函数的风险传播）\n"
            "2. 针对最高风险项的具体端到端测试用例建议（从入口函数开始）\n"
            "3. 静态分析未覆盖的其他风险区域\n"
            "请以 JSON 格式返回。"
        ),
    })

    # 调用 AI 模型
    logger.info("正在调用 AI 模型: %s/%s (消息数=%d)", provider_name, model, len(messages))
    ai_result = _call_model_sync(provider_name, model, messages)

    # 解析 AI 响应
    ai_content = ai_result.get("content", "")
    test_suggestions = _extract_test_suggestions(ai_content)

    if not ai_result.get("success"):
        err_msg = ai_result.get("error", "未知错误")
        logger.warning("AI 调用失败 [%s]: %s", display_name, err_msg)
        return {
            "ai_summary": f"{display_name} AI 增强不可用: {err_msg}",
            "test_suggestions": [],
            "enriched_findings": findings,
            "success": False,
            "error": err_msg,
            "usage": ai_result.get("usage", {}),
            "provider": provider_name,
            "model": model,
        }

    logger.info("AI 调用成功 [%s]: 响应长度=%d", display_name, len(ai_content))
    return {
        "ai_summary": ai_content[:5000] if ai_content else f"{display_name} AI 增强不可用",
        "test_suggestions": test_suggestions,
        "enriched_findings": findings,
        "success": True,
        "usage": ai_result.get("usage", {}),
        "provider": provider_name,
        "model": model,
    }


def synthesize_cross_module(
    all_module_results: dict[str, dict],
    source_snippets: dict[str, str],
    ai_config: dict,
) -> dict:
    """跨模块综合分析: 结合所有分析器的发现，生成全局视角的测试建议。

    在所有模块完成后调用，提供跨模块关联分析和端到端测试建议。
    """
    provider_name = ai_config.get("provider", "ollama")
    model = ai_config.get("model", "qwen2.5-coder")

    if not provider_name or provider_name.lower() in ("none", "", "skip"):
        return {
            "ai_summary": "未启用 AI 增强",
            "test_suggestions": [],
            "success": False,
            "skipped": True,
        }

    # 汇总所有模块的高风险发现
    all_high_risk: list[dict] = []
    module_summaries: list[str] = []

    for mod_id, mod_data in all_module_results.items():
        mod_findings = mod_data.get("findings", [])
        mod_risk = mod_data.get("risk_score", 0.0)
        high_risk = sorted(
            [f for f in mod_findings if f.get("risk_score", 0) > 0.6],
            key=lambda f: f.get("risk_score", 0),
            reverse=True,
        )[:5]
        all_high_risk.extend(high_risk)

        mod_name = get_display_name(mod_id)
        module_summaries.append(
            f"- {mod_name}: 风险={mod_risk:.0%}, 发现数={len(mod_findings)}, "
            f"高风险={len(high_risk)}"
        )

    # 提取数据流传播链
    df_chains = []
    df_data = all_module_results.get("data_flow", {})
    for finding in df_data.get("findings", [])[:10]:
        ev = finding.get("evidence", {})
        chain = ev.get("propagation_chain", [])
        if chain:
            path_str = " → ".join(f"{s['function']}({s['param']})" for s in chain[:8])
            df_chains.append({
                "path": path_str,
                "external": ev.get("is_external_input", False),
                "sensitive": ev.get("sensitive_ops", []),
            })

    # 构建综合提示
    system_msg = (
        "你是一个灰盒测试分析专家，擅长从多维度的静态分析结果中发现跨模块的隐藏风险，"
        "并设计端到端的测试方案。你需要:\n"
        "1. 关联不同分析器的发现（边界值 + 并发 + 错误路径 + 数据流），发现单模块无法看到的组合风险\n"
        "2. 基于数据流传播链，设计从入口函数到风险点的端到端测试场景\n"
        "3. 识别'看似正常的入口值经过多层调用变换后触发深层风险'的攻击路径\n"
        "4. 给出可操作的灰盒测试指导，帮助测试人员提升技术水平\n\n"
        "输出格式为 JSON。"
    )

    # 按风险排序 top findings
    all_high_risk.sort(key=lambda f: f.get("risk_score", 0), reverse=True)
    top_findings_text = json.dumps(all_high_risk[:15], indent=2, ensure_ascii=False)

    chains_text = "\n".join(
        f"  {'[外部输入]' if c['external'] else '[内部]'} {c['path']}"
        + (f" → 敏感操作: {', '.join(c['sensitive'])}" if c['sensitive'] else "")
        for c in df_chains
    )

    user_msg = (
        f"以下是对一个代码库的多维度静态分析结果综合:\n\n"
        f"**模块分析概要:**\n" + "\n".join(module_summaries) + "\n\n"
        f"**数据流传播链（参数如何跨函数传播）:**\n{chains_text}\n\n"
        f"**所有高风险发现（跨模块汇总，按风险排序）:**\n{top_findings_text[:4000]}\n\n"
        f"**代码片段:**\n"
    )

    for fn_name, src in list(source_snippets.items())[:3]:
        user_msg += f"\n// --- {fn_name} ---\n{src[:1500]}\n"

    user_msg += (
        "\n\n请提供:\n"
        "1. **跨模块风险关联**: 哪些发现来自不同模块但指向同一条调用链或同一个函数？"
        "组合起来的风险是什么？\n"
        "2. **隐藏风险路径**: 哪些看似不起眼的正常值入参，经过调用链变换后会触发深层风险？"
        "请给出具体的入口参数值和预期的风险触发点。\n"
        "3. **端到端测试方案**: 对于每个高风险链，设计从入口函数开始的完整测试用例，"
        "包括输入值、执行路径、预期行为。\n"
        "4. **灰盒测试改进建议**: 针对测试人员的技术提升，给出方法论层面的建议。\n\n"
        "请以 JSON 格式返回: { cross_module_risks, hidden_risk_paths, "
        "e2e_test_scenarios, methodology_advice }"
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    logger.info("正在执行跨模块 AI 综合分析: %s/%s", provider_name, model)
    ai_result = _call_model_sync(provider_name, model, messages)

    ai_content = ai_result.get("content", "")
    test_suggestions = _extract_test_suggestions(ai_content)

    if not ai_result.get("success"):
        err_msg = ai_result.get("error", "未知错误")
        return {
            "ai_summary": f"跨模块综合分析失败: {err_msg}",
            "test_suggestions": [],
            "success": False,
            "error": err_msg,
            "usage": ai_result.get("usage", {}),
            "provider": provider_name,
            "model": model,
        }

    return {
        "ai_summary": ai_content[:8000] if ai_content else "跨模块综合分析不可用",
        "test_suggestions": test_suggestions,
        "success": True,
        "usage": ai_result.get("usage", {}),
        "provider": provider_name,
        "model": model,
    }


def _extract_test_suggestions(ai_content: str) -> list[dict]:
    """尝试从 AI 响应中提取结构化的测试建议。"""
    if not ai_content:
        return []

    try:
        data = json.loads(ai_content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("test_suggestions", "tests", "test_cases", "branches",
                        "e2e_test_scenarios", "regression_tests", "test_scenarios"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]
    except json.JSONDecodeError:
        pass

    # 降级处理：返回原始文本块
    return [{"type": "raw_text", "content": ai_content[:3000]}]
