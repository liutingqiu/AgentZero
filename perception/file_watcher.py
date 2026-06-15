"""零 · 文件监听
================
轮询 E:\project 下的文件变更，发布事件到 MessageBus。

动态间隔: 有活动时 10s，无活动时 30s。
"""

import os, time, threading
from datetime import datetime


class FileWatcher:
    """监听 E:\project 下文件变更。
    
    不是实时 hook——30 秒轮询一次，检查文件修改时间。
    """
    
    def __init__(self, bus, watch_root=r'E:\project'):
        self.bus = bus
        self.watch_root = watch_root
        self._running = False
        self._thread = None
        self._last_state = {}       # {path: mtime}
        self._active_interval = 10  # 有活动时 10s
        self._idle_interval = 30    # 无活动时 30s
        self._skip_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 
                          'dist', 'build', '.reasonix', 'gpt_logs', 'agent_logs'}
        self._last_activity_count = 0
    
    def start(self):
        if self._running:
            return True
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # 先扫描一次建立基线（不产生事件）
        self._scan(baseline=True)
        return True
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        return True
    
    def status(self):
        return {
            'running': self._running,
            'root': self.watch_root,
            'tracked_files': len(self._last_state),
            'last_activity': self._last_activity_count,
        }
    
    # ── 内部 ──
    
    def _loop(self):
        """主循环：动态间隔轮询"""
        while self._running:
            changed = self._scan()
            interval = self._active_interval if changed > 0 else self._idle_interval
            time.sleep(interval)
    
    def _scan(self, baseline=False):
        """扫描文件变更，返回变更数量"""
        current = {}
        changed = 0
        
        try:
            for root, dirs, files in os.walk(self.watch_root):
                dirs[:] = [d for d in dirs if d not in self._skip_dirs]
                for f in files:
                    path = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(path)
                        current[path] = mtime
                    except OSError:
                        continue
        except PermissionError:
            pass
        
        if baseline:
            self._last_state = current
            return 0
        
        # 对比变更
        for path, mtime in current.items():
            old_mtime = self._last_state.get(path, 0)
            if mtime > old_mtime:
                changed += 1
                # 提取项目名
                rel = os.path.relpath(path, self.watch_root)
                project = rel.split(os.sep)[0] if os.sep in rel else 'root'
                
                self.bus.publish({
                    'type': 'file_modified',
                    'source': 'file_watcher',
                    'data': {
                        'path': path,
                        'relative': rel,
                        'project': project,
                        'mtime': datetime.fromtimestamp(mtime).isoformat()
                    },
                    'priority': 'normal'
                })
        
        # 检测新增文件
        for path in current:
            if path not in self._last_state:
                changed += 1
                self.bus.publish({
                    'type': 'file_created',
                    'source': 'file_watcher',
                    'data': {'path': path},
                    'priority': 'low'
                })
        
        self._last_activity_count = changed
        self._last_state = current
        return changed
