"""零 · 时钟感知
================
时间事件：早上/晚上/空闲检测。

发布事件:
  morning_greeting  — 早上首次交互
  daily_report_time — 每天 08:00
  night_check       — 每天 02:00
  idle_reminder     — 连续 N 小时无交互
"""

import time, threading
from datetime import datetime


class Clock:
    """时间感知 + 定时事件发布。"""
    
    def __init__(self, bus):
        self.bus = bus
        self._running = False
        self._thread = None
        self._last_interaction = time.time()
        self._last_daily_report = None
        self._last_night_check = None
        self._greeted_today = False
        self._last_idle_alert = None
    
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
            'idle_minutes': round((time.time() - self._last_interaction) / 60, 1),
            'greeted_today': self._greeted_today,
        }
    
    def touch(self):
        """记录用户交互时间"""
        self._last_interaction = time.time()
    
    # ── 内部 ──
    
    def _loop(self):
        while self._running:
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            
            # 每日报告 (08:00)
            if now.hour == 8 and self._last_daily_report != today:
                self._last_daily_report = today
                self.bus.publish({
                    'type': 'time_event',
                    'source': 'clock',
                    'data': {'subtype': 'daily_report', 'time': now.isoformat()},
                    'priority': 'normal'
                })
            
            # 夜间巡检 (02:00-04:00)
            if 2 <= now.hour <= 4 and self._last_night_check != today:
                self._last_night_check = today
                self.bus.publish({
                    'type': 'time_event',
                    'source': 'clock',
                    'data': {'subtype': 'night_check', 'time': now.isoformat()},
                    'priority': 'low'
                })
            
            # 空闲检测 (> 4 小时无交互)
            idle_hours = (time.time() - self._last_interaction) / 3600
            if idle_hours > 4 and self._greeted_today and self._last_idle_alert != today:
                self._last_idle_alert = today  # v2: 每天最多提醒一次
                self.bus.publish({
                    'type': 'time_event',
                    'source': 'clock',
                    'data': {'subtype': 'idle_reminder', 'idle_hours': round(idle_hours, 1)},
                    'priority': 'low'
                })
            
            time.sleep(60)  # 每分钟检查一次
    
    def morning_greeting(self):
        """早上首次交互时调用"""
        if not self._greeted_today:
            self._greeted_today = True
            self.bus.publish({
                'type': 'time_event',
                'source': 'clock',
                'data': {'subtype': 'morning_greeting'},
                'priority': 'normal'
            })
