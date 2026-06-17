"""测试 Agent 注册表 action/agent_registry.py"""

from action.agent_registry import AgentRegistry, ProficiencyTracker


class TestProficiencyTracker:
    def test_init(self):
        pt = ProficiencyTracker()
        assert pt.to_dict() == {}

    def test_set_static(self):
        pt = ProficiencyTracker()
        pt.set_static('agent_a', {'code': 0.8, 'chat': 0.6})
        w = pt.get_weight('agent_a', 'code')
        assert w == 0.8
        w2 = pt.get_weight('agent_a', 'chat')
        assert w2 == 0.6

    def test_record_and_weight_change(self):
        pt = ProficiencyTracker()
        pt.set_static('agent_a', {'code': 0.5})
        pt.record('agent_a', 'code', passed=True, score=80)
        pt.record('agent_a', 'code', passed=True, score=90)
        pt.record('agent_a', 'code', passed=True, score=85)
        # 3 次后开始混合动态权重（3 >= 最小样本数）
        w = pt.get_weight('agent_a', 'code')
        assert 0.5 <= w <= 1.0
        # 应该有动态成分（大于纯静态 0.5）
        assert w > 0.5

    def test_insufficient_samples_uses_static(self):
        pt = ProficiencyTracker()
        pt.set_static('agent_a', {'code': 0.7})
        pt.record('agent_a', 'code', passed=False, score=20)
        # 只有 1 条记录，不足 3，应返回纯静态
        w = pt.get_weight('agent_a', 'code')
        assert w == 0.7

    def test_sliding_window(self):
        pt = ProficiencyTracker()
        pt.set_static('agent_a', {'code': 0.5})
        # 大量失败记录
        for _ in range(30):
            pt.record('agent_a', 'code', passed=False, score=10)
        w = pt.get_weight('agent_a', 'code')
        # 通过率接近 0，动态权重应明显低于静态
        assert w < 0.5

    def test_unknown_agent_returns_default(self):
        pt = ProficiencyTracker()
        w = pt.get_weight('nonexistent', 'code')
        # 没有记录也没有静态基准，返回默认 0.5
        assert w == 0.5

    def test_to_dict(self):
        pt = ProficiencyTracker()
        pt.set_static('agent_a', {'code': 0.8})
        pt.record('agent_a', 'code', passed=True, score=90)
        pt.record('agent_a', 'code', passed=True, score=85)
        d = pt.to_dict()
        assert 'agent_a' in d
        assert 'code' in d['agent_a']
        assert d['agent_a']['code']['total'] == 2
        assert d['agent_a']['code']['pass_rate'] == 1.0


class TestAgentRegistry:
    def test_init(self):
        r = AgentRegistry()
        assert r.status() == {'agents': 0, 'online': 0}

    def test_register_and_list(self):
        r = AgentRegistry()
        r.register('agent_a', 'Agent A', {'chat', 'code'})
        r.register('agent_b', 'Agent B', {'search'})
        agents = r.list_all()
        assert len(agents) == 2
        ids = [a['id'] for a in agents]
        assert 'agent_a' in ids
        assert 'agent_b' in ids

    def test_register_default_values(self):
        r = AgentRegistry()
        r.register('a', 'Test', {'chat'})
        a = r.list_all()[0]
        assert a['online'] is True
        assert a['cost'] == 0

    def test_match_basic(self):
        r = AgentRegistry()
        r.register('agent_a', 'A', {'chat'}, executor=lambda p, c, e: 'ok')
        matched = r.match(['chat'])
        assert matched is not None
        assert matched['id'] == 'agent_a'

    def test_match_returns_none_when_no_candidate(self):
        r = AgentRegistry()
        r.register('agent_a', 'A', {'chat'}, executor=lambda p, c, e: 'ok')
        matched = r.match(['search'])
        assert matched is None

    def test_match_skips_offline_agents(self):
        r = AgentRegistry()
        r.register('agent_a', 'A', {'chat'}, executor=lambda p, c, e: 'ok')
        r.set_online('agent_a', False)
        matched = r.match(['chat'])
        assert matched is None

    def test_match_favors_lower_cost(self):
        r = AgentRegistry()
        r.register('paid', 'Paid', {'chat'}, cost=10,
                   executor=lambda p, c, e: 'ok')
        r.register('free', 'Free', {'chat'}, cost=0,
                   executor=lambda p, c, e: 'ok')
        matched = r.match(['chat'], prefer_free=True)
        assert matched['id'] == 'free'

    def test_run_agent(self):
        r = AgentRegistry()
        r.register('test', 'Test', {'chat'},
                   executor=lambda p, c, e: f'executed: {p}')
        reply = r.run('test', 'hello')
        assert reply == 'executed: hello'

    def test_run_agent_with_extra(self):
        r = AgentRegistry()
        def executor(prompt, caps, extra):
            return extra.get('key', 'no_extra')
        r.register('test', 'Test', {'chat'}, executor=executor)
        reply = r.run('test', 'hi', extra={'key': 'extra_value'})
        assert reply == 'extra_value'

    def test_run_nonexistent_agent(self):
        import pytest
        r = AgentRegistry()
        with pytest.raises(ValueError, match='未知 Agent'):
            r.run('nonexistent', 'test')

    def test_run_offline_agent(self):
        import pytest
        r = AgentRegistry()
        r.register('test', 'Test', {'chat'},
                   executor=lambda p, c, e: 'ok')
        r.set_online('test', False)
        with pytest.raises(RuntimeError, match='已熔断下线'):
            r.run('test', 'hi')

    def test_auto_circuit_breaker(self):
        r = AgentRegistry()
        r.register('test', 'Test', {'chat'},
                   executor=lambda p, c, e: (_ for _ in ()).throw(RuntimeError('fail')))
        for _ in range(3):
            try:
                r.run('test', 'hi')
            except Exception:
                pass
        assert r._agents['test']['online'] is False

    def test_record_result_updates_reliability(self):
        r = AgentRegistry()
        r.register('test', 'Test', {'chat'},
                   executor=lambda p, c, e: 'ok')
        r.run('test', 'hi')
        assert r._agents['test']['reliability'] == 1.0
        r.record_result('test', False)
        assert r._agents['test']['reliability'] == 0.5

    def test_find_by_capability(self):
        r = AgentRegistry()
        r.register('a', 'A', {'chat', 'code'}, executor=lambda p, c, e: 'ok')
        r.register('b', 'B', {'search'}, executor=lambda p, c, e: 'ok')
        matches = r.find_by_capability('chat')
        assert len(matches) == 1
        assert matches[0]['id'] == 'a'

    def test_unregister(self):
        r = AgentRegistry()
        r.register('a', 'A', {'chat'}, executor=lambda p, c, e: 'ok')
        r.unregister('a')
        assert r.status()['agents'] == 0

    def test_status(self):
        r = AgentRegistry()
        r.register('a', 'A', {'chat'}, executor=lambda p, c, e: 'ok')
        r.register('b', 'B', {'chat'}, executor=lambda p, c, e: 'ok')
        s = r.status()
        assert s['agents'] == 2
        assert s['online'] == 2

    def test_match_retry_limit(self):
        r = AgentRegistry()
        r.MAX_RETRIES = 2
        r.register('a', 'A', {'chat'}, executor=lambda p, c, e: 'ok')
        # 模拟重试
        task_id = 'task_1'
        r._inc_retry(task_id)
        r._inc_retry(task_id)
        r._inc_retry(task_id)  # 第三次，触发限制
        matched = r.match(['chat'], task_id=task_id)
        assert matched is None
