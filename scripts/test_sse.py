import urllib.request
import json
import time

# 绠€鍖栨祴璇曪細鐩存帴璇锋眰 SSE 浣嗚缃煭瓒呮椂锛岀湅鏄惁鏈変换浣曞搷搴?url = 'http://127.0.0.1:5052/api/chat/stream?m=hello'
req = urllib.request.Request(url)
start = time.time()

try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print(f'Status: {r.status}')
        print(f'Content-Type: {r.headers.get("Content-Type")}')
        count = 0
        while True:
            line = r.readline()
            if not line: break
            text = line.decode('utf-8', errors='replace').strip()
            if text.startswith('data:'):
                count += 1
                if count <= 3:
                    print(f'  [{count}] {text[:200]}')
        print(f'Total events: {count}')
    print(f'Time: {time.time() - start:.1f}s')
except urllib.error.HTTPError as e:
    print(f'HTTP {e.code}: {e.read().decode("utf-8", errors="replace")}')
except Exception as e:
    print(f'ERR: {type(e).__name__}: {e}')
    print(f'Time: {time.time() - start:.1f}s')
