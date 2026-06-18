"""零 · 自我反思
================
每日回顾 + 时段对比 + 经验积累。

从 agent-system/reflect_daily.py 重写。
"""

import os, json
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(BASE, 'data', 'reports')
os.makedirs(REPORT_DIR, exist_ok=True)


def daily_review(memory_manager):
    """每日反思——生成 Markdown 报告。
    
    Args:
        memory_manager: memory_manager 模块
    
    Returns:
        str: 报告文件路径
    """
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    
    # 统计（summary() 返回 total/success/failed/by_agent）
    stats = memory_manager.summary()
    summaries = memory_manager.get_conversation_summaries(days=1, limit=20)
    
    total = stats.get('total', 0)
    success = stats.get('success', 0)
    failed = stats.get('failed', 0)
    rate = round(success / total * 100, 1) if total > 0 else 0
    
    lines = [
        f'# 零 · 每日反思',
        f'> {now.strftime("%Y-%m-%d %H:%M")} 自动生成',
        '',
        '## 概览',
        f'- 总任务: **{total}**',
        f'- 成功: **{success}**',
        f'- 失败: **{failed}**',
        f'- 成功率: **{rate}%**',
        '',
    ]
    
    # 各 Agent 表现
    by_agent = stats.get('by_agent', [])
    if by_agent:
        lines.append('## 各模块表现')
        lines.append('| 模块 | 任务数 |')
        lines.append('|------|:--:|')
        for a in by_agent:
            lines.append(f'| {a.get("agent","?")} | {a.get("c",0)} |')
        lines.append('')
    
    # 对话摘要
    if summaries:
        lines.append('## 今日对话')
        for s in summaries[:5]:
            lines.append(f'- [{s.get("emotion","?")}] {s.get("topic","")}: {s.get("summary","")[:80]}')
        lines.append('')
    
    # 时段对比（新）
    morning_stats = _period_stats(memory_manager, 6, 12)   # 06-12
    afternoon_stats = _period_stats(memory_manager, 12, 18) # 12-18
    if morning_stats['total'] or afternoon_stats['total']:
        lines.append('## 时段对比')
        lines.append(f'- 上午 (06-12): {morning_stats["total"]}任务, 成功率 {morning_stats["rate"]}%')
        lines.append(f'- 下午 (12-18): {afternoon_stats["total"]}任务, 成功率 {afternoon_stats["rate"]}%')
        lines.append('')
    
    lines.append('---')
    lines.append('*零 · 自动生成*')
    
    report = '\n'.join(lines)
    path = os.path.join(REPORT_DIR, f'reflect_{today}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    return path


def _period_stats(memory_manager, start_hour, end_hour):
    """统计特定时段的性能"""
    # 使用 get_recent_tasks 按小时范围过滤
    recent = memory_manager.get_recent_tasks(limit=100)
    filtered = [t for t in (recent or [])
                if t.get('hour', 0) in range(start_hour, end_hour)]
    total = len(filtered)
    success = sum(1 for t in filtered if t.get('outcome') == 'success')
    return {
        'total': total,
        'rate': round(success / total * 100, 1) if total > 0 else 0,
    }


def extract_lessons(memory_manager):
    """从失败任务中提取经验教训"""
    # 使用 get_recent_tasks 获取最近任务，再过滤失败项
    recent = memory_manager.get_recent_tasks(hours=7 * 24, limit=50)
    failures = [t for t in recent if t.get('outcome') != 'success']
    lessons = []
    
    error_categories = {}
    for task in failures:
        # get_recent_tasks 返回 input_summary 而非 error_info
        err = task.get('input_summary', '') + ' ' + task.get('outcome', '')
        # 简单归类
        if '超时' in err or 'timeout' in err.lower():
            cat = '超时'
        elif '连接' in err or 'connect' in err.lower():
            cat = '网络问题'
        elif '编码' in err or 'encode' in err.lower():
            cat = '编码问题'
        elif '不存在' in err or 'not found' in err.lower():
            cat = '资源缺失'
        else:
            cat = '其他'
        
        error_categories[cat] = error_categories.get(cat, 0) + 1
    
    for cat, count in sorted(error_categories.items(), key=lambda x: -x[1]):
        if count >= 2:
            lessons.append(f'{cat}类错误发生{count}次，需要关注')
    
    return lessons


def compress_old_memories(memory_manager, days=30):
    """压缩过期记忆"""
    result = memory_manager.compress(days_keep=days)
    return result
