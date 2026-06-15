"""零 · 系统监控
================
磁盘空间、进程存活、网络状态、电池电量。

从 agent-system/bridge/sysmon.py 重写。
"""

import os, time, threading, subprocess


class SysMon:
    """系统健康监控。每 5 分钟检查一次。"""
    
    def __init__(self, bus):
        self.bus = bus
        self._running = False
        self._thread = None
        self._disk_warned = False
    
    def start(self):
        if self._running:
            return True
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True
    
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        return True
    
    def status(self):
        return {
            'running': self._running,
            'disk_free_gb': self._disk_free(),
            'knowledge_sys': self._check_knowledge_sys(),
            'network': self._check_network(),
        }
    
    # ── 内部 ──
    
    def _loop(self):
        while self._running:
            self._check_disk()
            time.sleep(300)  # 5 分钟
    
    def _disk_free(self):
        """E 盘剩余空间 (GB)"""
        try:
            import shutil
            return round(shutil.disk_usage('E:').free / (1024**3), 1)
        except:
            return -1
    
    def _check_disk(self):
        free = self._disk_free()
        if free < 0:
            return
        
        if free < 10 and not self._disk_warned:
            self._disk_warned = True
            self.bus.publish({
                'type': 'system_alert',
                'source': 'sysmon',
                'data': {'subtype': 'disk_low', 'free_gb': free},
                'priority': 'high'
            })
        elif free > 20:
            self._disk_warned = False
    
    def _check_knowledge_sys(self):
        """检查 KnowledgeSys 是否在运行"""
        try:
            r = subprocess.run(
                ['powershell', '-Command',
                 'Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | Where-Object {$_.CommandLine -like \'*watchdog.py*\'} | Select-Object -First 1'],
                capture_output=True, timeout=10)
            return len(r.stdout.strip()) > 0
        except:
            return False
    
    def _check_network(self):
        """检查外网连通性"""
        try:
            import urllib.request
            urllib.request.urlopen('https://www.baidu.com', timeout=5)
            return True
        except:
            return False
