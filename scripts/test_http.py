import urllib.request
import urllib.error
import json

def test_get(path, token=None):
    url = 'http://127.0.0.1:5052' + path
    req = urllib.request.Request(url)
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        r = urllib.request.urlopen(req)
        return r.code, r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

def test_post(path, body, token=None):
    url = 'http://127.0.0.1:5052' + path
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        r = urllib.request.urlopen(req)
        return r.code, r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')

print('=== 1. Health Check ===')
print(test_get('/health'))

print()
print('=== 2. Auth ===')
code, body = test_post('/api/auth', {'code': '鏌虫'})
print(code, body[:200])
token = json.loads(body).get('token', '')

print()
print('=== 3. Settings (with token) ===')
c, b = test_get('/api/settings', token)
print(c, b[:300])

print()
print('=== 4. Settings (without token) ===')
print(test_get('/api/settings'))

print()
print('=== 5. Chat (POST) ===')
c, b = test_post('/api/chat', {'message': '浣犲ソ锛屼粙缁嶄竴涓嬩綘鑷繁'}, token)
print(c, b[:300])

print()
print('=== 6. Chat (鎸囧畾 Agent) ===')
c, b = test_post('/api/chat', {'message': '鍐欎竴涓?Python 鐨?hello world', 'agent_id': 'reasonix'}, token)
print(c, b[:300])

print()
print('=== 7. SSE Stream Chat ===')
esc = urllib.parse.quote('鐢ㄤ竴鍙ヨ瘽瑙ｉ噴浠€涔堟槸浜哄伐鏅鸿兘')
url = f'http://127.0.0.1:5052/api/chat/stream?m={esc}'
req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        chunks = 0
        while True:
            line = r.readline()
            if not line:
                break
            text = line.decode('utf-8').strip()
            if text.startswith('data:'):
                payload = text[5:].strip()
                if payload:
                    chunks += 1
                    if chunks <= 3:
                        print(f'  chunk {chunks}: {payload[:120]}')
        print(f'  ... 鍏辨敹鍒?{chunks} 涓?SSE 浜嬩欢')
except Exception as e:
    print(f'  閿欒: {e}')

print()
print('=== 8. Kanban (GET) ===')
print(test_get('/api/kanban', token)[:200] if len(test_get('/api/kanban', token)) > 0 else '')

print()
print('=== 娴嬭瘯瀹屾垚 ===')
