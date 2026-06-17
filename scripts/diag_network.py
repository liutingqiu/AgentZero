import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
_ZERO_ROOT = _HERE.parent
if str(_ZERO_ROOT) not in sys.path:
    sys.path.insert(0, str(_ZERO_ROOT))

import os, socket, urllib.request, json

# 1. 检查 8899 端口是什么
print("=== 检查 localhost:8899 ===")
try:
    req = urllib.request.Request('http://127.0.0.1:8899/v1/models',
        headers={'Authorization': 'Bearer test'})
    r = urllib.request.urlopen(req, timeout=5)
    data = json.loads(r.read())
    print('Models:', json.dumps(data, indent=2, ensure_ascii=False)[:500])
except Exception as e:
    print(f'连接错误: {e}')

# 2. 检查 5052 端口是否在跑（应该就是 zero server）
print("\n=== 检查 localhost:5052 ===")
try:
    r = urllib.request.urlopen('http://127.0.0.1:5052/health', timeout=5)
    print(r.read().decode('utf-8'))
except Exception as e:
    print(f'5052 未运行: {e}')

# 3. 查看所有相关环境变量
print("\n=== 所有 API 相关环境变量 ===")
for k, v in sorted(os.environ.items()):
    if any(x in k.upper() for x in ['API', 'KEY', 'TOKEN', 'URL', 'BASE', 'ENDPOINT', 'MODEL', 'AGNES', 'OPENAI', 'CLAUDE', 'HUGGING', 'SECRET']):
        print(f'{k}: {v}')

# 4. 测试 Agnes API 直接访问
print("\n=== 测试 Agnes API 直接访问 ===")
try:
    from config import AGNES_API_URL, MODEL_NAMES
try:
    req = urllib.request.Request(
        AGNES_API_URL,
        data=json.dumps({
            'model': MODEL_NAMES['agnes_text'],
            'messages': [{'role': 'user', 'content': 'hello'}],
            'max_tokens': 10
        }).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer YOUR_KEY_HERE'}
    )
    r = urllib.request.urlopen(req, timeout=5)
    print(' Agnes API reachable:', r.status)
except urllib.error.HTTPError as e:
    print(f' Agnes API HTTP {e.code}: {e.read().decode("utf-8")[:200]}')
except Exception as e:
    print(f' Agnes API 错误: {type(e).__name__}: {e}')
