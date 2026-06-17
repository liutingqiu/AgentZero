import urllib.request, json, time

# 璁よ瘉
req = urllib.request.Request('http://127.0.0.1:5052/api/auth',
    data=json.dumps({'code': '鏌虫'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
r = urllib.request.urlopen(req, timeout=10)
token = json.loads(r.read().decode('utf-8')).get('token', '')
print('Auth OK, token:', token[:20], '...')

# 娴嬭瘯 SSE 娴佸紡鑱婂ぉ锛?0绉掕秴鏃讹級
url = 'http://127.0.0.1:5052/api/chat/stream?m=' + urllib.parse.quote('鐢ㄤ竴鍙ヨ瘽瑙ｉ噴浠€涔堟槸浜哄伐鏅鸿兘')
req = urllib.request.Request(url)
print('\nSSE Stream 寮€濮?..')
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
        print(f'\n鎬昏 {count} 涓簨浠讹紝鑰楁椂 {time.time()-start:.1f}s')
        print(f'鍥炲鍐呭: {full_text[:300]}...' if len(full_text) > 300 else f'鍥炲鍐呭: {full_text}')
except Exception as e:
    print(f'閿欒: {type(e).__name__}: {e}')
