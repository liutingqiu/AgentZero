"""临时验证脚本：逐个文件 py_compile 检测语法"""
import py_compile
import sys

files = [
    'config.py',
    'zero_server.py',
    'message_bus.py',
    'agnes_proxy.py',
    'utils/json_helpers.py',
    'utils/text_helpers.py',
    'action/agent_registry.py',
    'action/agent_loop.py',
    'action/task_orchestrator.py',
    'action/reviewer.py',
    'action/tools.py',
    'action/kanban.py',
    'cognition/memory_manager.py',
    'interface/webapp.py',
    'perception/file_watcher.py',
    'security/guard.py',
]

errors = 0
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f'  OK  {f}')
    except Exception as exc:
        print(f'  FAIL {f}: {exc}')
        errors += 1

print(f'\n=== 结果: {len(files)-errors}/{len(files)} 通过 ===')
sys.exit(0 if errors == 0 else 1)
