import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
_ZERO_ROOT = _HERE.parent
if str(_ZERO_ROOT) not in sys.path:
    sys.path.insert(0, str(_ZERO_ROOT))

import os

# 检查环境变量
for env in ['AGNES_API_KEY', 'LLM_API_KEY', 'AGNES_KEY', 'AGNES_TOKEN']:
    v = os.environ.get(env, '')
    if v:
        print(f'{env}: {v[:20]}...')
    else:
        print(f'{env}: 未设置')

# 检查 keyring
try:
    import keyring
    k = keyring.get_password('AGNES', 'KEY')
    print(f'keyring AGNES/KEY: {k[:20]}...' if k else 'keyring: 无')
except ImportError:
    print('keyring: 未安装')
except Exception as e:
    print(f'keyring 错误: {e}')

# 检查 Windows Credential Manager
try:
    import keyring.backends.Windows
    k = keyring.get_password('AGNES', 'KEY')
    print(f'Windows keyring: {k[:20]}...' if k else '无')
except Exception as e:
    print(f'Windows keyring 错误: {e}')

# 检查 config 中的 fallback
try:
    from config import get_agnes_key, get_api_key
    print(f'\nget_agnes_key(): {repr(get_agnes_key()[:20]) if get_agnes_key() else None}...')
    print(f'get_api_key(): {repr(get_api_key()[:20]) if get_api_key() else None}...')
except Exception as e:
    print(f'config 错误: {e}')
