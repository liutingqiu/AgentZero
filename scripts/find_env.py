import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
_ZERO_ROOT = _HERE.parent
if str(_ZERO_ROOT) not in sys.path:
    sys.path.insert(0, str(_ZERO_ROOT))

import os, winreg

print("=== 当前进程环境变量 ===")
for k, v in sorted(os.environ.items()):
    if any(x in k.upper() for x in ['AGNES', 'LLM', 'API', 'KEY', 'TOKEN', 'SECRET', 'HUGGING', 'OPENAI', 'DEEPSEEK', 'CLAUDE']):
        print(f'{k}: {v[:30]}...' if len(v) > 30 else f'{k}: {v}')

print("\n=== HKCU\Environment ===")
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_READ) as key:
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, i)
                if any(x in name.upper() for x in ['AGNES', 'LLM', 'API', 'KEY', 'TOKEN']):
                    print(f'{name}: {str(value)[:50]}')
                i += 1
            except OSError:
                break
except Exception as e:
    print(f'错误: {e}')

print("\n=== HKCU\Software\Microsoft\Windows\CurrentVersion\pmlib ===")
try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion', 0, winreg.KEY_READ) as key:
        subkeys = []
        try:
            i = 0
            while True:
                subkeys.append(winreg.EnumKey(key, i))
                i += 1
        except OSError:
            pass
        for sk in subkeys:
            if 'env' in sk.lower() or 'key' in sk.lower() or 'api' in sk.lower():
                print(f'  {sk}')
except Exception as e:
    print(f'错误: {e}')
