r"""零 · 主服务器
================
HTTP :5052。串联全部模块。

修复要点：
  - P0-A1: call_llm —— 候选链 + 显式异常，不再裸 `except: pass`
  - P0-A4: HTTP —— 服务端签发 token，其他接口校验
  - P1-A2: keyring —— 改为惰性 getter（通过 config.py 引入）
  - P2-A10: prompt 截断统一工具
  - P2-HTTP: HTTPServer → ThreadingHTTPServer，避免长请求阻塞其他请求
  - P3-log: 统一 logging.getLogger 替代 print
"""

import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── 路径 & 日志 & 密钥（统一交给 config.py） ──
from config import (
    AGNES_API_URL,
    DATA_DIR,
    HTTP_HOST,
    HTTP_PORT,
    MEMORY_DB,
    UNLOCK_DURATION_SECONDS,
    ZERO_ROOT,
    get_agnes_key,
    get_api_key,
    get_api_url,
    get_logger,
)
from utils.json_helpers import extract_first_json
from utils.text_helpers import truncate

os.chdir(ZERO_ROOT)
logger = get_logger('zero.server')

# ── 业务模块（zero 目录已经在 sys.path 最前） ──
from message_bus import TaskStateMachine, get_bus  # noqa: E402
from security.guard import SessionManager, detect_jailbreak  # noqa: E402
from cognition import memory_manager  # noqa: E402
from cognition.working_memory import WorkingMemory  # noqa: E402
from action.agent_loop import AgentLoop  # noqa: E402
from action.agent_registry import AgentRegistry, seed_defaults  # noqa: E402
from action.reviewer import Reviewer  # noqa: E402
from action.task_orchestrator import TaskOrchestrator  # noqa: E402
from action.tools import execute as tool_execute  # noqa: E402
from interface.webapp import WEBAPP_HTML  # noqa: E402


# ── 模型配置 ──────────────────────────────────────────────────────────
AGNES_MODELS = {
    'text_fast': 'agnes-1.5-flash',
    'text': 'agnes-2.0-flash',
    'image': 'agnes-image-2.1-flash',
    'image_old': 'agnes-image-2.0-flash',
    'video': 'agnes-video-v2.0',
}


def _select_agnes_model(task_type='text'):
    """按任务类型挑合适的 Agnes 模型。"""
    if task_type in ('image', 'image_generation'):
        return AGNES_MODELS['image']
    if task_type in ('video', 'video_generation'):
        return AGNES_MODELS['video']
    return AGNES_MODELS['text']


def _post_json(url, payload_dict, api_key, timeout=30):
    """统一的 JSON HTTP POST。返回解析后的 dict；失败抛异常。"""
    payload = json.dumps(payload_dict, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def call_llm(system=None, prompt=None, *, messages=None,
             prefer_free=True, task_type='text', timeout=30,
             task_text='', extra_rules='', agent_id='',
             skip_ground=False):
    """LLM 调用：Agnes → DeepSeek。支持两种调用模式。

    结构化模式（推荐，保留 role 结构）:
        call_llm(messages=[{'role':'system','content':'...'},
                           {'role':'user','content':'...'}, ...])

    旧式兼容（自动构造 system+user）:
        call_llm(system='...', prompt='...')

    Args:
        messages: 结构化消息列表（优先）。为 None 时走 system/prompt 兼容路径。
        system: [兼容] system prompt，仅当 messages=None 时生效。
        prompt: [兼容] user prompt，仅当 messages=None 时生效。
        prefer_free: 是否优先 Agnes（免费 API）
        task_type: 'text' | 'image' | ...，决定模型名
        timeout: 单次 HTTP 超时（秒）。默认 30s。
    """
    # ── 构建消息列表 ──
    if messages is not None:
        # 结构化模式：保留 role 结构（截断在 Gateway 之后统一做）
        msgs = list(messages)
    else:
        # 旧式兼容：system + user 双消息
        msgs = [
            {'role': 'system', 'content': system or ''},
            {'role': 'user', 'content': prompt or ''},
        ]

    # ── Semantic Gateway: L1硬阻断 → L2标准化 → L3软约束 ──
    from semantic_gateway import process as gateway_process  # noqa: WPS433
    try:
        msgs = gateway_process(msgs)
    except Exception as exc:
        logger.error('Gateway 拒绝消息: %s', exc)
        return f'[语义协议违规] {exc}'

    # ── Behavior Canonicalizer v2: 控制强度 → 温度策略 → schema模式 → 路径选择 ──
    from behavior_canon import (canonicalize as canon_behavior,  # noqa: WPS433
                                validate_output, retry_feedback, Path)
    ctx = canon_behavior(
        msgs, task_text=task_text, task_type=task_type,
        agent_id=agent_id, extra_rules=extra_rules,
    )
    msgs = ctx.messages
    # 温度采样：探索路径偏好高温端
    prefer_explore = (ctx.path == Path.EXPLORATORY)
    temperature = ctx.temp_policy.sample(ctx.control_strength, prefer_explore)
    logger.debug('behavior: type=%s ctrl=%.2f temp=%.2f schema=%s path=%s',
                 ctx.task_type, ctx.control_strength, temperature,
                 ctx.schema_mode.value, ctx.path.value)

    # ── 截断保护（逐条） ──
    safe_msgs = []
    for m in msgs:
        role = m.get('role', 'user')
        content = str(m.get('content', ''))
        max_len = 2000 if role == 'system' else 4000
        safe_msgs.append({'role': role, 'content': truncate(content, max_len)})
    msgs = safe_msgs

    # 候选模型链（按优先级顺序尝试）
    candidates = []
    agnes_key = get_agnes_key()
    if prefer_free and agnes_key:
        candidates.append({
            'name': 'agnes',
            'url': AGNES_API_URL,
            'key': agnes_key,
            'model': _select_agnes_model(task_type),
        })

    deepseek_key = get_api_key()
    deepseek_url = get_api_url()
    if deepseek_key:
        candidates.append({
            'name': 'deepseek',
            'url': deepseek_url,
            'key': deepseek_key,
            'model': 'deepseek-chat',
        })

    if not candidates:
        return '[模型不可用：请配置 AGNES_API_KEY 或 LLM_API_KEY 环境变量]'

    # ── 重试上限：strict 模式最多 2 次，soft/free 不重试 ──
    from behavior_canon import SchemaMode  # noqa: WPS433
    max_retries = 2 if ctx.schema_mode == SchemaMode.STRICT else 0

    for c in candidates:
        retries = 0
        while retries <= max_retries:
            try:
                data = _post_json(
                    c['url'],
                    {
                        'model': c['model'],
                        'messages': msgs,
                        'max_tokens': 2000,
                        'temperature': temperature,
                    },
                    c['key'],
                    timeout=timeout,
                )
                content = data['choices'][0]['message']['content']
                if not content:
                    logger.warning('[%s] 返回空内容，尝试下一个候选', c['name'])
                    break

                # ── 输出校验（v2: 按 schema_mode 决定行为）──
                passed, issues = validate_output(
                    content, ctx.control_strength, ctx.task_type,
                    mode=ctx.schema_mode,
                )
                if passed or retries >= max_retries:
                    if not passed:
                        logger.debug('输出校验未通过(重试耗尽): %s', issues)
                    # ── Phase 4.2: 记录控制决策结果 ──
                    from behavior_canon import record_outcome  # noqa: WPS433
                    quality = 0.7 if passed else 0.3
                    record_outcome(
                        task_type=ctx.task_type,
                        agent_id=ctx.agent_id,
                        control_raw=ctx.control_raw,
                        control_final=ctx.control_strength,
                        success=passed,
                        output_quality=quality,
                    )
                    # ── Phase 7: 合成锚定（skip_ground 时跳过，防递归）──
                    if not skip_ground:
                        from behavior_canon import auto_ground_v3  # noqa: WPS433
                        auto_ground_v3(content, ctx.task_type, ctx.agent_id,
                                       ctx.control_strength, llm_caller=call_llm)
                    return content

                # ── 不合规 → Anti-Collapse 重试反馈 ──
                retries += 1
                logger.debug('[%s] 输出不合规(第%d次重试): %s',
                             c['name'], retries, issues)
                feedback = retry_feedback(issues, retries)
                msgs.append({'role': 'user', 'content': feedback})

            except Exception as exc:  # noqa: BLE001
                logger.warning('[%s] 调用失败: %s', c['name'], exc)
                break

    return '[所有模型不可用，请稍后重试]'


# ── Token 注册表（服务端签发，线程安全） ────────────────────────
class TokenStore:
    """极简 bearer-token：服务端生成 → 客户端回传 → 服务端校验。"""

    def __init__(self, ttl_seconds: int):
        self._tokens: dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def issue(self) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = time.time() + self._ttl
            # 顺手清理已过期 token
            now = time.time()
            expired = [t for t, exp in self._tokens.items() if exp < now]
            for t in expired:
                del self._tokens[t]
        return token

    def validate(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            exp = self._tokens.get(token)
            if exp and exp > time.time():
                return True
            if exp:
                del self._tokens[token]
        return False

    def count(self) -> int:
        with self._lock:
            return len(self._tokens)


# ── 初始化中控台（延迟到 main，避免前向引用） ──────────────────
bus = get_bus()
session = SessionManager()
wm = WorkingMemory()
tokens = TokenStore(ttl_seconds=UNLOCK_DURATION_SECONDS)

tsm = TaskStateMachine(bus)
registry = AgentRegistry()
reviewer = None  # 延迟初始化
orch = None  # 延迟初始化


# ── 消息处理 ──────────────────────────────────────────────────────────
# v5.1: 最小干涉壳子。壳子只做三件事：安全、路由、记忆。
# Agent 自己决定怎么回复、是否调工具、是否生图。


def _build_agent_context() -> str:
    """构建注入 Agent 的上下文——纯事实，无人格指令。"""
    now = datetime.now()
    weekday_cn = ['一', '二', '三', '四', '五', '六', '日'][now.weekday()]
    hour = now.hour
    period = ('凌晨' if hour < 6 else '早上' if hour < 9
              else '上午' if hour < 12 else '下午' if hour < 18 else '晚上')
    parts = [
        f'当前时间: {now.month}/{now.day} 周{weekday_cn} {period}',
    ]
    # 活跃项目
    if wm.active_project:
        parts.append(f'活跃项目: {wm.active_project}')
    # 今日状态
    today = memory_manager.get_today_state()
    if today:
        parts.append(f'今日: {today.get("messages_count", 0)}消息 '
                     f'{today.get("tasks_completed", 0)}任务')
    # 最近话题
    summaries = memory_manager.get_conversation_summaries(days=3, limit=3)
    if summaries:
        parts.append('最近话题: ' + '; '.join(s['topic'][:30] for s in summaries))
    return '\n'.join(parts)


def _parse_at_mentions(text: str) -> list[tuple[str, str]]:
    """从文本中提取 @Agent名 及其后的任务描述。

    格式: @Agent名 任务描述（到下一个 @ 或文本结束）
    返回: [(agent_id, task_description), ...]
    """
    import re as _re3
    # 匹配 @agent_id 后跟任务描述（到下一个 @ 或行尾）
    pattern = r'@(\w+)\s+([^\n@]+)'
    return [(m.group(1).lower(), m.group(2).strip())
            for m in _re3.finditer(pattern, text)]


def _auto_write_files(reply: str) -> int:
    """从回复中检测代码块 + 文件路径，自动写入。返回写入的文件数。

    只在同时满足时触发：1)有代码块 2)代码块前后有明确的文件路径
    避免把闲聊中提到的路径误判为写入意图。
    """
    import re as _re4
    # 找代码块
    code_start = reply.find('```html')
    if code_start == -1:
        code_start = reply.find('```')
    if code_start == -1:
        return 0  # 没有代码块 → 不写文件
    nl = reply.find('\n', code_start)
    code_body = reply[nl + 1:] if nl > 0 else reply[code_start + 3:]
    last_end = code_body.rfind('```')
    content = code_body[:last_end].strip() if last_end > 0 else ''
    if not content or len(content) < 50:
        return 0  # 代码块内容太短 → 不写文件
    # 在代码块前的文字中找路径
    prefix = reply[:code_start]
    path_m = _re4.search(
        r'(?<![A-Za-z])[A-Za-z]:[\\/][^\s<>"|\n]+\.(?:html|css|js|py|json|txt|md|bat|sh)',
        prefix)
    if not path_m:
        return 0  # 没有路径 → 不写文件
    filepath = path_m.group(0)
    wr = tool_execute('write_file', {'path': filepath, 'content': content})
    if wr.ok:
        logger.info('auto-wrote: %s (%d chars)', filepath, len(content))
        return 1
    return 0


def handle_message(text):
    """v6 壳子：安全 → 记忆 → @检测 → 聊天或路由 → 自动写文件 → 收尾。

    零不写 JSON 协议。模型自由聊天。壳子静默执行。
    """
    # ── 1. 越狱检测 ──
    is_attack, reason = detect_jailbreak(text)
    if is_attack:
        return f'🛡️ 检测到{reason}，已拒绝。', 'zero'

    # ── 2. 写工作记忆 ──
    wm.add_message('user', text)
    import re as _re2
    proj_match = _re2.search(r'E:[\\/]project[\\/]([^\\/\s"\'<>|:*?]+)', text)
    if proj_match:
        wm.track_project(proj_match.group(1))

    # ── 3. 检测 @Agent 指令 ──
    at_mentions = _parse_at_mentions(text)
    if at_mentions:
        # 有 @ → 分发给对应 Agent
        results = []
        for agent_id, task_desc in at_mentions:
            agent = registry._agents.get(agent_id)
            if agent and agent.get('executor'):
                try:
                    output = agent['executor'](task_desc, ['chat'], {})
                    results.append(output)  # 完整输出
                except Exception as e:
                    results.append(f'[{agent_id}] ❌ {e}')
            else:
                results.append(f'[{agent_id}] ❌ Agent 不可用')
        reply = '\n\n'.join(results)
        agent_name = 'orchestrator'
        n = _auto_write_files(reply)
        if n > 0:
            reply += '\n\n✅ 文件已自动保存。'
    else:
        # ── 纯聊天：模型自由回复 ──
        ctx = _build_agent_context()
        history = wm.get_conversation_history(limit=12)
        messages = [
            {'role': 'system', 'content': (
                f'{ctx}\n'
                f'你是零，主人的智能助手。\n'
                f'聊天时直接回复。需要执行任务时用 @Agent名 分发：\n'
                f'  @reasonix 写代码  @agnes_text 聊天  @agnes_image 生图  @tavily 搜索\n'
                f'给文件路径+代码块会自动保存。用中文。'
            )},
            *history,
            {'role': 'user', 'content': text},
        ]
        # 结构化传递：role 已在源头标准化，Gateway L2 兜底映射
        raw = call_llm(messages=messages,
                       prefer_free=False, task_type='reasoning',
                       task_text=text, agent_id='reasonix')
        reply = raw
        agent_name = 'reasonix'

        # ── 检测零回复中的 @Agent → 触发链式分发 ──
        at_in_reply = _parse_at_mentions(reply)
        if at_in_reply:
            results = []
            for aid, task_desc in at_in_reply:
                ag = registry._agents.get(aid)
                if ag and ag.get('executor'):
                    try:
                        out = ag['executor'](task_desc, ['chat'], {})
                        results.append(out)  # 完整输出
                    except Exception as e:
                        results.append(f'[{aid}] ❌ {e}')
                else:
                    results.append(f'[{aid}] ❌ 不可用')
            reply = '\n\n'.join(results)
            agent_name = 'orchestrator'
            n = _auto_write_files(reply)
            if n > 0:
                reply += '\n\n✅ 文件已自动保存。'

        # ── 静默：检测代码+路径 → 自动写文件 ──
        n = _auto_write_files(reply)
        if n > 0:
            reply += '\n\n✅ 文件已自动保存。'

    # ── 4. 收尾 ──
    wm.add_message('assistant', reply)  # 标准 role（曾为 'zero'）
    wm.mark_task_done()
    try:
        memory_manager.save_task(
            task_id=f'msg_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            agent='reasonix', task_type='chat',
            input_summary=text[:100], outcome='success', tokens_used=len(reply),
        )
    except Exception as exc:
        logger.warning('写记忆失败: %s', exc)

    return reply, agent_name



# ── 完成剩余模块级初始化（在 _handle_image_gen 等函数定义后） ──
seed_defaults(registry, llm_caller=call_llm, image_caller=None)
reviewer = Reviewer(llm_caller=call_llm)
orch = TaskOrchestrator(tsm, registry, llm_caller=call_llm, reviewer=reviewer)


# ── HTTP 服务 ──────────────────────────────────────────────────────────
def _extract_auth_token(headers, body_data):
    """从 Authorization header / query / body 中取 token。"""
    auth = headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[len('Bearer '):].strip()
    # 兼容旧前端直接塞在 body 里
    return (body_data or {}).get('token', '').strip()


class ZeroHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器。token 机制：
    /api/auth 成功后会签发 token；其他所有写接口都必须带 token。
    """

    def log_message(self, format, *args):  # noqa: A002
        return  # 安静模式

    # ── 辅助 ────────────────────────────────────────────────────
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers',
                         'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, rel_path, content_type):
        full = os.path.join(ZERO_ROOT, 'interface', rel_path)
        if os.path.isfile(full):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.end_headers()
            with open(full, 'rb') as fh:
                self.wfile.write(fh.read())
        else:
            self.send_error(404)

    def _needs_auth(self) -> bool:
        return self.path in ('/api/chat', '/api/history',
                              '/api/kanban', '/api/notifications')

    # ── HTTP 方法 ──────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods',
                         'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers',
                         'Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        # 标准化路径（去除 query string 和尾部 /）
        path = self.path.split('?')[0].rstrip('/') or '/'

        if path == '/health':
            self._json({
                'status': 'ok',
                'session': '已解锁' if session.is_unlocked() else '已锁定',
                'active_tokens': tokens.count(),
            })
            return

        # ===== 升级：Settings API（前端用）=====
        if path == '/api/settings':
            if not self._authed():
                self._json({'error': '需要认证'}, 401)
                return
            # 返回系统状态：Agent 列表、记忆统计、模型 API 状态
            agent_status = registry.list_all()
            mem_status = memory_manager.status()
            # 检测各 API 连通性（轻量——只看 key 是否配置）
            api_info = {
                'agnes': bool(get_agnes_key()),
                'deepseek': bool(get_api_key()),
                'base_url': get_api_url() if get_api_key() else '',
            }
            self._json({
                'agents': agent_status,
                'memory': mem_status,
                'apis': api_info,
                'session_unlocked': session.is_unlocked(),
                'watch_root': 'E:\\project',
            })
            return

        # ===== 升级：SSE 流式聊天端点 =====
        if path == '/api/chat/stream':
            if not self._authed():
                self.send_response(401)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.end_headers()
                body = json.dumps({'type': 'error', 'data': '需要认证'},
                                  ensure_ascii=False)
                self.wfile.write(('data: ' + body + '\n\n').encode('utf-8'))
                return

            # 从 query string 读消息
            message = ''
            q = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(q)
            if 'm' in params:
                message = urllib.parse.unquote(params['m'][0])

            # 如果 GET 没传消息，返回 400
            if not message:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'missing message'},
                                            ensure_ascii=False).encode('utf-8'))
                return

            # SSE 头
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            def _send(kind, payload):
                data = json.dumps({'type': kind, 'data': payload},
                                  ensure_ascii=False)
                try:
                    self.wfile.write(('data: ' + data + '\n\n').encode('utf-8'))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # 客户端断开连接 — 正常，静默停止
                    pass
                except Exception:
                    logger.warning('SSE _send 异常（非网络断开）', exc_info=True)

            # 告知已接收
            _send('status', 'thinking')

            try:
                # 调用主处理
                reply, agent = handle_message(message)

                # 模拟流式输出（按"字符块"）
                # 真实 SSE 需要模型流式返回，这里先按 80 字符一块输出
                chunk_size = 80
                for i in range(0, len(reply), chunk_size):
                    chunk = reply[i:i + chunk_size]
                    _send('chunk', chunk)

                _send('done', {'agent': agent, 'total_chars': len(reply)})
            except Exception as exc:  # noqa: BLE001
                logger.warning('SSE 聊天失败: %s', exc)
                _send('error', str(exc))
            finally:
                # 关闭 SSE 连接，让前端 reader.read() 收到 done: true
                self.close_connection = True
            return

        if path.startswith('/assets'):
            ct = 'text/css' if self.path.endswith('.css') else (
                'application/javascript' if self.path.endswith('.js')
                else 'image/svg+xml' if self.path.endswith('.svg')
                else 'application/octet-stream'
            )
            self._serve_file('hermes_web/' + path[len('/assets'):].lstrip('/'), ct)
            return

        if path == '/favicon.ico':
            self._serve_file('hermes_web/favicon.ico', 'image/x-icon')
            return

        if path == '/product':
            self._serve_file('product.html', 'text/html; charset=utf-8')
            return

        if path in ('/', '/index.html'):
            body = WEBAPP_HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            self.wfile.write(body)
            return

        if path in ('/agnes', '/agnes.html'):
            self._serve_file('agnes_chat.html', 'text/html; charset=utf-8')
            return

        # 图片代理：解决跨域下载问题
        if path == '/api/image-proxy':
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            url = params.get('url', [None])[0]
            if not url:
                self._json({'error': 'missing url'}, 400)
                return
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Zero/1.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    img_data = resp.read()
                ct = 'image/png' if url.endswith('.png') else (
                    'image/jpeg' if url.endswith(('.jpg', '.jpeg')) else
                    'image/webp' if url.endswith('.webp') else
                    'image/gif' if url.endswith('.gif') else
                    'image/png'
                )
                self.send_response(200)
                self.send_header('Content-Type', ct)
                self.send_header('Content-Length', str(len(img_data)))
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(img_data)
            except Exception as exc:
                logger.warning('image proxy failed: %s', exc)
                self._json({'error': str(exc)}, 502)
            return

        # 需要鉴权的读接口
        if path == '/api/history':
            if not self._authed():
                self._json({'error': '需要认证'}, 401)
                return
            try:
                from cognition.memory_manager import get_conversation_summaries
                summaries = get_conversation_summaries(days=7, limit=50)
                self._json({'history': summaries})
            except Exception as exc:  # noqa: BLE001
                logger.warning('get history: %s', exc)
                self._json({'error': str(exc)}, 500)
            return

        if path == '/api/kanban':
            if not self._authed():
                self._json({'error': '需要认证'}, 401)
                return
            try:
                from action.kanban import list_tasks, stats
                s = stats()
                tasks = list_tasks(limit=20)
                self._json({
                    'done': s['done'],
                    'total': s['total'],
                    'tasks': [
                        {'title': t.title[:60], 'status': t.status, 'id': t.id}
                        for t in tasks if t.title
                    ],
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning('get kanban: %s', exc)
                self._json({'error': str(exc)}, 500)
            return

        if path == '/api/notifications':
            if not self._authed():
                self._json({'error': '需要认证'}, 401)
                return
            self._json({'notifications': []})
            return

        # ===== SSE 流式协作 =====
        if path == '/api/collab/stream':
            if not self._authed():
                self.send_response(401)
                self.end_headers()
                return
            message = ''
            q = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(q)
            if 'm' in params:
                message = urllib.parse.unquote(params['m'][0])
            if not message:
                self.send_response(400)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            def _send(kind, payload):
                data = json.dumps({'type': kind, 'data': payload}, ensure_ascii=False)
                try:
                    self.wfile.write(('data: ' + data + '\n\n').encode('utf-8'))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def _send(kind, payload):
                data = json.dumps({'type': kind, 'data': payload}, ensure_ascii=False)
                try:
                    self.wfile.write(('data: ' + data + '\n\n').encode('utf-8'))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            try:
                from multi_agent import collaborate_v8
                from behavior_canon import synthetic_evaluate
                import traceback

                _send('status', '启动协作引擎')
                # 协作模式优先速度——跳过慢速免费API，60s超时
                _fast = lambda **kw: call_llm(prefer_free=False, timeout=60, **kw)

                # 1. Planner
                _send('step', {'role': 'planner', 'status': 'running', 'action': '正在分析任务...'})
                try:
                    from multi_agent import PlannerV5, BlackboardV5
                    planner = PlannerV5(_fast)
                    bb = BlackboardV5(message)
                    proposed = planner.propose(bb)
                    step_ids = bb.create_steps(proposed)
                    _send('step', {'role': 'planner', 'status': 'done',
                                   'action': f'拆解为 {len(step_ids)} 个步骤',
                                   'detail': str(proposed)[:500]})
                except Exception as exc:
                    _send('step', {'role': 'planner', 'status': 'failed',
                                   'action': f'规划失败: {exc}'})
                    _send('done', {'status': 'failed', 'answer': f'规划失败: {exc}'})
                    return

                # 2. Execute + Critique
                from multi_agent import ExecutorV5, CriticV5, SynthesizerV5
                executor = ExecutorV5(_fast)
                critic = CriticV5(_fast)
                completed = 0
                for sid in step_ids:
                    step = bb.get_step(sid)
                    if not step:
                        continue
                    info = {'id': sid, 'action': step['action'], 'criteria': step['criteria']}
                    _send('step', {'id': sid, 'role': 'executor', 'status': 'running',
                                   'action': step['action'][:120]})

                    for attempt in range(3):
                        try:
                            bb.start_step(sid, 'executor')
                            output = executor.execute(info, bb)
                            rule_s, _ = synthetic_evaluate(output, 'code')

                            critique = critic.review(output, info)
                            bb.submit_critique(sid, critique, 'critic')
                            critic_s = critique.get('score', 50) / 100.0

                            if critique.get('passed', True):
                                bb.complete_step(sid, output, 'executor')
                                completed += 1
                                _send('step', {
                                    'id': sid, 'role': 'executor', 'status': 'done',
                                    'action': step['action'][:120],
                                    'output': output[:800],
                                    'critique': {'score': critique.get('score'), 'passed': True},
                                })
                                break
                            elif attempt < 2:
                                issues = critique.get('issues', [])
                                suggestions = critique.get('suggestions', [])
                                info['action'] = f'{info["action"]}\n[修正] {"; ".join(issues)}'
                                _send('step', {
                                    'id': sid, 'role': 'critic', 'status': 'running',
                                    'action': f'发现问题: {"; ".join(issues[:2])}',
                                    'detail': f'建议: {"; ".join(suggestions[:2])}',
                                })
                            else:
                                bb.fail_step(sid, 'executor', '审查未通过')
                                _send('step', {'id': sid, 'role': 'executor', 'status': 'failed',
                                               'action': step['action'][:120]})
                        except Exception as exc:
                            _send('step', {'id': sid, 'role': 'executor', 'status': 'failed',
                                           'action': str(exc)[:120]})
                            break

                # 3. Synthesize
                _send('step', {'role': 'synthesizer', 'status': 'running', 'action': '正在整合结果...'})
                synthesizer = SynthesizerV5(_fast)
                answer = synthesizer.synthesize(bb)
                _send('step', {'role': 'synthesizer', 'status': 'done', 'action': '结果整合完成'})
                _send('done', {'status': 'done' if completed == len(step_ids) else 'partial',
                               'answer': answer, 'completed': completed,
                               'total': len(step_ids)})

            except Exception as exc:
                logger.warning('SSE collab failed: %s', exc)
                _send('error', str(exc))
            finally:
                self.close_connection = True
            return

        self._json({'error': 'not found', 'path': path, 'raw': self.path}, 404)

    def _authed(self) -> bool:
        """鉴权：Session 解锁即可，token 为可选项。"""
        return session.is_unlocked()

    def do_POST(self):
        # 标准化路径
        path = self.path.split('?')[0].rstrip('/') or '/'

        length = int(self.headers.get('Content-Length', '0') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'
        try:
            body = raw.decode('utf-8')
            data = json.loads(body) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json({'error': '无效JSON'}, 400)
            return

        if path == '/api/auth':
            code = data.get('code', '')
            if session.is_unlocked():
                t = tokens.issue()
                self._json({'ok': True, 'token': t, 'message': '已解锁'})
                return
            ok, msg = session.authenticate(code)
            if ok:
                wm.add_message('system', '会话解锁')
                t = tokens.issue()
                logger.info('用户认证成功，签发 token')
                self._json({'ok': True, 'token': t, 'message': msg})
            else:
                logger.warning('用户认证失败')
                self._json({'ok': False, 'error': msg}, 401)
            return

        if path == '/api/chat':
            if not self._authed():
                self._json({'reply': '会话已锁定，请先认证。',
                            'status': 'locked'}, 401)
                return

            message = data.get('message', '')
            # 可选：指定 Agent ID
            agent_id = data.get('agent_id')

            try:
                if agent_id:
                    # 用户显式指定 Agent
                    reply = registry.run(agent_id, message,
                                          capabilities=['chat'])
                    agent = agent_id
                else:
                    # 走默认流程（意图分类 → orchestrator）
                    reply, agent = handle_message(message)

                try:
                    memory_manager.save_conversation_summary(
                        topic=message[:30], summary=reply[:200],
                        emotion=wm.owner_mood, messages_count=1,
                    )
                except Exception:  # noqa: BLE001
                    pass

                self._json({'reply': reply, 'status': 'ok', 'agent': agent})
            except Exception as exc:  # noqa: BLE001
                logger.warning('聊天处理失败: %s', exc)
                self._json({'reply': f'处理失败: {exc}',
                            'status': 'error', 'agent': 'zero'}, 500)
            return

        # ===== 升级：指定 Agent 直接执行 =====
        if path.startswith('/api/agents/') and path.endswith('/run'):
            if not self._authed():
                self._json({'error': '需要认证'}, 401)
                return
            # 从 /api/agents/<id>/run 解析 id
            parts = path.split('/')
            agent_id = parts[-2] if len(parts) >= 3 else ''
            message = data.get('message', '')
            try:
                reply = registry.run(agent_id, message,
                                      capabilities=data.get('capabilities'))
                self._json({'reply': reply, 'status': 'ok',
                            'agent': agent_id})
            except Exception as exc:  # noqa: BLE001
                self._json({'reply': f'⚠️ {exc}', 'status': 'error',
                            'agent': agent_id}, 500)
            return

        if path == '/api/collab':
            if not self._authed():
                self._json({'error': '需要认证'}, 401)
                return
            message = data.get('message', '')
            mode = data.get('mode', 'work')
            if not message:
                self._json({'error': '缺少 message'}, 400)
                return
            try:
                from multi_agent import collaborate_v8
                # 尝试加载工具执行器（可选）
                tool_exec = None
                try:
                    from action.tools import execute as _texec
                    tool_exec = lambda out, _e=_texec: _e('shell', {'command': f'python -c \"{out[:200]}\"'}).ok
                except Exception:
                    pass
                result = collaborate_v8(message, call_llm, tool_exec)
                # 提取步骤详情给前端可视化
                bb = result.get('blackboard')
                steps_detail = []
                if bb:
                    for sid in bb._step_order:
                        s = bb._steps.get(sid, {})
                        versions = s.get('versions', [])
                        steps_detail.append({
                            'id': sid,
                            'action': s.get('action', '')[:120],
                            'status': s.get('status', 'pending'),
                            'output': versions[-1]['output'][:500] if versions else '',
                            'version_count': len(versions),
                            'critiques': [
                                c.get('data', {}).get('passed', True)
                                for c in s.get('critiques', [])
                            ] if isinstance(s.get('critiques'), list) else [],
                        })
                self._json({
                    'status': result.get('status', 'error'),
                    'answer': result.get('answer', ''),
                    'mode': mode,
                    'steps': steps_detail,
                    'completed': result.get('completed', 0),
                    'failed': result.get('failed', 0),
                    'grounded': result.get('grounded', 0),
                    'events': bb.events.stats() if bb else {'total': 0},
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning('collab failed: %s', exc)
                self._json({'error': str(exc), 'status': 'failed'}, 500)
            return

        self._json({'error': '未知端点', 'path': path}, 404)


def main():
    logger.info('零 v5 · 启动中... http://%s:%s', HTTP_HOST, HTTP_PORT)
    logger.info('模块: MessageBus + Security + Cognition + Action + Perception')
    logger.info('Agent: %d 位已注册，流式聊天已启用', len(registry.list_all()))

    # ThreadingHTTPServer —— 每个请求一个线程，避免长调用阻塞健康检查
    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), ZeroHandler)
    server.daemon_threads = True

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('收到 Ctrl+C，正在关闭...')
        wm.flush(memory_manager)
        server.shutdown()
        logger.info('零已关闭')


if __name__ == '__main__':
    main()
