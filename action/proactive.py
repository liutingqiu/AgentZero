"""零 · 主动推送
================
从事件中识别需要主动通知主人的场景。

推送策略:
  - project_idle: 项目 N 天没动 → 关心询问
  - disk_low: 磁盘不足 → 提醒清理
  - process_died: 关键进程挂掉 → 通知
  - github_discover: 新工具发现 → 评估后推送

冷却机制:
  - 同一事件不重复推送
  - 每种类型有最小间隔
  - 连续推送 3 次无回应 → 降级
"""

import time, json, os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 推送记录 ──
_push_history = {}     # {event_key: [timestamp, ...]}
_silenced = set()      # 主人已关闭的事件类型
_consecutive_no_response = {}  # {event_key: count}


def should_push(event_type, event_key, priority='normal'):
    """判断是否应该推送。
    
    Args:
        event_type: 'project_idle', 'disk_low', 'process_died', 'github_discover'
        event_key: 唯一标识（如项目名）
        priority: critical/high/normal/low
    
    Returns:
        bool: 是否应该推送
    """
    # 已静默的 → 不推
    if event_key in _silenced:
        return False
    
    # 冷却检查
    now = time.time()
    cooldowns = {
        'critical': 60,      # 1 分钟
        'high': 1800,        # 30 分钟
        'normal': 3600,      # 1 小时
        'low': 14400,        # 4 小时
    }
    cooldown = cooldowns.get(priority, 3600)
    
    history = _push_history.get(event_key, [])
    if history:
        last_push = history[-1]
        if now - last_push < cooldown:
            return False
    
    # 连续无回应 → 降级
    no_resp = _consecutive_no_response.get(event_key, 0)
    if no_resp >= 3:
        _silenced.add(event_key)
        return False
    
    # 记录
    if event_key not in _push_history:
        _push_history[event_key] = []
    _push_history[event_key].append(now)
    
    # 清理旧记录
    _push_history[event_key] = [t for t in _push_history[event_key] if now - t < 86400]
    
    return True


def mark_responded(event_key):
    """主人回应了推送 → 重置计数"""
    _consecutive_no_response[event_key] = 0


def mark_ignored(event_key):
    """主人忽略了推送"""
    _consecutive_no_response[event_key] = _consecutive_no_response.get(event_key, 0) + 1


def silence(event_key):
    """主人主动关闭某类通知"""
    _silenced.add(event_key)


def unsilence(event_key):
    """恢复某类通知"""
    _silenced.discard(event_key)


# ── 消息生成 ──

def generate_message(event_type, data):
    """根据事件类型生成推送消息"""
    messages = {
        'project_idle': lambda d: f'主人，{d.get("project","项目")} {d.get("days","")}天没动了，要继续吗~',
        'disk_low': lambda d: f'⚠️ E盘仅剩 {d.get("free_gb","?")}GB，建议清理一下',
        'process_died': lambda d: f'⚠️ {d.get("process","进程")} 挂了，已尝试重启',
        'github_discover': lambda d: f'🔍 发现新工具: {d.get("title","")}',
        'daily_report': lambda d: f'📊 今日报告已生成',
    }
    
    fn = messages.get(event_type)
    if fn:
        return fn(data)
    return str(data)
