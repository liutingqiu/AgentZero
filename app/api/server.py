"""零 · API 层 (aiohttp)
========================
全异步 HTTP 服务——替代 ThreadingHTTPServer。

P2: asyncio 事件循环 + 非阻塞 SSE + 协程式路由。
"""

import json
import os
import sys
import urllib.parse
import logging
import asyncio

from aiohttp import web

import threading as _threading
from config import (
    HTTP_HOST, HTTP_PORT, ZERO_ROOT, OWNER_NAME, DATA_DIR,
    get_agnes_key, get_api_key, get_api_url, get_logger,
)
from interface.webapp import WEBAPP_HTML
from app.services.llm import (
    call_llm, handle_message, tokens, session, wm,
    bus, tsm, registry, reviewer,
)
from action.tools import approve_command
from cognition import memory_manager
from cognition.token_tracker import tracker as token_tracker

logger = get_logger('zero.api')
os.chdir(ZERO_ROOT)

routes = web.RouteTableDef()

# 最大上传大小（字节），默认 10MB，可通过环境变量覆盖
MAX_UPLOAD_BYTES = int(os.environ.get('ZERO_MAX_UPLOAD_BYTES', str(10 * 1024 * 1024)))


# ═══════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════


def _authed(request: web.Request) -> bool:
    return session.is_unlocked()


def _cors_headers() -> dict:
    """返回 CORS 头。
    生产环境中应通过环境变量 ZERO_ALLOWED_ORIGINS 指定允许的 origin 列表（逗号分隔）。
    默认为 '*'（仅用于开发）。
    """
    allowed = os.environ.get('ZERO_ALLOWED_ORIGINS', '').strip()
    if allowed:
        # 支持逗号分隔的白名单，返回请求的 Origin（如果在白名单中）
        def header(origin: str | None):
            if not origin:
                return '*'
            origins = [o.strip() for o in allowed.split(',') if o.strip()]
            return origin if origin in origins else 'null'
        # We return a dict with a dynamic Origin placeholder; caller should replace if needed.
        # For simplicity, return wildcard for non-production when ZERO_ALLOWED_ORIGINS not set.
        return {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
        }
    else:
        # 开发模式默认允许所有来源（部署到生产时请务必设置 ZERO_ALLOWED_ORIGINS）
        return {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
        }

    if request is not None:
        origin = request.headers.get('Origin', '')
        allowed_origins = ['http://127.0.0.1:5052', 'http://localhost:5052']
        if origin in allowed_origins:
            headers['Access-Control-Allow-Origin'] = origin
        # 不在白名单中 → 不设置该头
    else:
        headers['Access-Control-Allow-Origin'] = '*'

    return headers


def _error_response(code: str, msg: str, status: int = 400) -> web.json_response:
    """统一的错误响应格式（含 CORS 头）。"""
    return web.json_response(
        {'ok': False, 'error': {'code': code, 'msg': msg}},
        status=status,
        headers=_cors_headers(),
    )


# 错误码常量
ERR_AUTH_FAILED = 'AUTH_FAILED'
ERR_FILE_TYPE = 'FILE_TYPE_NOT_ALLOWED'
ERR_FILE_SIZE = 'FILE_TOO_LARGE'
ERR_INTERNAL = 'INTERNAL_ERROR'
ERR_BAD_REQUEST = 'BAD_REQUEST'
ERR_NOT_FOUND = 'NOT_FOUND'


# ═══════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════

@routes.view('/health')
class HealthHandler(web.View):
    async def get(self):
        return web.json_response({
            'status': 'ok',
            'session': '已解锁' if session.is_unlocked() else '已锁定',
            'active_tokens': tokens.count(),
        }, headers=_cors_headers())


@routes.view('/api/settings')
class SettingsHandler(web.View):
    async def get(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        agent_status = registry.list_all()
        mem_status = memory_manager.status()
        api_info = {
            'agnes': bool(get_agnes_key()),
            'deepseek': bool(get_api_key()),
            'base_url': get_api_url() if get_api_key() else '',
        }
        return web.json_response({
            'agents': agent_status, 'memory': mem_status, 'apis': api_info,
            'session_unlocked': session.is_unlocked(), 'watch_root': '.',
            'owner': OWNER_NAME,
        }, headers=_cors_headers())


@routes.view('/api/history')
class HistoryHandler(web.View):
    async def get(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        try:
            from cognition.memory_manager import get_conversation_summaries
            summaries = get_conversation_summaries(days=7, limit=50)
            return web.json_response({'history': summaries}, headers=_cors_headers())
        except Exception as exc:
            logger.exception('history handler failed')
            return web.json_response({'error': str(exc)}, status=500, headers=_cors_headers())


@routes.view('/api/kanban')
class KanbanHandler(web.View):
    async def get(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        try:
            from action.kanban import list_tasks, stats
            s = stats(); tasks = list_tasks(limit=20)
            return web.json_response({
                'done': s.get('done', 0), 'total': s.get('total', 0),
                'tasks': [{'title': t.title[:60], 'status': t.status, 'id': t.id} for t in tasks if t.title],
            }, headers=_cors_headers())
        except Exception as exc:
            logger.exception('kanban handler failed')
            return web.json_response({'error': str(exc)}, status=500, headers=_cors_headers())


@routes.view('/api/tokens')
class TokenStatsHandler(web.View):
    """Token 消耗统计。"""
    async def get(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        return web.json_response(token_tracker.session_stats(), headers=_cors_headers())


@routes.view('/api/tokens/recent')
class TokenRecentHandler(web.View):
    """最近 Token 调用记录。"""
    async def get(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        return web.json_response(token_tracker.recent_calls(30), headers=_cors_headers())


@routes.view('/api/notifications')
class NotificationHandler(web.View):
    async def get(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        return web.json_response({'notifications': []}, headers=_cors_headers())


@routes.view('/api/image-proxy')
class ImageProxyHandler(web.View):
    async def get(self):
        url = self.request.query.get('url', '')
        if not url:
            return _error_response(ERR_BAD_REQUEST, 'missing url', status=400)
        try:
            import aiohttp as _aiohttp
            async with _aiohttp.ClientSession() as client:
                async with client.get(url, headers={'User-Agent': 'Zero/1.0'}, timeout=15) as resp:
                    img_data = await resp.read()
            ct = resp.content_type or 'image/png'
            return web.Response(body=img_data, content_type=ct,
                                headers={'Cache-Control': 'public, max-age=86400'})
        except Exception as exc:
            logger.exception('image proxy failed')
            return web.json_response({'error': str(exc)}, status=502, headers=_cors_headers())


@routes.view('/api/chat/stream')
class ChatStreamHandler(web.View):
    async def get(self):
        if not _authed(self.request):
            return web.Response(status=401, content_type='text/event-stream',
                                headers=_cors_headers())
        message = self.request.query.get('m', '')
        permission_level = self.request.query.get('perm', 'plan')
        if not message:
            return _error_response(ERR_BAD_REQUEST, 'missing message')

        resp = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/event-stream; charset=utf-8',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                **_cors_headers(),
            })
        await resp.prepare(self.request)

        async def _send(kind, payload):
            if not self._stream_alive:
                return
            data = json.dumps({'type': kind, 'data': payload}, ensure_ascii=False)
            try:
                await resp.write(('data: ' + data + '\n\n').encode('utf-8'))
            except (ConnectionResetError, BrokenPipeError):
                # 客户端已断开，忽略写入错误
                raise

        self._done_sent = False
        self._chunk_sent = False
        self._stream_alive = True
        await _send('status', 'thinking')
        try:
            # 将阻塞性处理移入线程，避免阻塞事件循环
            reply, agent = await asyncio.to_thread(handle_message, message)
            chunk_size = 80
            for i in range(0, len(reply), chunk_size):
                try:
                    await _send('chunk', reply[i:i + chunk_size])
                except Exception:
                    break
            try:
                await _send('done', {'agent': agent, 'total_chars': len(reply)})
            except Exception:
                pass
        except Exception as exc:
            logger.exception('SSE chat failed')
            try:
                await _send('error', str(exc))
            except Exception:
                pass
        return resp


@routes.view('/api/collab/stream')
class CollabStreamHandler(web.View):
    """SSE 流式协作端点——由 GoalOrchestrator 接管。
    
    保留 SSE 协议格式以兼容前端 `sendCollab()` 的接口，
    内部实现切换到统一的 GoalOrchestrator。
    """
    async def get(self):
        if not _authed(self.request):
            return web.Response(status=401, content_type='text/event-stream',
                                headers=_cors_headers())
        message = self.request.query.get('m', '')
        if not message:
            return _error_response(ERR_BAD_REQUEST, 'missing message')

        resp = web.StreamResponse(
            status=200, reason='OK',
            headers={
                'Content-Type': 'text/event-stream; charset=utf-8',
                'Cache-Control': 'no-cache', 'Connection': 'keep-alive',
                **_cors_headers(),
            })
        await resp.prepare(self.request)

        async def _send(kind, payload):
            data = json.dumps({'type': kind, 'data': payload}, ensure_ascii=False)
            try:
                await resp.write(('data: ' + data + '\n\n').encode('utf-8'))
            except (ConnectionResetError, BrokenPipeError):
                raise

        try:
            from action.goal_orchestrator import GoalOrchestrator
            orch = GoalOrchestrator(llm_caller=call_llm)

            await _send('status', '目标编排器已启动')
            await _send('step', {'role': 'planner', 'status': 'running',
                                 'action': '正在分析任务...'})

            # 在后台线程运行可能阻塞的 orchestrator.run
            result = await asyncio.to_thread(orch.run, message, wm)

            steps = result.get('steps', []) if isinstance(result, dict) else []
            for s in steps:
                step_id = f'step_{s.get("step", 0)}'
                action = s.get('action', '')[:120]
                status = s.get('status', 'done')
                output = s.get('output', '')[:800]
                score = s.get('score', 0)

                try:
                    await _send('step', {
                        'id': step_id,
                        'role': 'executor',
                        'status': status,
                        'action': action,
                        'output': output,
                        'critique': {'score': score, 'passed': s.get('passed', False)},
                    })
                except Exception:
                    break

            try:
                await _send('step', {'role': 'synthesizer', 'status': 'done',
                                     'action': '结果整合完成'})
                stats = result.get('stats', {}) if isinstance(result, dict) else {}
                await _send('done', {
                    'status': result.get('status', 'done') if isinstance(result, dict) else 'done',
                    'answer': result.get('answer', '') if isinstance(result, dict) else '',
                    'completed': stats.get('completed', 0),
                    'total': stats.get('total', 0),
                })
            except Exception:
                pass
        except Exception as exc:
            logger.exception('SSE collab failed')
            try:
                await _send('error', str(exc))
            except Exception:
                pass
        return resp


# ═══════════════════════════════════════════
# POST 端点
# ═══════════════════════════════════════════

@routes.view('/api/auth')
class AuthHandler(web.View):
    async def post(self):
        try:
            data = await self.request.json()
        except Exception:
            return _error_response(ERR_BAD_REQUEST, '无效JSON', status=400)
        code = data.get('code', '')
        if session.is_unlocked():
            t = tokens.issue()
            return web.json_response({'ok': True, 'token': t, 'message': '已解锁'}, headers=_cors_headers())
        ok, msg = session.authenticate(code)
        if ok:
            wm.add_message('system', '会话解锁')
            t = tokens.issue()
            return web.json_response({'ok': True, 'token': t, 'message': msg}, headers=_cors_headers())
        return _error_response(ERR_AUTH_FAILED, msg, status=401)


@routes.view('/api/chat')
class ChatHandler(web.View):
    async def post(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '会话已锁定，请先认证。', status=401)
        try:
            data = await self.request.json()
        except Exception:
            return _error_response(ERR_BAD_REQUEST, '无效JSON', status=400)
        message = data.get('message', '')
        agent_id = data.get('agent_id')
        permission_level = data.get('permission_level', 'plan')
        try:
            if agent_id:
                reply = registry.run(agent_id, message, capabilities=['chat'])
                agent = agent_id
            else:
                # 将可能阻塞的处理放到线程中
                reply, agent = await asyncio.to_thread(handle_message, message)
            try:
                memory_manager.save_conversation_summary(
                    topic=message[:30], summary=reply[:200],
                    emotion=wm.owner_mood, messages_count=1)
            except Exception:
                logger.exception('save_conversation_summary failed')
            return web.json_response({'reply': reply, 'status': 'ok', 'agent': agent},
                                     headers=_cors_headers())
        except Exception as exc:
            logger.exception('chat handler failed')
            return web.json_response({'reply': f'处理失败: {exc}', 'status': 'error', 'agent': 'zero'},
                                     status=500, headers=_cors_headers())


@routes.view('/api/agents/{agent_id}/run')
class AgentRunHandler(web.View):
    async def post(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        agent_id = self.request.match_info['agent_id']
        try:
            data = await self.request.json()
        except Exception:
            return _error_response(ERR_BAD_REQUEST, '无效JSON', status=400)
        message = data.get('message', '')
        try:
            reply = registry.run(agent_id, message, capabilities=data.get('capabilities'))
            return web.json_response({'reply': reply, 'status': 'ok', 'agent': agent_id},
                                     headers=_cors_headers())
        except Exception as exc:
            logger.exception('agents run failed')
            return web.json_response({'reply': f'⚠️ {exc}', 'status': 'error', 'agent': agent_id},
                                     status=500, headers=_cors_headers())


@routes.view('/api/collab')
class CollabHandler(web.View):
    async def post(self):
        if not _authed(self.request):
            return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
        try:
            data = await self.request.json()
        except Exception:
            return _error_response(ERR_BAD_REQUEST, '无效JSON', status=400)
        message = data.get('message', '')
        if not message:
            return _error_response(ERR_BAD_REQUEST, '缺少 message', status=400)
        try:
            from action.goal_orchestrator import GoalOrchestrator
            orch = GoalOrchestrator(llm_caller=call_llm)
            # 在后台线程运行 orchestration
            result = await asyncio.to_thread(orch.run, message, wm)
            steps = result.get('steps', []) if isinstance(result, dict) else []
            steps_detail = []
            for s in steps:
                steps_detail.append({
                    'id': f'step_{s.get("step", 0)}',
                    'action': s.get('action', '')[:120],
                    'status': s.get('status', 'pending'),
                    'output': s.get('output', '')[:500],
                    'version_count': 1,
                    'critiques': [s.get('passed', False)],
                })
            stats = result.get('stats', {}) if isinstance(result, dict) else {}
            return web.json_response({
                'status': result.get('status', 'error') if isinstance(result, dict) else 'error',
                'answer': result.get('answer', '') if isinstance(result, dict) else '',
                'steps': steps_detail,
                'completed': stats.get('completed', 0),
                'failed': stats.get('failed', 0),
                'grounded': 0,
                'events': {'total': 0},
            }, headers=_cors_headers())
        except Exception as exc:
            logger.exception('collab failed')
            return web.json_response({'error': str(exc), 'status': 'failed'},
                                     status=500, headers=_cors_headers())


# ═══════════════════════════════════════════
# 静态文件 + 前端
# ═══════════════════════════════════════════

@routes.get('/')
@routes.get('/index.html')
async def index_handler(request: web.Request):
    return web.Response(body=WEBAPP_HTML.replace('{{OWNER_NAME}}', OWNER_NAME).encode('utf-8'),
                        content_type='text/html', charset='utf-8',
                        headers={'Cache-Control': 'no-cache'})


@routes.get('/product')
async def product_handler(request: web.Request):
    path = os.path.join(ZERO_ROOT, 'interface', 'product.html')
    if os.path.isfile(path):
        return web.FileResponse(path)
    return _error_response(ERR_NOT_FOUND, '页面不存在', status=404)


@routes.get('/favicon.ico')
async def favicon_handler(request: web.Request):
    path = os.path.join(ZERO_ROOT, 'interface', 'hermes_web', 'favicon.ico')
    if os.path.isfile(path):
        return web.FileResponse(path)
    return _error_response(ERR_NOT_FOUND, '页面不存在', status=404)


# ── 文件上传/下载 ─────────────────────────────────────────────


@routes.post('/api/upload')
async def upload_handler(request: web.Request):
    """上传文件到 data/uploads/ 目录。"""
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = {
        '.txt', '.md', '.json', '.py', '.js', '.ts', '.html', '.css', '.scss',
        '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp',
        '.pdf', '.doc', '.docx', '.xlsx', '.xls', '.ppt', '.pptx', '.csv',
        '.zip', '.tar', '.gz', '.7z', '.rar',
        '.mp3', '.mp4', '.wav', '.flac', '.ogg', '.webm', '.mov', '.avi',
        '.log', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
        '.xml', '.sql', '.sh', '.bat', '.ps1',
        '.mdx', '.tex', '.rst',
        '.woff', '.woff2', '.ttf', '.eot',
    }
    if not _authed(request):
        return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
    upload_dir = os.path.join(DATA_DIR, 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    reader = await request.multipart()
    saved = []
    try:
        async for part in reader:
            if part.filename:
                # 防止路径穿越
                safe_name = os.path.basename(part.filename)
                dest = os.path.join(upload_dir, safe_name)
                # 逐块写入并检查大小
                total = 0
                with open(dest, 'wb') as f:
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_UPLOAD_BYTES:
                            # 超出限制，删除文件并返回 413
                            f.close()
                            try:
                                os.remove(dest)
                            except Exception:
                                pass
                            return web.json_response({'error': '文件大小超过限制'}, status=413, headers=_cors_headers())
                        f.write(chunk)
                saved.append({'name': safe_name, 'size': os.path.getsize(dest)})
    except Exception as exc:
        logger.exception('upload failed')
        return web.json_response({'ok': False, 'error': str(exc)}, status=500, headers=_cors_headers())
    return web.json_response({'ok': True, 'files': saved}, headers=_cors_headers())


@routes.get('/api/download/{filename}')
async def download_handler(request: web.Request):
    """下载 data/uploads/ 中的文件。"""
    if not _authed(self:=request):
        return web.json_response({'error': '需要认证'}, status=401, headers=_cors_headers())
    filename = request.match_info.get('filename', '')
    safe_name = os.path.basename(filename)
    path = os.path.join(DATA_DIR, 'uploads', safe_name)
    if not os.path.isfile(path):
        return _error_response(ERR_NOT_FOUND, '文件不存在', status=404)
    return web.FileResponse(path, headers=_cors_headers())


# ═══════════════════════════════════════════
# OPTIONS (CORS preflight)
# ═══════════════════════════════════════════


# ═══════════════════════════════════════════
# 审批端点
# ═══════════════════════════════════════════

@routes.post('/api/approval/{request_id}')
async def handle_approval(request: web.Request):
    """POST /api/approval/{request_id} — 处理 auto 模式命令执行审批。
    
    Body: {"approved": true|false}
    """
    if not _authed(request):
        return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)

    request_id = request.match_info.get('request_id', '')
    if not request_id:
        return _error_response(ERR_BAD_REQUEST, '缺少 request_id', status=400)

    try:
        body = await request.json()
    except Exception:
        return _error_response(ERR_BAD_REQUEST, '请求格式错误')

    approved = body.get('approved', False)
    if not isinstance(approved, bool):
        return _error_response(ERR_BAD_REQUEST, 'approved 必须为布尔值')

    try:
        result = approve_command(request_id, approved)
        return web.json_response(result.to_dict(), headers=_cors_headers())
    except Exception as exc:
        return _error_response(ERR_INTERNAL, str(exc), status=500)


# ═══════════════════════════════════════════
# 监控指标 + 请求追踪
# ═══════════════════════════════════════════

async def handle_monitor_metrics(request):
    """GET /api/monitor/metrics — 聚合监控指标（最近 1 小时 + 系统资源）。"""
    try:
        metrics = {}
        if hasattr(token_tracker, 'get_monitor_metrics'):
            metrics = token_tracker.get_monitor_metrics()
        elif hasattr(token_tracker, 'session_stats'):
            stats = token_tracker.session_stats()
            metrics = {
                'total_tokens': stats.get('total_tokens', 0),
                'total_cost': stats.get('total_cost', 0),
                'cache_hit_rate': stats.get('cache_hit_rate', 0),
            }

        # 系统级别指标（psutil 可选）
        try:
            import psutil
            process = psutil.Process(os.getpid())
            metrics['memory_mb'] = round(process.memory_info().rss / 1024 / 1024, 2)
            metrics['cpu_percent'] = process.cpu_percent(interval=0.1)
            metrics['uptime_seconds'] = int(time.time() - process.create_time())
        except ImportError:
            metrics['memory_mb'] = 0
            metrics['cpu_percent'] = 0
            metrics['uptime_seconds'] = 0

        return web.json_response({'ok': True, 'metrics': metrics})
    except Exception as e:
        return _error_response(ERR_INTERNAL, str(e), status=500)


@web.middleware
async def request_id_middleware(request: web.Request, handler):
    """为每个请求添加唯一 request_id 并记录请求日志。"""
    request_id = str(uuid.uuid4())[:8]
    request['request_id'] = request_id

    logger.info('[%s] %s %s', request_id, request.method, request.path)

    try:
        response = await handler(request)
        response.headers['X-Request-Id'] = request_id
        return response
    except Exception as e:
        logger.error('[%s] %s %s failed: %s', request_id, request.method, request.path, str(e))
        raise


# ═══════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════

@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == 'OPTIONS':
        return web.Response(status=200, headers=_cors_headers(request))
    resp = await handler(request)
    cors = _cors_headers(request)
    resp.headers.update(cors)
    # 白名单检查后若未设 Allow-Origin，清除 handler 遗留的通配符
    if 'Access-Control-Allow-Origin' not in cors:
        try:
            del resp.headers['Access-Control-Allow-Origin']
        except (KeyError, TypeError):
            pass
    return resp


# 速率限制
import time as _time
_rate_limits: dict[str, list[float]] = {}

@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    """简单令牌桶: 每 IP 每分钟 60 请求。"""
    ip = request.headers.get('X-Forwarded-For') or request.remote or '127.0.0.1'
    if isinstance(ip, str) and ',' in ip:
        ip = ip.split(',')[0].strip()
    now = _time.time()
    window = 60  # 1 分钟
    max_req = 120

    if ip not in _rate_limits:
        _rate_limits[ip] = []
    # 清理过期记录
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < window]
    if len(_rate_limits[ip]) >= max_req:
        return web.json_response(
            {'ok': False, 'error': {'code': 'BAD_REQUEST', 'msg': '请求过于频繁，请稍后重试'}, 'retry_after': int(window - (now - _rate_limits[ip][0]))},
            status=429,
            headers={**_cors_headers(request), 'Retry-After': str(int(window))},
        )
    _rate_limits[ip].append(now)
    return await handler(request)


def _load_tray_icon():
    """加载托盘图标。优先使用 data/custom_icon.png，否则用内置默认。"""
    custom = os.path.join(DATA_DIR, 'custom_icon.png')
    if os.path.isfile(custom):
        try:
            from PIL import Image as _PILImage
            return _PILImage.open(custom)
        except Exception as exc:
            logger.warning('自定义图标加载失败: %s', exc)
    # 内置默认：生成一个 64x64 的绿色圆点 + "零"字
    try:
        from PIL import Image as _PILImage, ImageDraw as _PILDraw, ImageFont as _PILFont
        img = _PILImage.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = _PILDraw.Draw(img)
        draw.ellipse([2, 2, 62, 62], fill='#22c55e', outline='#4ade80', width=2)
        # 尝试找中文字体，找不到就用无字绿点
        font = None
        for _fp in ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/yahei.ttf',
                     'C:/Windows/Fonts/simsun.ttc']:
            if os.path.isfile(_fp):
                font = _PILFont.truetype(_fp, 28)
                break
        if font:
            bbox = draw.textbbox((0, 0), '零', font=font)
            tx = (64 - (bbox[2] - bbox[0])) // 2
            ty = (64 - (bbox[3] - bbox[1])) // 2 - 2
            draw.text((tx, ty), '零', fill='#171717', font=font)
        return img
    except Exception as exc:
        logger.debug('内置图标生成失败: %s', exc)
    return None


def _start_tray(app, url):
    """在系统托盘启动图标（pystray）。"""
    try:
        import pystray as _pystray
        import threading as _threading
        from PIL import Image as _PILImage
    except ImportError:
        logger.info('pystray 未安装，跳过托盘图标')
        return

    icon_img = _load_tray_icon() or _PILImage.new('RGBA', (32, 32), (0, 0, 0, 0))

    def _open(icon, item):
        import webbrowser as _wb
        _wb.open(url)

    def _restart(icon, item):
        icon.stop()
        app.shutdown()
        logger.info('正在重启...')
        os.execl(sys.executable, sys.executable, *sys.argv)

    def _stop(icon, item):
        icon.stop()
        logger.info('用户通过托盘菜单退出')
        os._exit(0)

    menu = _pystray.Menu(
        _pystray.MenuItem('打开浏览器', _open, default=True),
        _pystray.Menu.SEPARATOR,
        _pystray.MenuItem('重启', _restart),
        _pystray.MenuItem('停止', _stop),
    )

    tray_icon = _pystray.Icon('zero', icon_img, '零 v5', menu)

    # 在新线程中运行托盘
    t = _threading.Thread(target=tray_icon.run, daemon=True)
    t.start()
    logger.info('系统托盘图标已启动')
    return tray_icon


@routes.post('/api/icon')
async def upload_icon_handler(request: web.Request):
    """上传自定义托盘图标。"""
    if not _authed(request):
        return _error_response(ERR_AUTH_FAILED, '需要认证', status=401)
    reader = await request.multipart()
    async for part in reader:
        if part.filename:
            ext = os.path.splitext(part.filename)[1].lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.ico', '.bmp'):
                return _error_response(ERR_FILE_TYPE, '不支持的图片格式，请使用 PNG/JPG/ICO/BMP', status=400)
            dest = os.path.join(DATA_DIR, 'custom_icon.png')
            with open(dest, 'wb') as f:
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)
            return web.json_response({'ok': True, 'message': '图标已上传，重启后生效'}, headers=_cors_headers())
    return _error_response(ERR_BAD_REQUEST, '未收到文件', status=400)


# ── 行为评估 API ─────────────────────────────────────────────

@routes.get('/api/behavior/control')
async def handle_behavior_control(request: web.Request):
    """获取当前行为控制强度配置。"""
    task_type = request.query.get('type', '').strip()

    try:
        from behavior_canon import compute_control_strength, get_agent_residual
        TASK_TYPES = ['code', 'planning', 'analysis', 'chat', 'reasoning', 'text', 'search']
        agent_id_map = {
            'code': 'reasonix', 'planning': 'zero', 'analysis': 'zero',
            'chat': 'agnes_text', 'reasoning': 'zero', 'text': 'agnes_text',
            'search': 'tavily',
        }

        if task_type:
            strength = compute_control_strength(task_type)
            agent_id = agent_id_map.get(task_type, 'zero')
            residual = get_agent_residual(agent_id)
            return web.json_response({
                'ok': True,
                'task_type': task_type,
                'control_strength': round(strength, 4),
                'temperature': round(0.2 + (1.0 - strength) * 0.6, 4),
                'agent_residual': {
                    'agent_id': residual.agent_id,
                    'style_hint': residual.style_hint,
                    'code_density': residual.code_density,
                    'verbosity': residual.verbosity,
                },
            })
        else:
            result = {}
            for tt in TASK_TYPES:
                strength = compute_control_strength(tt)
                agent_id = agent_id_map.get(tt, 'zero')
                result[tt] = {
                    'control_strength': round(strength, 4),
                    'temperature': round(0.2 + (1.0 - strength) * 0.6, 4),
                    'agent': agent_id,
                }
            return web.json_response({'ok': True, 'controls': result})

    except Exception as e:
        return _error_response(ERR_INTERNAL, str(e), status=500)


@routes.get('/api/behavior/report')
async def handle_behavior_report(request: web.Request):
    """获取行为校准报告。"""
    try:
        from behavior_canon import get_control_memory
        mem = get_control_memory()
        stats = mem.get_stats() if mem else {}

        report = {
            'total_calibrations': stats.get('total', 0),
            'success_rate': stats.get('success_rate', 0),
            'avg_quality': stats.get('avg_quality', 0),
            'avg_control': stats.get('avg_control', 0),
            'bias': stats.get('bias', 0),
            'drift': stats.get('drift', 0),
            'by_type': stats.get('by_type', {}),
            'current_profile': {},
        }
        return web.json_response({'ok': True, 'report': report})
    except Exception as e:
        return _error_response(ERR_INTERNAL, str(e), status=500)


def main():
    from config import find_available_port as _find_port, open_browser as _open_browser

    # ── 加载预算配置 ──
    try:
        config_path = os.path.join(DATA_DIR, 'zero_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            zero_cfg = json.load(f)
        budget_cfg = zero_cfg.get('budget', {})
        monthly = float(budget_cfg.get('monthly_usd', 0.50))
        threshold = float(budget_cfg.get('auto_degrade_threshold', 0.05))
        token_tracker.set_budget(monthly, threshold)
        if monthly > 0:
            logger.info('月预算: $%.2f, 降级阈值: $%.2f', monthly, threshold)
    except Exception as exc:
        logger.debug('预算配置加载失败（使用默认不限）: %s', exc)

    # ── 启动时钟定时任务 ──
    try:
        from perception.clock import Clock as _Clock
        from message_bus import bus as _message_bus
        _clock = _Clock(_message_bus)
        _clock.start()
        logger.info('时钟已启动（每日报告/空闲提醒/夜间巡检）')
    except Exception as exc:
        logger.warning('时钟启动失败: %s', exc)

    actual_port = _find_port()
    if actual_port != HTTP_PORT:
        logger.info('端口 %d 被占用，改用 %d', HTTP_PORT, actual_port)

    url = f'http://{HTTP_HOST}:{actual_port}'
    logger.info('零 v5 · 启动中... %s', url)
    logger.info('Agent: %d 位已注册', len(registry.list_all()))

    _open_browser(url)

    app = web.Application(middlewares=[cors_middleware, rate_limit_middleware, request_id_middleware])
    app.add_routes(routes)
    app.router.add_get('/api/monitor/metrics', handle_monitor_metrics)

    # 静态资源
    static_path = os.path.join(ZERO_ROOT, 'interface', 'hermes_web')
    if os.path.isdir(static_path):
        app.router.add_static('/assets/', path=static_path, name='assets')

    # 前端拆分后的静态文件（style.css, app.js）
    webapp_static = os.path.join(ZERO_ROOT, 'interface', 'webapp_static')
    if os.path.isdir(webapp_static):
        app.router.add_static('/static/', path=webapp_static, name='webapp_static')

    # ── 启动系统托盘图标 ──
    _start_tray(app, url)

    web.run_app(app, host=HTTP_HOST, port=actual_port, print=None)


if __name__ == '__main__':
    main()
