"""零 · Token 成本追踪器

每次 LLM 调用时记录 token 消耗，提供实时统计。
支持缓存命中标记，前端实时展示。
"""

import hashlib
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenRecord:
    """一次 LLM 调用的记录。"""
    agent_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached: bool = False
    cost: float = 0.0
    timestamp: float = field(default_factory=time.time)
    task_type: str = ''


class TokenTracker:
    """Token 追踪器。线程安全，支持实时查询。"""

    MODEL_RATES = {
        'deepseek-chat':       {'input': 0.00014, 'output': 0.00028},   # $0.14/$0.28 per 1M
        'deepseek-reasoner':   {'input': 0.00055, 'output': 0.00219},   # $0.55/$2.19 per 1M
        'agnes-2.0-flash':     {'input': 0.0,     'output': 0.0},       # 免费
        'agnes-image-2.1-flash': {'input': 0.0,   'output': 0.0},       # 免费
        'gpt-4o':              {'input': 0.0025,  'output': 0.01},      # $2.50/$10 per 1M
        'gpt-4o-mini':         {'input': 0.00015, 'output': 0.0006},    # $0.15/$0.60 per 1M
    }

    def __init__(self, max_records: int = 1000):
        self._records: deque[TokenRecord] = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._cache = {}  # prompt_hash -> (response, timestamp)
        self._cache_hits = 0
        self._cache_misses = 0
        self._budget = 0.0  # 用户设定的月预算（美元）
        self._degrade_threshold = 0.05  # 剩余低于此值自动降级（美元）

    def set_budget(self, usd: float, degrade_threshold: float = 0.05) -> None:
        """设置月预算和自动降级阈值。
        
        Args:
            usd: 月预算上限（美元），0=不限
            degrade_threshold: 剩余预算低于此值自动切免费模型（美元）
        """
        self._budget = usd
        self._degrade_threshold = degrade_threshold

    def record(self, agent_id: str, model: str,
               prompt_tokens: int, completion_tokens: int,
               cached: bool = False, task_type: str = '') -> TokenRecord:
        """记录一次 LLM 调用。"""
        rate = self.MODEL_RATES.get(model, {'input': 0.001, 'output': 0.002})
        cost = (prompt_tokens * rate['input'] + completion_tokens * rate['output']) / 1_000_000

        rec = TokenRecord(
            agent_id=agent_id, model=model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cached=cached, cost=cost, task_type=task_type,
        )
        with self._lock:
            self._records.append(rec)
        return rec

    def get_monitor_metrics(self) -> dict:
        """获取聚合监控指标（最近 1 小时窗口）。

        从 _records 中计算：调用次数、平均延迟、错误率、
        缓存命中率、token 消耗、费用。适配 TokenRecord 的
        实际字段。
        """
        now = time.time()
        hour_ago = now - 3600

        with self._lock:
            recent = [r for r in self._records if r.timestamp > hour_ago]

        total_calls = len(recent)
        if total_calls == 0:
            return {
                'total_calls': 0,
                'avg_latency_ms': 0,
                'error_rate': 0,
                'cache_hit_rate': 0,
                'total_tokens': 0,
                'total_cost': 0,
                'period_hours': 1,
            }

        cached_count = sum(1 for r in recent if r.cached)
        total_tokens = sum(r.total_tokens for r in recent)
        total_cost = sum(r.cost for r in recent)

        return {
            'total_calls': total_calls,
            'avg_latency_ms': 0,          # TokenRecord 无 latency 字段
            'error_rate': 0,               # TokenRecord 无 is_error 字段
            'cache_hit_rate': round(cached_count / total_calls, 4),
            'total_tokens': total_tokens,
            'total_cost': round(total_cost, 6),
            'period_hours': 1,
        }

    def session_stats(self) -> dict:
        """当前会话的汇总统计。"""
        with self._lock:
            total_tokens = sum(r.total_tokens for r in self._records)
            total_cost = sum(r.cost for r in self._records)
            free_tokens = sum(r.total_tokens for r in self._records if r.cached)
            by_agent = {}
            for r in self._records:
                by_agent.setdefault(r.agent_id, {
                    'calls': 0, 'tokens': 0, 'cost': 0.0, 'cached': 0,
                })
                by_agent[r.agent_id]['calls'] += 1
                by_agent[r.agent_id]['tokens'] += r.total_tokens
                by_agent[r.agent_id]['cost'] += r.cost
                if r.cached:
                    by_agent[r.agent_id]['cached'] += 1

            cache_hits = self._cache_hits
            cache_total = cache_hits + self._cache_misses
            cache_rate = round(cache_hits / cache_total * 100, 1) if cache_total > 0 else 0.0

            return {
                'total_calls': len(self._records),
                'total_tokens': total_tokens,
                'total_cost': round(total_cost, 6),
                'budget': self._budget,
                'budget_remaining': round(self._budget - total_cost, 6),
                'cached_tokens': free_tokens,
                'cache_hit_rate': cache_rate,
                'by_agent': by_agent,
            }

    def recent_calls(self, n: int = 20) -> list[dict]:
        """最近 N 次调用详情。"""
        with self._lock:
            records = list(self._records)[-n:]
        return [
            {
                'agent': r.agent_id,
                'tokens': r.total_tokens,
                'cost': round(r.cost, 6),
                'cached': r.cached,
                'time': time.strftime('%H:%M:%S', time.localtime(r.timestamp)),
            }
            for r in reversed(records)
        ]

    def cache_get(self, prompt_hash: str) -> Optional[str]:
        """检查缓存命中。"""
        entry = self._cache.get(prompt_hash)
        if entry:
            # 检查 TTL 是否过期
            if entry[1] < time.time():
                del self._cache[prompt_hash]
                self._cache_misses += 1
                return None
            self._cache_hits += 1
            return entry[0]
        self._cache_misses += 1
        return None

    def cache_set(self, prompt_hash: str, response: str, ttl: int = 3600) -> None:
        """写入缓存。"""
        self._cache[prompt_hash] = (response, time.time() + ttl)
        # 惰性清理过期缓存
        if len(self._cache) > 500:
            now = time.time()
            self._cache = {k: v for k, v in self._cache.items() if v[1] > now}

    @staticmethod
    def make_hash(messages: list[dict], model: str = '',
                  temperature: float = 0.0) -> str:
        """从消息列表和参数生成缓存 key。

        忽略 'cached' flags 和纯 whitespace 变化。
        """
        h = hashlib.sha256()
        for m in messages:
            role = m.get('role', '')
            content = str(m.get('content', '')).strip()
            h.update(f'{role}|{content}\0'.encode())
        h.update(f't={temperature:.2f}'.encode())
        h.update(f'm={model}'.encode())
        return h.hexdigest()


# 全局实例
tracker = TokenTracker()
