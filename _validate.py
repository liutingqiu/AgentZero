import ast
import os

files = ['zero_server.py', 'action/agent_registry.py', 'interface/webapp.py', 'config.py']
for f in files:
    try:
        ast.parse(open(f, encoding='utf-8').read())
        print(f'OK: {f}')
    except SyntaxError as e:
        print(f'FAIL: {f} - {e}')
    except Exception as e:
        print(f'ERR: {f} - {e}')

# 测试导入
try:
    import importlib
    for mod in ['zero_server', 'action.agent_registry', 'interface.webapp', 'config']:
        importlib.import_module(mod)
        print(f'IMPORT OK: {mod}')
    print('\\nAll imports successful')
except Exception as e:
    print(f'\\nIMPORT ERR: {e}')
