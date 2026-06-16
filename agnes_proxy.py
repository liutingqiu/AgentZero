"""Agnes 代理 v2 — Codex Responses API → Agnes Chat Completions.

修复要点：
  - keyring 惰性加载（环境变量优先）
  - 超时从 120s → 30s
  - 日志统一 get_logger，避免 print 乱码
  - 非贪婪 JSON 提取
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import get_agnes_key, get_logger

logger = get_logger('zero.agnes_proxy')

AGNES_URL = 'https://apihub.agnes-ai.com/v1/chat/completions'
PORT = int(os.environ.get('AGNES_PROXY_PORT', '8899'))


class ProxyHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
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
                ],
            })
        else:
            logger.debug('未知 GET 路径: %s', self.path)
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0') or 0)
        raw = self.rfile.read(length) if length > 0 else b'{}'

        try:
            req = json.loads(raw)
            logger.debug('请求 model=%s', req.get('model', '?'))
        except json.JSONDecodeError:
            self._send_json({'error': 'invalid JSON'}, 400)
            return

        try:
            # 从不同格式中提取 messages
            messages = []
            if isinstance(req.get('input'), str):
                messages = [{'role': 'user', 'content': req['input']}]
            elif isinstance(req.get('input'), list):
                for item in req['input']:
                    if isinstance(item, dict):
                        role = item.get('role', 'user')
                        content = item.get('content', str(item))
                        messages.append({'role': role, 'content': content})
            elif 'messages' in req and isinstance(req['messages'], list):
                messages = req['messages']

            if not messages:
                messages = [{'role': 'user', 'content': 'hi'}]

            # 调 Agnes
            key = get_agnes_key()
            if not key:
                self._send_json({
                    'error': 'AGNES_API_KEY 未配置（环境变量或 keyring）'
                }, 500)
                return

            payload = json.dumps({
                'model': 'agnes-2.0-flash',
                'messages': messages,
                'max_tokens': min(int(req.get('max_output_tokens', 2000)), 4000),
                'temperature': float(req.get('temperature', 0.7)),
            }).encode('utf-8')

            import urllib.request
            http_req = urllib.request.Request(
                AGNES_URL, data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {key}',
                },
            )
            with urllib.request.urlopen(http_req, timeout=30) as resp:
                agnes_data = json.loads(resp.read().decode('utf-8'))

            reply = agnes_data['choices'][0]['message']['content']
            logger.info('OK，响应 %d 字符', len(reply))

            # 转回 Responses API 格式
            output = [{
                'type': 'message',
                'role': 'assistant',
                'content': [{'type': 'output_text', 'text': reply}],
            }]
            self._send_json({'output': output, 'model': 'gpt-5.3-codex'})

        except Exception as exc:
            logger.error('请求失败: %s', exc)
            self._send_json({'error': str(exc)}, 500)

    def log_message(self, format, *args):  # noqa: A002
        return  # 静音默认 http.server 日志


def main():
    logger.info('Agnes 代理启动在 :%d', PORT)
    server = ThreadingHTTPServer(('127.0.0.1', PORT), ProxyHandler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('收到 Ctrl+C，关闭')
        server.shutdown()


if __name__ == '__main__':
    main()
