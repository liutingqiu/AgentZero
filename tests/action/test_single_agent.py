"""测试单 Agent 流程链 action/single_agent.py"""

from unittest.mock import MagicMock
from action.single_agent import SingleAgentOrchestrator, StepResult


class TestStepResult:
    def test_create(self):
        s = StepResult(step_num=1, action='写代码', capability='code_generation')
        assert s.step_num == 1
        assert s.action == '写代码'
        assert s.capability == 'code_generation'
        assert s.status == 'pending'
        assert s.passed is False

    def test_to_summary_done(self):
        s = StepResult(step_num=0, action='写代码', capability='code_generation')
        s.output = 'print(1)'
        s.passed = True
        s.status = 'done'
        summary = s.to_summary()
        assert '步骤0' in summary
        assert '写代码' in summary
        assert '通过' in summary

    def test_to_summary_failed(self):
        s = StepResult(step_num=0, action='失败步骤', capability='chat')
        s.passed = False
        s.status = 'failed'
        s.issues = ['超时']
        summary = s.to_summary()
        assert '失败' in summary

    def test_to_dict(self):
        s = StepResult(step_num=1, action='测试', capability='chat')
        s.output = 'ok'
        s.passed = True
        s.score = 85
        d = s.to_dict()
        assert d['step'] == 1
        assert d['action'] == '测试'
        assert d['passed'] is True
        assert d['score'] == 85
        assert d['attempts'] == 0
        assert d['status'] == 'pending'


class TestRuleCritic:
    """测试 Critic 的规则评分 _rule_critic。"""

    def _make_step(self, output='', action='test', capability='chat'):
        s = StepResult(step_num=1, action=action, capability=capability)
        s.output = output
        return s

    def test_code_output_ok(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        step = self._make_step(output='def hello():\n    pass')
        passed, score, issues = sa._rule_critic(step)
        assert passed is True
        assert score >= 50

    def test_empty_output_fails(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        step = self._make_step(output='')
        passed, score, issues = sa._rule_critic(step)
        assert passed is False
        assert score <= 60

    def test_short_output_fails(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        step = self._make_step(output='短')
        passed, score, issues = sa._rule_critic(step)
        assert passed is False

    def test_error_keyword_penalty(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        step = self._make_step(output='执行失败')
        passed, score, issues = sa._rule_critic(step)
        assert score < 50

    def test_unclosed_code_block(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        # 输出足够长以通过长度检查，但代码块未闭合
        step = self._make_step(
            output='x' * 20 + '\n```\nprint(1)\n',
        )
        passed, score, issues = sa._rule_critic(step)
        assert '代码块未闭合' in issues

    def test_no_issues_valid_output(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        step = self._make_step(output='这是一个足够长的有效输出不包含那些关键词')
        passed, score, issues = sa._rule_critic(step)
        # 长度够且无问题关键词 → passed
        assert passed is True


class TestSingleAgentOrchestrator:
    def test_init(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        assert sa.max_retries == 2
        assert sa.enable_critic is True

    def test_plan_llm_failure_returns_empty(self):
        """LLM 调用失败时 _plan 返回空列表。"""
        def failing_llm(messages, **kwargs):
            raise RuntimeError('LLM 挂了')
        sa = SingleAgentOrchestrator(llm_caller=failing_llm)
        steps = sa._plan('做一个网站')
        assert steps == []

    def test_plan_llm_returns_invalid(self):
        """LLM 返回非 JSON 时 _plan 返回空列表。"""
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='不是 JSON'))
        steps = sa._plan('做一个网站')
        assert steps == []

    def test_plan_success(self):
        """LLM 返回有效步骤 JSON 时 _plan 返回 StepResult 列表。"""
        valid_json = (
            '{"steps": ['
            '{"step": 1, "action": "写HTML", "capability": "code_generation", "criteria": "ok"},'
            '{"step": 2, "action": "写CSS", "capability": "code_generation", "criteria": "ok"}'
            ']}'
        )
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value=valid_json))
        steps = sa._plan('做一个网站')
        assert len(steps) == 2
        assert steps[0].action == '写HTML'
        assert steps[1].action == '写CSS'
        assert steps[0].capability == 'code_generation'

    def test_synthesize_all_failed(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        steps = [
            StepResult(step_num=1, action='a', capability='chat'),
            StepResult(step_num=2, action='b', capability='chat'),
        ]
        for s in steps:
            s.status = 'failed'
            s.passed = False
            s.issues = ['错误']
        result = sa._synthesize('test', steps)
        assert '未完成' in result
        assert '错误' in result

    def test_synthesize_single_step(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='ok'))
        step = StepResult(step_num=1, action='a', capability='chat')
        step.status = 'done'
        step.passed = True
        step.output = '完成结果'
        result = sa._synthesize('test', [step])
        # 单步骤且全部完成 → 直接返回步骤输出
        assert result == '完成结果'

    def test_synthesize_multiple_steps(self):
        sa = SingleAgentOrchestrator(llm_caller=MagicMock(return_value='整合结果'))
        s1 = StepResult(step_num=1, action='a', capability='chat')
        s1.status = 'done'
        s1.passed = True
        s1.output = '结果1'
        s2 = StepResult(step_num=2, action='b', capability='chat')
        s2.status = 'done'
        s2.passed = True
        s2.output = '结果2'
        result = sa._synthesize('test', [s1, s2])
        assert result == '整合结果'
