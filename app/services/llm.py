"""零 · 核心服务层
================
LLM 调用、消息处理、Token 管理。

从 zero_server.py 剥离——P0 单体拆分。
"""

import json
import os
import secrets
import sys
import threading
import time
import uuid
from datetime import datetime

from config import (
    AGNES_API_URL, DATA_DIR, HTTP_HOST, HTTP_PORT,
    MEMORY_DB, UNLOCK_DURATION_SECONDS, ZERO_ROOT,
    get_agnes_key, get_api_key, get_api_url, get_logger,
)
from utils.json_helpers import extract_first_json
from utils.text_helpers import truncate

os.chdir(ZERO_ROOT)
logger = get_logger('zero.service')

from message_bus import TaskStateMachine, get_bus
from security.guard import SessionManager, detect_jailbreak
from cognition import memory_manager
from cognition.working_memory import WorkingMemory
from cognition.token_tracker import tracker as token_tracker
from action.agent_loop import AgentLoop
from action.agent_registry import AgentRegistry, seed_defaults
from action.reviewer import Reviewer
from action.tools import execute as tool_execute, set_permission_level

from model_adapter import load_adapters
from model_adapter.base import ModelAdapter

# ── 模型适配器层: 模块级初始化 ─────────────────────────────
_ADAPTERS: list = []

def _init_adapters():
    """初始化模型适配器（幂等，模块加载时自动调用）。"""
    global _ADAPTERS
    if _ADAPTERS:
        return
    _ADAPTERS = load_adapters({})
    if not _ADAPTERS:
        logger.warning('未发现任何可用模型适配器')

_init_adapters()

def _pick_candidates(task_type='text', prefer_free=True):
    """从已发现的适配器中选候选链（免费优先）。
    
    预算检查（无条件，每次调用都检查）：
      - 剩余预算低于阈值 → 强制走免费模型
      - 预算已耗尽 → 拒绝所有付费模型
    """
    # 预算自动降级：剩余不足时强制免费
    stats = token_tracker.session_stats()
    budget = stats.get('budget', 0)
    spent = stats.get('total_cost', 0)
    remaining = budget - spent
    threshold = getattr(token_tracker, '_degrade_threshold', 0.05)  # 降级阈值（美元）

    if budget > 0 and remaining <= 0:
        # 预算已耗尽，彻底走免费
        logger.info('预算耗尽 ($%.4f/$%.4f)，仅使用免费模型', spent, budget)
        prefer_free = True
    elif budget > 0 and remaining < threshold:
        # 预算余量不足，自动降级
        logger.info('预算不足 (剩余$%.4f < 阈值$%.4f)，自动降级到免费模型', remaining, threshold)
        prefer_free = True
    
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


def _check_budget(prefer_free: bool) -> bool:
    """检查预算是否充足。返回 True 表示可用，False 表示应拒绝调用。
    
    预算不足时 logger 告警，由调用方决定行为。
    """
    stats = token_tracker.session_stats()
    budget = stats.get('budget', 0)
    if budget <= 0:
        return True  # 没设预算不限制
    spent = stats.get('total_cost', 0)
    remaining = budget - spent
    if remaining <= 0:
        logger.warning('月度预算已耗尽 ($%.4f / $%.4f)', spent, budget)
        return False
    return True


def call_llm(system=None, prompt=None, *, messages=None,
             prefer_free=True, task_type='text', timeout=30,
             task_text='', extra_rules='', agent_id='', skip_ground=False,
             _depth=0):
    # 递归深度保护
    if _depth > 3:
        return '[递归深度超限，预算检查异常，请检查配置]'

    # 预算检查
    if not _check_budget(prefer_free):
        # 预算耗尽，尝试强制免费模型
        if not prefer_free:
            logger.info('预算不足，自动降级到免费模型')
            return call_llm(system=system, prompt=prompt, messages=messages,
                           prefer_free=True, task_type=task_type, timeout=timeout,
                           task_text=task_text, extra_rules=extra_rules,
                           agent_id=agent_id, skip_ground=skip_ground,
                           _depth=_depth + 1)
        return '[预算已耗尽，请等待下个周期或配置更多预算]'
    
    if messages is not None:
        msgs = list(messages)
    else:
        msgs = [{'role':'system','content':system or ''},{'role':'user','content':prompt or ''}]

    from semantic_gateway import process as gateway_process
    try: msgs = gateway_process(msgs)
    except Exception as exc:
        logger.error('Gateway 拒绝消息: %s', exc)
        return f'[语义协议违规] {exc}'

    from behavior_canon import (canonicalize as canon_behavior,
                                validate_output, retry_feedback, Path)
    ctx = canon_behavior(msgs, task_text=task_text, task_type=task_type,
                         agent_id=agent_id, extra_rules=extra_rules)
    msgs = ctx.messages
    prefer_explore = (ctx.path == Path.EXPLORATORY)
    temperature = ctx.temp_policy.sample(ctx.control_strength, prefer_explore)

    safe_msgs = []
    for m in msgs:
        role = m.get('role','user'); content = str(m.get('content',''))
        max_len = 2000 if role == 'system' else 4000
        safe_msgs.append({'role':role,'content':truncate(content,max_len)})
    msgs = safe_msgs

    # 通过 model_adapter 层选择候选模型（已集成预算降级）
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

    from behavior_canon import SchemaMode
    max_retries = 2 if ctx.schema_mode == SchemaMode.STRICT else 0

    for adapter in candidates:
        retries = 0
        while retries <= max_retries:
            try:
                result = adapter.chat(
                    msgs,
                    temperature=temperature,
                    max_tokens=2000,
                    timeout=timeout,
                )
                if not result.ok:
                    logger.warning('[%s] 适配器返回错误: %s', adapter.meta.name, result.error)
                    break

                content = result.data
                if not content:
                    logger.warning('[%s] 返回空内容', adapter.meta.name)
                    break

                # 写入缓存（首个成功的候选模型）
                token_tracker.cache_set(cache_key, content)

                # 记录 Token 消耗（适配器当前不返回 usage，估算）
                token_tracker.record(
                    agent_id=agent_id or adapter.meta.adapter_id,
                    model=adapter.meta.adapter_id,
                    prompt_tokens=0,
                    completion_tokens=len(content),
                    cached=False, task_type=task_type,
                )

                passed, issues = validate_output(content, ctx.control_strength,
                                                  ctx.task_type, mode=ctx.schema_mode)
                if passed or retries >= max_retries:
                    if not passed: logger.debug('校验未通过(重试耗尽): %s',issues)
                    from behavior_canon import record_outcome
                    record_outcome(task_type=ctx.task_type,agent_id=ctx.agent_id,
                        control_raw=ctx.control_raw,control_final=ctx.control_strength,
                        success=passed,output_quality=0.7 if passed else 0.3)
                    if not skip_ground:
                        from behavior_canon import auto_ground_v3
                        auto_ground_v3(content,ctx.task_type,ctx.agent_id,
                                       ctx.control_strength,llm_caller=call_llm)
                    return content
                retries += 1
                logger.debug('[%s] 重试%d: %s', adapter.meta.name, retries, issues)
                msgs.append({'role':'user','content':retry_feedback(issues,retries)})
            except Exception as exc:
                logger.warning('[%s] 失败: %s', adapter.meta.name, exc)
                break
    return '[所有模型不可用，请稍后重试]'


class TokenStore:
    def __init__(self, ttl_seconds: int):
        self._tokens: dict[str,float] = {}; self._lock = threading.Lock(); self._ttl = ttl_seconds
    def issue(self) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = time.time() + self._ttl
            now = time.time()
            expired = [t for t,exp in self._tokens.items() if exp < now]
            for t in expired: del self._tokens[t]
        return token
    def validate(self, token: str) -> bool:
        if not token: return False
        with self._lock:
            exp = self._tokens.get(token)
            if exp and exp > time.time(): return True
            if exp: del self._tokens[token]
        return False
    def count(self) -> int:
        with self._lock: return len(self._tokens)

bus = get_bus(); session = SessionManager(); wm = WorkingMemory()
tokens = TokenStore(ttl_seconds=UNLOCK_DURATION_SECONDS)
tsm = TaskStateMachine(bus); registry = AgentRegistry()
reviewer = None

def _build_agent_context() -> str:
    now = datetime.now()
    weekday_cn = ['一','二','三','四','五','六','日'][now.weekday()]
    hour = now.hour
    period = ('凌晨' if hour<6 else '早上' if hour<9 else '上午' if hour<12 else '下午' if hour<18 else '晚上')
    parts = [f'当前时间: {now.month}/{now.day} 周{weekday_cn} {period}']
    if wm.active_project: parts.append(f'活跃项目: {wm.active_project}')
    today = memory_manager.get_today_state()
    if today: parts.append(f'今日: {today.get("messages_count",0)}消息 {today.get("tasks_completed",0)}任务')
    summaries = memory_manager.get_conversation_summaries(days=3,limit=3)
    if summaries: parts.append('最近话题: '+'；'.join(s['topic'][:30] for s in summaries))
    return '\n'.join(parts)

def _parse_at_mentions(text: str) -> list:
    import re as _re3
    pattern = r'@(\w+)\s+([^\n@]+)'
    return [(m.group(1).lower(),m.group(2).strip()) for m in _re3.finditer(pattern,text)]

def _auto_write_files(reply: str) -> int:
    # plan 模式下不自动写文件（权限门控）
    from action.tools import PERMISSION_LEVEL
    if PERMISSION_LEVEL == 'plan':
        return 0
    import re as _re4
    code_start = reply.find('```html')
    if code_start == -1: code_start = reply.find('```')
    if code_start == -1: return 0
    nl = reply.find('\n',code_start)
    code_body = reply[nl+1:] if nl>0 else reply[code_start+3:]
    last_end = code_body.rfind('```')
    content = code_body[:last_end].strip() if last_end>0 else ''
    if not content or len(content)<50: return 0
    prefix = reply[:code_start]
    path_m = _re4.search(r'(?<![A-Za-z])[A-Za-z]:[\\/][^\s<>\"|\n]+\.(?:html|css|js|py|json|txt|md|bat|sh)',prefix)
    if not path_m: return 0
    filepath = path_m.group(0)
    wr = tool_execute('write_file',{'path':filepath,'content':content})
    if wr.ok: logger.info('auto-wrote: %s (%d chars)',filepath,len(content)); return 1
    return 0

def handle_message(text, permission_level='plan'):
    # 设置权限等级（供 tools.py 工具函数门控使用）
    set_permission_level(permission_level)

    is_attack, reason = detect_jailbreak(text)
    if is_attack: return f'🛡️ 检测到{reason}，已拒绝。','zero'

    # ── 特殊指令：换图标 ──
    if text.strip() in ('换图标', '更换图标', '上传图标', '改图标', 'set icon'):
        return ('要更换托盘图标？请上传一张 PNG/JPG 图片到 /api/icon（POST multipart form，字段名 file）。上传后重启零即可生效。', 'zero')

    # Bug 2: 检测图片/文件上传引用，确保 LLM 能看到
    import re as _upload_re
    _upload_images = _upload_re.findall(r'!\[.*?\]\(/api/download/([^)]+)\)', text)
    _upload_files = _upload_re.findall(r'\[用户上传了[^\]]*?：([^\]]+)\]', text)
    if _upload_images or _upload_files:
        _upload_note = '\n\n[系统提示：'
        if _upload_images:
            _upload_note += '用户上传了图片：' + '、'.join(_upload_images)
            _upload_note += '。你无法直接查看图片内容，但可以根据文件名和用户描述来回应。'
        if _upload_files:
            if _upload_images:
                _upload_note += ' 同时上传了文件：' + '、'.join(_upload_files) + '。'
            else:
                _upload_note += '用户上传了文件：' + '、'.join(_upload_files) + '。'
        _upload_note += ']'
        # 只在没有系统提示时才追加，避免重复
        if '[系统提示：' not in text:
            text = text + _upload_note
        logger.debug('检测到上传引用: images=%s files=%s', _upload_images, _upload_files)

    wm.add_message('user',text)
    import re as _re2
    proj_match = _re2.search(r'E:[\\/]project[\\/]([^\\/\s\"\'<>|:*?]+)',text)
    if proj_match: wm.track_project(proj_match.group(1))
    at_mentions = _parse_at_mentions(text)
    if at_mentions:
        reply_parts = []
        agent_name = 'orchestrator'
        for agent_id, task_desc in at_mentions:
            agent = registry._agents.get(agent_id)
            # 1. 用 LLM 理解上下文并生成前置说明
            if registry._agents.get('reasonix', {}).get('executor'):
                try:
                    context_note = call_llm(messages=[
                        {'role': 'system', 'content': f'你正在辅助用户与 Agent @{agent_id} 协作。用户需要对 Agent 说: {task_desc}。请用自然语言补充一句说明用户意图（15字以内），不要提问。'},
                    ], prefer_free=True, task_type='chat', agent_id='reasonix')
                    if context_note and len(str(context_note)) > 3:
                        reply_parts.append(str(context_note).strip())
                except Exception:
                    pass
            # 2. 执行 Agent
            if agent and agent.get('executor'):
                try:
                    output = agent['executor'](task_desc, ['chat'], {})
                    reply_parts.append(str(output))
                except Exception as e:
                    reply_parts.append(f'[{agent_id}] 执行失败: {e}')
            else:
                reply_parts.append(f'[{agent_id}] Agent 不可用')
        reply = '\n\n'.join(reply_parts)
        n = _auto_write_files(reply)
        if n > 0:
            reply += '\n\n✅ 文件已自动保存。'
    else:
        # ── 多轮迭代检测：用户说"再改/不够好/重新"时重新执行 ──
        _iteration_keywords = ['再改', '不够好', '重新', '优化', '改进',
                               '重做', '再来', 'rewrite', 'improve', 'rework']
        _is_iteration = any(kw in text.lower() for kw in _iteration_keywords)

        # 复杂任务走单 Agent 流程链，简单任务走直接聊天
        _complex_keywords = ['做', '建', '搭', '开发', '项目', '全流程', '整个', '完整',
                             '帮我', '写一个', '创建一个', '设计', '分析', '比较']
        _is_complex = (len(text) > 40 and
                      any(kw in text for kw in _complex_keywords))

        if (_is_complex or _is_iteration) and _single_agent:
            logger.debug('走单 Agent 流程链: %s..', text[:40])
            # 多轮迭代：将迭代意图转为"基于反馈重新执行"
            goal_text = text
            if _is_iteration:
                # 从工作记忆中获取最近一次的目标作为上下文
                prev_goal = ''
                if wm and wm.tool_results:
                    # 取第一步的执行摘要作为参考
                    first_key = sorted(wm.tool_results.keys())[:1]
                    if first_key:
                        prev_goal = wm.tool_results[first_key[0]].get('summary', '')[:120]
                goal_text = f'根据反馈重新优化: {text}\n之前执行摘要: {prev_goal}' if prev_goal else f'根据反馈重新优化: {text}'
            result = _single_agent.run(goal_text, wm=wm)
            reply = result.get('answer', '')
            agent_name = 'single_agent'
            for s in result.get('steps', []):
                if s.get('output'):
                    n = _auto_write_files(s['output'])
                    if n and '文件已自动保存' not in reply:
                        reply += '\n\n✅ 文件已自动保存。'
        else:
            # 简单对话：使用三层上下文构建 messages
            ctx_text = _build_agent_context()
            messages = wm.build_context_messages(text, llm_caller=call_llm)
            
            # 如果 messages 是由 build_context_messages 构建的（含 system_anchors），
            # 需要补充 Agent 角色说明
            system_prompt = (f'{ctx_text}\n你是零，主人的智能助手。\n聊天时直接回复。需要执行任务时用 @Agent名 分发：\n'
                           f'  @reasonix 写代码  @agnes_text 聊天  @agnes_image 生图  @tavily 搜索\n'
                           f'给文件路径+代码块会自动保存。用中文。')
            # 将 system prompt 插入到最前面（在 build_context 的 system anchors 之前）
            messages.insert(0, {'role': 'system', 'content': system_prompt})
            
            raw = call_llm(messages=messages, prefer_free=False,
                          task_type='reasoning', task_text=text, agent_id='reasonix')
            reply = raw; agent_name = 'reasonix'
        at_in_reply = _parse_at_mentions(reply)
        if at_in_reply:
            agent_results = []
            for aid, task_desc in at_in_reply:
                ag = registry._agents.get(aid)
                if ag and ag.get('executor'):
                    try:
                        out = ag['executor'](task_desc, ['chat'], {})
                        agent_results.append(f'【@{aid} 执行结果】\n{out}')
                    except Exception as e:
                        agent_results.append(f'【@{aid}】执行失败: {e}')
                else:
                    agent_results.append(f'【@{aid}】Agent 不可用')
            reply = reply + '\n\n' + '\n\n'.join(agent_results)
            agent_name = 'orchestrator'
            n = _auto_write_files(reply)
            if n > 0:
                reply += '\n\n✅ 文件已自动保存。'
        n = _auto_write_files(reply)
        if n>0: reply += '\n\n✅ 文件已自动保存。'
    wm.add_message('assistant',reply); wm.mark_task_done()
    try:
        memory_manager.save_task(task_id=f'msg_{datetime.now().strftime("%Y%m%d_%H%M%S")}',agent='reasonix',task_type='chat',input_summary=text[:100],outcome='success',tokens_used=len(reply))
    except Exception as exc: logger.warning('写记忆失败: %s',exc)
    return reply, agent_name

seed_defaults(registry, llm_caller=call_llm, image_caller=None)

# ── 单 Agent 流程链 ──────────────────────────────────
_single_agent: 'SingleAgentOrchestrator' | None = None
try:
    from action.single_agent import SingleAgentOrchestrator as _SAO
    _single_agent = _SAO(llm_caller=call_llm)
    logger.info('单 Agent 流程链已就绪')
except Exception as exc:
    logger.warning('单 Agent 流程链初始化失败: %s', exc)

# ── 个性化注入 ─────────────────────────────────────
try:
    from personal.seed import load_personal_config, seed_personal
    _personal_cfg = load_personal_config()
    seed_personal(_personal_cfg)
except ImportError:
    pass  # personal/ 不存在（壳子模式）
except Exception as exc:
    logger.warning('个性化注入失败: %s', exc)
reviewer = Reviewer(llm_caller=call_llm)
