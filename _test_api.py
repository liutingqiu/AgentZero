import urllib.request
import urllib.error
import json
import time

def fetch(path, data=None):
    url = f'http://127.0.0.1:5052{path}'
    try:
        if data:
            req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
        else:
            req = urllib.request.Request(url)
        r = urllib.request.urlopen(req, timeout=30)
        body = r.read().decode('utf-8')
        return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

print('=== 1. /health ===')
code, body = fetch('/health')
print(f'{code}: {body[:200]}')

print('\n=== 2. /api/auth ===')
code, body = fetch('/api/auth', {'code': '柳橙'})
print(f'{code}: {body[:200]}')

print('\n=== 3. /api/settings ===')
code, body = fetch('/api/settings')
print(f'{code}: {body[:300]}')

print('\n=== 4. POST /api/chat ===')
code, body = fetch('/api/chat', {'message': '用一句话解释什么是人工智能'})
print(f'{code}: {body[:400]}')

print('\n=== 5. GET /api/chat/stream (SSE) ===')
url = 'http://127.0.0.1:5052/api/chat/stream?m=' + urllib.parse.quote('用一句话解释什么是快速排序算法')
req = urllib.request.Request(url)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        lines = []
        while True:
            line = r.readline()
            if not line: break
            decoded = line.decode('utf-8').strip()
            if decoded.startswith('data:'):
                lines.append(decoded[5:].strip())
        print(f'{r.status}: received {len(lines)} SSE events')
        for l in lines[:5]:
            print(f'  - {l[:120]}')
        if len(lines) > 5:
            print(f'  ... ({len(lines) - 5} more)')
except Exception as e:
    print(f'ERR: {e}')

print('\n=== ALL TESTS DONE ===')
