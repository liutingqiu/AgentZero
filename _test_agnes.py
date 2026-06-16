import urllib.request, json, time

# 认证
req = urllib.request.Request('http://127.0.0.1:5052/api/auth',
    data=json.dumps({'code': '柳橙'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
r = urllib.request.urlopen(req, timeout=10)
token = json.loads(r.read().decode('utf-8')).get('token', '')
print('Auth OK, token:', token[:20], '...')

# 测试 SSE 流式聊天（30秒超时）
url = 'http://127.0.0.1:5052/api/chat/stream?m=' + urllib.parse.quote('用一句话解释什么是人工智能')
req = urllib.request.Request(url)
print('\nSSE Stream 开始...')
start = time.time()
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f'Status: {r.status}')
        full_text = ''
        count = 0
        while True:
            line = r.readline()
            if not line: break
            text = line.decode('utf-8', errors='replace').strip()
            if text.startswith('data:'):
                count += 1
                try:
                    d = json.loads(text[5:])
                    if d.get('type') == 'chunk':
                        full_text += d.get('data', '')
                        print(f'  [{count}] chunk: {d["data"][:80]}...')
                    elif d.get('type') == 'done':
                        print(f'  [{count}] done: agent={d.get("data", {})}')
                except:
                    pass
        print(f'\n总计 {count} 个事件，耗时 {time.time()-start:.1f}s')
        print(f'回复内容: {full_text[:300]}...' if len(full_text) > 300 else f'回复内容: {full_text}')
except Exception as e:
    print(f'错误: {type(e).__name__}: {e}')
