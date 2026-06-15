"""Agnes 代理 v2 — Codex Responses API → Agnes Chat Completions
=================================================================
启动: python agnes_proxy.py
Codex 配置: OPENAI_BASE_URL=http://127.0.0.1:8899/v1
"""

import json, urllib.request, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler

AGNES_KEY = os.environ.get('AGNES_API_KEY',
    __import__('keyring').get_password('AGNES', 'KEY') or '')
AGNES_URL = 'https://apihub.agnes-ai.com/v1/chat/completions'
PORT = 8899

class ProxyHandler(BaseHTTPRequestHandler):
    
    def _log(self, msg):
        try:
            print(f'[{self.command}] {self.path} -> {msg}')
        except:
            pass  # 编码问题，忽略日志
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()
    
    def do_GET(self):
        if self.path in ('/', '/health'):
            self._send_json({'status': 'ok', 'service': 'Agnes Proxy'})
        elif '/models' in self.path:
            self._send_json({
                'object': 'list',
                'data': [
                    {'id': 'gpt-5.3-codex', 'object': 'model'},
                    {'id': 'agnes-2.0-flash', 'object': 'model'},
                ]
            })
        else:
            self._log(f'未知GET路径')
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b'{}'
        
        try:
            req = json.loads(body)
            self._log(f'model={req.get("model","?")} keys={list(req.keys())[:3]}')
        except:
            self._log(f'无效JSON')
            self.send_error(400)
            return
        
        try:
            # 提取 messages（兼容多种格式）
            messages = []
            if 'input' in req:
                inp = req['input']
                if isinstance(inp, str):
                    messages = [{'role': 'user', 'content': inp}]
                elif isinstance(inp, list):
                    for item in inp:
                        if isinstance(item, dict):
                            role = item.get('role', 'user')
                            content = item.get('content', str(item))
                            messages.append({'role': role, 'content': content})
            elif 'messages' in req:
                messages = req['messages']
            
            if not messages:
                messages = [{'role': 'user', 'content': 'hi'}]
            
            # 调 Agnes
            payload = json.dumps({
                'model': 'agnes-2.0-flash',
                'messages': messages,
                'max_tokens': min(req.get('max_output_tokens', 2000), 4000),
                'temperature': req.get('temperature', 0.7)
            }).encode()
            
            ag_req = urllib.request.Request(AGNES_URL, data=payload,
                headers={'Content-Type':'application/json',
                         'Authorization': f'Bearer {AGNES_KEY}'})
            ag_resp = json.loads(urllib.request.urlopen(ag_req, timeout=120).read())
            reply = ag_resp['choices'][0]['message']['content']
            
            self._log(f'OK {len(reply)} chars')
            
            # 转回 Responses API 格式
            output = [{
                'type': 'message',
                'role': 'assistant',
                'content': [{'type': 'output_text', 'text': reply}]
            }]
            self._send_json({'output': output, 'model': 'gpt-5.3-codex'})
            
        except Exception as e:
            self._log(f'ERR {str(e)[:100]}')
            self._send_json({'error': str(e)}, 500)
    
    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def log_message(self, *args):
        pass

if __name__ == '__main__':
    print(f'Agnes 代理 v2 :{PORT} (Codex→Agnes)')
    HTTPServer(('127.0.0.1', PORT), ProxyHandler).serve_forever()
