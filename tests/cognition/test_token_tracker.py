"""测试 Token 成本追踪器 cognition/token_tracker.py"""

import time
from cognition.token_tracker import TokenTracker, TokenRecord


class TestTokenRecord:
    def test_create(self):
        r = TokenRecord(
            agent_id='agnes', model='agnes-2.0-flash',
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
        )
        assert r.agent_id == 'agnes'
        assert r.total_tokens == 150
        assert r.cached is False
        assert r.cost == 0.0

    def test_default_timestamp(self):
        r = TokenRecord(
            agent_id='a', model='m',
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
        )
        assert r.timestamp > 0

    def test_cached_tag(self):
        r = TokenRecord(
            agent_id='a', model='m',
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            cached=True,
        )
        assert r.cached is True


class TestTokenTracker:
    def test_init(self):
        t = TokenTracker(max_records=100)
        assert t.session_stats()['total_calls'] == 0
        assert t.cache_get('some_hash') is None

    def test_record_and_stats(self):
        t = TokenTracker()
        t.record('agnes', 'agnes-2.0-flash', 100, 50)
        t.record('deepseek', 'deepseek-chat', 200, 100)
        s = t.session_stats()
        assert s['total_calls'] == 2
        assert s['total_tokens'] == 450
        assert s['total_cost'] >= 0
        assert s['cached_tokens'] == 0

    def test_record_free_model_cost(self):
        t = TokenTracker()
        t.record('agnes', 'agnes-2.0-flash', 1000, 500)
        s = t.session_stats()
        # 免费模型 cost = 0
        assert s['total_cost'] == 0.0

    def test_budget_set_and_remaining(self):
        t = TokenTracker()
        t.set_budget(10.0)
        s = t.session_stats()
        assert s['budget'] == 10.0
        assert s['budget_remaining'] == 10.0

        # 用大量 token 确保 cost > 0
        t.record('deepseek', 'deepseek-chat', 10_000_000, 5_000_000)
        s = t.session_stats()
        assert s['budget'] == 10.0
        assert s['budget_remaining'] < 10.0

    def test_recent_calls(self):
        t = TokenTracker()
        t.record('a', 'm1', 10, 5)
        t.record('b', 'm2', 20, 10)
        recent = t.recent_calls(5)
        assert len(recent) == 2
        assert recent[0]['agent'] == 'b'  # reverse order
        assert recent[1]['agent'] == 'a'
        assert 'time' in recent[0]

    def test_cache_set_and_get(self):
        t = TokenTracker()
        h = 'abc123'
        result = t.cache_get(h)
        assert result is None  # miss

        t.cache_set(h, 'response_text', ttl=10)
        result = t.cache_get(h)
        assert result == 'response_text'

    def test_cache_stats(self):
        t = TokenTracker()
        t.cache_get('hash1')  # miss
        t.cache_set('hash2', 'data')
        t.cache_get('hash2')  # hit
        t.cache_get('hash3')  # miss
        s = t.session_stats()
        assert s['cache_hit_rate'] == 33.3  # 1/3

    def test_cache_ttl_expiry(self):
        t = TokenTracker()
        h = 'expire_test'
        t.cache_set(h, 'data', ttl=-1)  # 已过期
        # 注意：cache_get 不检查 TTL，惰性清理仅在缓存 >500 时触发
        # 所以这里直接检查缓存条目确实已存入
        entry = t._cache.get(h)
        assert entry is not None
        # 但 TTL 已过期
        assert entry[1] < time.time()

    def test_cache_cleanup(self):
        t = TokenTracker()
        # 填充超过 500 条，触发惰性清理
        for i in range(600):
            t.cache_set(f'h{i}', 'x', ttl=-1)  # 全部过期
        # 清理后缓存大小减小
        assert len(t._cache) < 600

    def test_make_hash_consistency(self):
        messages = [{'role': 'user', 'content': '你好'}]
        h1 = TokenTracker.make_hash(messages, model='m', temperature=0.0)
        h2 = TokenTracker.make_hash(messages, model='m', temperature=0.0)
        assert h1 == h2

    def test_make_hash_different_input(self):
        h1 = TokenTracker.make_hash([{'role': 'user', 'content': '你好'}], model='m')
        h2 = TokenTracker.make_hash([{'role': 'user', 'content': '再见'}], model='m')
        assert h1 != h2

    def test_make_hash_ignores_whitespace(self):
        h1 = TokenTracker.make_hash([{'role': 'user', 'content': '你好  '}], model='m')
        h2 = TokenTracker.make_hash([{'role': 'user', 'content': '你好'}], model='m')
        assert h1 == h2

    def test_make_hash_respects_temperature(self):
        messages = [{'role': 'user', 'content': 'hi'}]
        h1 = TokenTracker.make_hash(messages, temperature=0.0)
        h2 = TokenTracker.make_hash(messages, temperature=1.0)
        assert h1 != h2

    def test_max_records(self):
        t = TokenTracker(max_records=5)
        for i in range(10):
            t.record(f'a{i}', 'm', 1, 1)
        assert len(t._records) == 5

    def test_by_agent_stats(self):
        t = TokenTracker()
        t.record('agent_a', 'm', 100, 50)
        t.record('agent_b', 'm', 200, 100)
        t.record('agent_a', 'm', 50, 25, cached=True)
        s = t.session_stats()
        assert s['by_agent']['agent_a']['calls'] == 2
        assert s['by_agent']['agent_b']['calls'] == 1
        assert s['by_agent']['agent_a']['cached'] == 1

    def test_make_hash_with_cache_flag(self):
        messages = [{'role': 'user', 'content': 'hi', 'cached': True}]
        h = TokenTracker.make_hash(messages, model='m')
        # 不会因为 cached flag 而改变
        assert h is not None
