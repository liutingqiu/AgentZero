"""零 · 文件监听
================
轮询目标目录下的文件变更，发布事件到 MessageBus。

修复要点：
  - os.walk + os.path.getmtime 改为 os.scandir 递归，减少系统调用
  - 限制最大扫描文件数，避免百万级文件项目把内存吃光
  - 日志：统一 get_logger
"""

import os
import threading
import time
from datetime import datetime

from config import get_logger

logger = get_logger('zero.file_watcher')

_MAX_FILES = 200_000  # 最多跟踪文件数（保护机制）


class FileWatcher:
    """监听文件变更，发布到 MessageBus。"""

    def __init__(self, bus, watch_root=r'E:\project'):
        self.bus = bus
        self.watch_root = watch_root
        self._running = False
        self._thread = None
        self._last_state = {}
        self._active_interval = 10
        self._idle_interval = 30
        self._skip_dirs = {
            '.git', 'node_modules', '__pycache__', '.venv',
            'dist', 'build', '.reasonix', 'gpt_logs',
            'agent_logs', 'data',
        }
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
            try:
                self._thread.join(timeout=5)
            except RuntimeError:
                pass
        return True

    def status(self):
        return {
            'running': self._running,
            'root': self.watch_root,
            'tracked_files': len(self._last_state),
            'last_activity': self._last_activity_count,
        }

    # ── 内部循环 ────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            changed = self._scan()
            interval = (self._active_interval if changed > 0
                        else self._idle_interval)
            time.sleep(interval)

    # ── 扫描：os.scandir 递归，减少系统调用 ──────────────────────

    def _collect_mtimes(self, path, current_dict, count_ref):
        """递归扫描一个目录，填充 {path: mtime} dict。"""
        try:
            entries = list(os.scandir(path))
        except PermissionError:
            return
        except PermissionError:
            return  # 无权限访问子目录 — 正常跳过
        except OSError as exc:
            logger.warning('scandir %s failed: %s', path, exc)
            return

        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if name in self._skip_dirs or name.startswith('.'):
                        continue
                    self._collect_mtimes(entry.path, current_dict, count_ref)
                elif entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    current_dict[entry.path] = stat.st_mtime
                    count_ref[0] += 1
                    if count_ref[0] >= _MAX_FILES:
                        return
            except OSError:
                # 某个 entry stat 失败，跳过
                continue

    def _scan(self, baseline=False):
        """扫描所有文件，对比上次状态，发布变更事件。"""
        current: dict = {}
        count_ref = [0]  # 可变对象，用于递归中计数

        try:
            self._collect_mtimes(self.watch_root, current, count_ref)
        except Exception as exc:
            logger.warning('scan failed: %s', exc)
            return 0

        if count_ref[0] >= _MAX_FILES:
            logger.warning('超过最大文件数 %s，已停止跟踪更多文件', _MAX_FILES)

        if baseline:
            self._last_state = current
            logger.info('基线扫描完成，共 %s 个文件', len(current))
            return 0

        # 对比变更
        changed = 0
        for path, mtime in current.items():
            old_mtime = self._last_state.get(path, 0)
            if mtime > old_mtime:
                changed += 1
                rel = os.path.relpath(path, self.watch_root)
                project = rel.split(os.sep, 1)[0] if os.sep in rel else 'root'
                self.bus.publish({
                    'type': 'file_modified',
                    'source': 'file_watcher',
                    'data': {
                        'path': path,
                        'relative': rel,
                        'project': project,
                        'mtime': datetime.fromtimestamp(mtime).isoformat(),
                    },
                    'priority': 'normal',
                })

        # 检测新增文件
        for path in current:
            if path not in self._last_state:
                changed += 1
                self.bus.publish({
                    'type': 'file_created',
                    'source': 'file_watcher',
                    'data': {'path': path},
                    'priority': 'low',
                })

        self._last_activity_count = changed
        self._last_state = current
        return changed
