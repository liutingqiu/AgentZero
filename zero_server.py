r"""零 · 主服务器
================
HTTP :5052。串联全部模块。

E:\project\tools\zero\zero_server.py
"""

import json, os, sys, time, uuid, urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
# 关键：zero 目录必须在 sys.path[0]，覆盖当前 CWD 中的同名模块
if BASE in sys.path:
    sys.path.remove(BASE)
sys.path.insert(0, BASE)
os.chdir(BASE)
# agent-system 路径（用于 secure_config 等，放在 zero 之后）
agent_sys = os.path.join(os.path.dirname(BASE), 'agent-system')
if agent_sys in sys.path:
    sys.path.remove(agent_sys)
sys.path.insert(1, agent_sys)

from message_bus import get_bus
from security.guard import SessionManager, detect_jailbreak
from cognition.working_memory import WorkingMemory
from cognition import memory_manager
from cognition.context import build_context, build_llm_messages
from cognition.intent_engine import classify
from action.tools import execute as tool_execute
from action.agent_loop import AgentLoop
from action.proactive import should_push, generate_message
from interface.webapp import WEBAPP_HTML

# ── 模型 ──
from secure_config import get_api_url, get_api_key
API_URL = get_api_url()
API_KEY = get_api_key()

# Agnes 免费 API（优先级高于 DeepSeek）
AGNES_KEY = __import__('keyring').get_password('AGNES', 'KEY') or ''
AGNES_URL = 'https://apihub.agnes-ai.com/v1/chat/completions'

# Agnes 模型自动选择（v4: 按任务类型匹配）
AGNES_MODELS = {
    'text_fast': 'agnes-1.5-flash',      # 简单聊天（更快）
    'text': 'agnes-2.0-flash',            # 推理/代码（主力）
    'image': 'agnes-image-2.1-flash',     # 图像生成/编辑
    'image_old': 'agnes-image-2.0-flash', # 图像（上一代）
    'video': 'agnes-video-v2.0',          # 视频生成
}

def _select_agnes_model(task_type='text'):
    """文本→2.0 / 图像→2.1 / 视频→2.0，全选最强"""
    if task_type in ('image', 'image_generation'):
        return 'agnes-image-2.1-flash'
    elif task_type in ('video', 'video_generation'):
        return 'agnes-video-v2.0'
    else:
        return 'agnes-2.0-flash'

def call_llm(system, prompt, prefer_free=True, task_type='text'):
    """LLM 调用——v4: Agnes(5模型自动选)→DeepSeek→兜底"""
    if prefer_free and AGNES_KEY:
        model = _select_agnes_model(task_type)
        try:
            payload = json.dumps({
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system[:500]},
                    {'role': 'user', 'content': prompt[:3000]}
                ],
                'max_tokens': 1000 if 'text' in model else 200
            }).encode()
            req = urllib.request.Request(AGNES_URL, data=payload,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {AGNES_KEY}'})
            r = json.loads(urllib.request.urlopen(req, timeout=120).read())
            return r['choices'][0]['message']['content']
        except:
            pass
    
    # 第二优先：DeepSeek（AIHubMix）
    try:
        payload = json.dumps({
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 1000
        }).encode()
        req = urllib.request.Request(API_URL, data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'})
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return r['choices'][0]['message']['content']
    except Exception as e:
        return f'[所有模型不可用: {str(e)[:100]}]'

# ── 初始化 v2 中控台 ──
bus = get_bus()
session = SessionManager()
wm = WorkingMemory()

from message_bus import TaskStateMachine
from action.agent_registry import AgentRegistry, seed_defaults
from action.task_orchestrator import TaskOrchestrator
from action.reviewer import Reviewer

tsm = TaskStateMachine(bus)
registry = AgentRegistry()
seed_defaults(registry)
reviewer = Reviewer(llm_caller=call_llm)
orch = TaskOrchestrator(tsm, registry, llm_caller=call_llm, reviewer=reviewer)

# ── 消息处理 ──

def handle_message(text):
    """v2: 简单聊天走LLM直聊，复杂任务走Orchestrator拆活分活"""
    # 1. 越狱检测
    is_attack, reason = detect_jailbreak(text)
    if is_attack:
        return (f'🛡️ 检测到{reason}，已拒绝。', 'zero')
    
    # 2. 记录工作记忆
    wm.add_message('user', text)
    
    # 3. 生图请求 → 直接调 Agnes Image API
    img_keywords = ['生成', '生图', '画', '图片', '照片', '图像', '绘图', '做一张', '来一张']
    if any(kw in text for kw in img_keywords) and AGNES_KEY:
        try:
            prompt = text
            for kw in img_keywords:
                prompt = prompt.replace(kw, '').strip()
            if not prompt: prompt = text
            
            payload = json.dumps({
                'model': 'agnes-image-2.1-flash',
                'prompt': prompt,
                'n': 1,
                'size': '1024x1024'
            }).encode()
            req = urllib.request.Request('https://apihub.agnes-ai.com/v1/images/generations',
                data=payload,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {AGNES_KEY}'})
            r = json.loads(urllib.request.urlopen(req, timeout=120).read())
            img_url = r['data'][0].get('url', '')
            if img_url:
                wm.add_message('zero', f'[生图: {img_url}]')
                wm.mark_task_done()
                return (f'🖼️ 已生成:\n{img_url}', 'agnes')
            return ('生图失败: 未获取到图片URL', 'zero')
        except Exception as e:
            return (f'生图异常: {str(e)[:200]}', 'zero')
    
    # 4. 意图分类
    intent, confidence = classify(text, wm.get_context(), call_llm)
    
    # 简单任务（写代码/查资料/聊天）→ 直接 LLM，不拆
    is_simple = intent == 'passive_chat' or len(text) < 50
    
    if is_simple:
        # 聊天模式 → Agnes 1.5 Flash（更快）
        context = build_context(wm, memory_manager)
        system = f'你是零，服务于柳橙（主人）。{context}\n简洁回复，用中文。'
        reply = call_llm(system, text, task_type='chat')
    else:
        # Action 模式 → v2 Orchestrator（拆活→分Agent→Reviewer验证）
        result = orch.execute(text, max_subtasks=3)  # 最多3步，避免过度拆解
        done = result.get('completed', 0)
        failed = result.get('failed', 0)
        
        if result['status'] == 'done':
            # 汇总所有子任务结果
            parts = ['✅ 完成 (' + str(done) + '/' + str(result.get('subtasks', '?')) + '个子任务)']
            for r in result.get('results', []):
                agent_name = r.get('agent', '?')
                task_result = str(r.get('result', ''))[:200]
                score = r.get('review_score', '')
                score_str = f' [评分:{score}]' if score else ''
                parts.append(f'\n📌 {agent_name}{score_str}: {task_result}')
            reply = ''.join(parts)
        elif result['status'] == 'partial':
            reply = f'⚠️ 部分完成 ({done}成功/{failed}失败)'
        else:
            reply = f'❌ 任务失败: {result.get("summary", "")}'
    
    # 5. 返回（默认 agent=zero）
    agent = 'zero'
    wm.add_message('zero', reply)
    wm.mark_task_done()
    
    # 6. 写入短期记忆
    memory_manager.save_task(
        task_id=f'msg_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
        agent='zero', task_type=intent,
        input_summary=text[:100], outcome='success',
        tokens_used=len(reply)
    )
    
    return (reply, agent)


# ── HTTP 服务器 ──

class ZeroHandler(BaseHTTPRequestHandler):
    
    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def _serve_file(self, path, content_type):
        full = os.path.join(BASE, 'interface', path)
        if os.path.exists(full):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.end_headers()
            with open(full, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404)
    
    def do_GET(self):
        if self.path == '/health':
            self._json({'status': 'ok', 'session': '已解锁' if session.is_unlocked() else '已锁定'})
        # Hermes React 静态资源
        elif self.path.startswith('/assets/'):
            p = 'hermes_web' + self.path
            ct = 'text/css' if self.path.endswith('.css') else 'application/javascript' if self.path.endswith('.js') else 'image/svg+xml' if self.path.endswith('.svg') else 'application/octet-stream'
            self._serve_file(p, ct)
        elif self.path == '/favicon.ico':
            self._serve_file('hermes_web/favicon.ico', 'image/x-icon')
        elif self.path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(WEBAPP_HTML.encode('utf-8'))
        elif self.path.startswith('/api/kanban'):
            try:
                from action.kanban import stats, list_tasks
                s = stats()
                tasks = list_tasks(limit=20)
                self._json({
                    'done': s['done'], 'total': s['total'],
                    'tasks': [{'title': t.title[:60], 'status': t.status, 'id': t.id} for t in tasks if t.title]
                })
            except Exception as e:
                self._json({'error': str(e)}, 500)
        elif self.path.startswith('/api/notifications'):
            self._json({'notifications': []})
        else:
            self._json({'error': 'not found'}, 404)
    
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length > 0 else '{}'
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json({'error': '无效JSON'}, 400)
            return
        
        # /api/auth
        if self.path == '/api/auth':
            code = data.get('code', '')
            if session.is_unlocked():
                self._json({'ok': True, 'token': 'unlocked', 'message': '已解锁'})
                return
            ok, msg = session.authenticate(code)
            if ok:
                wm.add_message('system', '会话解锁')
                self._json({'ok': True, 'token': str(uuid.uuid4())[:12], 'message': msg})
            else:
                self._json({'ok': False, 'error': msg}, 401)
            return
        
        # /api/chat
        if self.path == '/api/chat':
            if not session.is_unlocked():
                self._json({'reply': '会话已锁定，请先认证。', 'status': 'locked'})
                return
            
            message = data.get('message', '')
            result = handle_message(message)
            if isinstance(result, tuple):
                reply, agent = result
            else:
                reply, agent = result, 'zero'
            self._json({'reply': reply, 'status': 'ok', 'agent': agent})
            return
        
        self._json({'error': '未知端点'}, 404)
    
    def log_message(self, format, *args):
        pass


def main():
    print('零 v4 · 启动中...')
    print(f'http://127.0.0.1:5052')
    print(f'模块: MessageBus + Security + Cognition + Action + Perception')
    
    server = HTTPServer(('127.0.0.1', 5052), ZeroHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n零已关闭')
        wm.flush(memory_manager)
        server.shutdown()

if __name__ == '__main__':
    main()
