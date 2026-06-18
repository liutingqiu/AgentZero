"""零 · 异步 LLM 服务
=====================
asyncio + httpx 非阻塞调用，解决线程池饥饿。

用法:
  from app.services.async_llm import async_call_llm
  reply = await async_call_llm(messages=[...])
"""

import asyncio
import logging
from config import get_logger
from utils.text_helpers import truncate

from cognition.token_tracker import tracker as token_tracker
from model_adapter import load_adapters

logger = get_logger('zero.async_llm')

# ── 共享适配器池 ─────────────────────────────────────
_ADAPTERS: list = []

def _init_adapters():
    global _ADAPTERS
    if _ADAPTERS:
        return
    _ADAPTERS = load_adapters({})

_init_adapters()


def _pick_candidates(task_type='text', prefer_free=True):
    """从已发现的适配器中选候选链（含预算自动降级，与 llm.py 对齐）。"""
    # 预算自动降级
    try:
        stats = token_tracker.session_stats()
        budget = stats.get('budget', 0)
        spent = stats.get('total_cost', 0)
        remaining = budget - spent
        threshold = getattr(token_tracker, '_degrade_threshold', 0.05)
        if budget > 0 and remaining <= 0:
            prefer_free = True
        elif budget > 0 and remaining < threshold:
            prefer_free = True
    except Exception:
        pass

    candidates = []
    for a in _ADAPTERS:
        if prefer_free and not a.meta.is_free:
            continue
        caps = a.capabilities()
        if task_type in ('image', 'image_generation') and caps.get('image_generation', 0) > 0:
            candidates.append(a)
        elif task_type in ('video', 'video_generation'):
            continue
        elif caps.get('chat', 0) > 0 or caps.get('reasoning', 0) > 0:
            candidates.append(a)
    if not candidates and not prefer_free:
        for a in _ADAPTERS:
            caps = a.capabilities()
            if caps.get('chat', 0) > 0 or caps.get('reasoning', 0) > 0:
                candidates.append(a)
    return candidates


async def async_call_llm(messages=None, *, system=None, prompt=None,
                         prefer_free=True, task_type='text', timeout=60,
                         task_text='', extra_rules='', agent_id='',
                         skip_ground=False) -> str:
    """异步 LLM 调用——非阻塞，协程友好。

    支持: messages 列表 或 (system, prompt) 旧式兼容。
    候选链: 通过 model_adapter 层自动发现。
    """
    from semantic_gateway import process as gateway_process
    from behavior_canon import (canonicalize as canon_behavior,
                                validate_output, retry_feedback, Path, SchemaMode)

    # 构建消息
    if messages is not None:
        msgs = list(messages)
    else:
        msgs = [{'role': 'system', 'content': system or ''},
                {'role': 'user', 'content': prompt or ''}]

    # Gateway + Canonicalizer
    try:
        msgs = gateway_process(msgs)
    except Exception as exc:
        return f'[语义协议违规] {exc}'

    ctx = canon_behavior(msgs, task_text=task_text, task_type=task_type,
                         agent_id=agent_id, extra_rules=extra_rules)
    msgs = ctx.messages
    prefer_explore = (ctx.path == Path.EXPLORATORY)
    temperature = ctx.temp_policy.sample(ctx.control_strength, prefer_explore)

    safe_msgs = []
    for m in msgs:
        role = m.get('role', 'user')
        content = str(m.get('content', ''))
        max_len = 2000 if role == 'system' else 4000
        safe_msgs.append({'role': role, 'content': truncate(content, max_len)})
    msgs = safe_msgs

    # 通过 model_adapter 层选择候选模型
    candidates = _pick_candidates(task_type, prefer_free)
    if not candidates:
        return '[模型不可用：请配置 AGNES_API_KEY 或 LLM_API_KEY 环境变量]'

    # ── LLM 响应缓存：同 session 内相同 prompt 直接命中 ──
    cache_key = token_tracker.make_hash(
        msgs, candidates[0].meta.adapter_id, temperature)
    cached_reply = token_tracker.cache_get(cache_key)
    if cached_reply is not None:
        logger.debug('缓存命中 [%s] %s..', cache_key[:8], task_text[:40])
        token_tracker.record(
            agent_id=agent_id or candidates[0].meta.adapter_id,
            model=candidates[0].meta.adapter_id,
            prompt_tokens=0, completion_tokens=len(cached_reply),
            cached=True, task_type=task_type,
        )
        return cached_reply

    max_retries = 2 if ctx.schema_mode == SchemaMode.STRICT else 0

    for adapter in candidates:
        retries = 0
        while retries <= max_retries:
            try:
                # 同步适配器 → 在线程池中执行
                result = await asyncio.to_thread(
                    adapter.chat, msgs,
                    temperature=temperature,
                    max_tokens=2000,
                    timeout=timeout,
                )
                if not result.ok:
                    logger.warning('[%s] 适配器返回错误: %s', adapter.meta.name, result.error)
                    break

                content = result.data
                if not content:
                    logger.warning('[%s] 空内容', adapter.meta.name)
                    break

                # 写入缓存（首个成功的候选模型）
                token_tracker.cache_set(cache_key, content)

                # 记录 Token 消耗（与 llm.py 对齐）
                token_tracker.record(
                    agent_id=agent_id or adapter.meta.adapter_id,
                    model=adapter.meta.adapter_id,
                    prompt_tokens=0,
                    completion_tokens=len(content),
                    cached=False, task_type=task_type,
                )

                passed, issues = validate_output(
                    content, ctx.control_strength, ctx.task_type,
                    mode=ctx.schema_mode)
                if passed or retries >= max_retries:
                    if not passed:
                        logger.debug('校验未通过: %s', issues)
                    from behavior_canon import record_outcome, auto_ground_v3
                    record_outcome(
                        task_type=ctx.task_type, agent_id=ctx.agent_id,
                        control_raw=ctx.control_raw,
                        control_final=ctx.control_strength,
                        success=passed, output_quality=0.7 if passed else 0.3)
                    if not skip_ground:
                        from app.services.llm import call_llm
                        auto_ground_v3(content, ctx.task_type, ctx.agent_id,
                                       ctx.control_strength, llm_caller=call_llm)
                    return content

                retries += 1
                msgs.append({'role': 'user',
                             'content': retry_feedback(issues, retries)})
            except Exception as exc:
                logger.warning('[%s] 失败: %s', adapter.meta.name, exc)
                break
    return '[所有模型不可用]'


def call_llm_async(messages=None, **kwargs) -> str:
    """同步包装——在事件循环中运行 async_call_llm。"""
    try:
        loop = asyncio.get_running_loop()
        # 已在事件循环中 → 直接 await（需要调用方是 async）
        raise RuntimeError('请在 async 函数中直接使用 async_call_llm')
    except RuntimeError:
        # 无事件循环 → 创建新循环运行
        return asyncio.run(async_call_llm(messages=messages, **kwargs))
