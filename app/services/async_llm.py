"""零 · 异步 LLM 服务
=====================
asyncio + httpx 非阻塞调用，解决线程池饥饿。

用法:
  from app.services.async_llm import async_call_llm
  reply = await async_call_llm(messages=[...])
"""

import json
import logging
from config import (AGNES_API_URL, get_agnes_key, get_api_key, get_api_url)
from utils.text_helpers import truncate

logger = logging.getLogger('zero.async_llm')

AGNES_MODELS = {
    'text': 'agnes-2.0-flash',
    'image': 'agnes-image-2.1-flash',
    'video': 'agnes-video-v2.0',
}

def _select_model(task_type='text'):
    if task_type in ('image', 'image_generation'): return AGNES_MODELS['image']
    if task_type in ('video', 'video_generation'): return AGNES_MODELS['video']
    return AGNES_MODELS['text']


async def async_call_llm(messages=None, *, system=None, prompt=None,
                         prefer_free=True, task_type='text', timeout=60,
                         task_text='', extra_rules='', agent_id='',
                         skip_ground=False) -> str:
    """异步 LLM 调用——非阻塞，协程友好。

    支持: messages 列表 或 (system, prompt) 旧式兼容。
    候选链: Agnes(免费) → DeepSeek(付费)
    """
    import httpx
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

    # 候选链
    candidates = []
    ak = get_agnes_key()
    if prefer_free and ak:
        candidates.append({'name': 'agnes', 'url': AGNES_API_URL,
                           'key': ak, 'model': _select_model(task_type)})
    dk = get_api_key()
    du = get_api_url()
    if dk:
        candidates.append({'name': 'deepseek', 'url': du, 'key': dk,
                           'model': 'deepseek-chat'})
    if not candidates:
        return '[模型不可用]'

    max_retries = 2 if ctx.schema_mode == SchemaMode.STRICT else 0

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        for c in candidates:
            retries = 0
            while retries <= max_retries:
                try:
                    resp = await client.post(
                        c['url'],
                        json={'model': c['model'], 'messages': msgs,
                              'max_tokens': 2000, 'temperature': temperature},
                        headers={'Authorization': f'Bearer {c["key"]}',
                                 'Content-Type': 'application/json'},
                    )
                    data = resp.json()
                    content = data['choices'][0]['message']['content']
                    if not content:
                        logger.warning('[%s] 空内容', c['name'])
                        break

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
                    logger.warning('[%s] 失败: %s', c['name'], exc)
                    break
    return '[所有模型不可用]'


def call_llm_async(messages=None, **kwargs) -> str:
    """同步包装——在事件循环中运行 async_call_llm。"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        # 已在事件循环中 → 直接 await（需要调用方是 async）
        raise RuntimeError('请在 async 函数中直接使用 async_call_llm')
    except RuntimeError:
        # 无事件循环 → 创建新循环运行
        return asyncio.run(async_call_llm(messages=messages, **kwargs))
