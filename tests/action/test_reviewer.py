"""测试 Reviewer action/reviewer.py"""

from action.reviewer import Reviewer
from dataclasses import dataclass, field


@dataclass
class FakeTask:
    id: str = 'test_1'
    description: str = '写一个函数'
    success_criteria: str = '包含代码'
    result: str = ''
    error: str = ''
    required_capabilities: set = field(default_factory=lambda: {'chat'})


class TestReviewer:
    def test_init(self):
        r = Reviewer()
        assert r.stats() == {'total': 0, 'pass_rate': 0}

    def test_review_error(self):
        r = Reviewer()
        task = FakeTask(error='出错啦')
        result = r.review(task, {'id': 'a', 'name': 'A'})
        assert result['passed'] is False
        assert result['score'] == 0
        assert '出错' in result['reason']

    def test_review_empty_result(self):
        r = Reviewer()
        task = FakeTask(result='')
        result = r.review(task, {'id': 'a', 'name': 'A'})
        assert result['passed'] is False
        assert result['score'] == 0

    def test_review_short_result(self):
        r = Reviewer()
        task = FakeTask(result='ab')
        result = r.review(task, {'id': 'a', 'name': 'A'})
        assert result['passed'] is False

    def test_rule_review_code_present(self):
        r = Reviewer()
        task = FakeTask(
            result='def hello():\n    print("world")',
            required_capabilities={'code_generation'},
        )
        result = r._rule_review(task, {'id': 'a'})
        assert result['passed'] is True
        assert result['score'] >= 70

    def test_rule_review_code_absent(self):
        r = Reviewer()
        task = FakeTask(
            result='只有文字描述',
            required_capabilities={'code_generation'},
        )
        result = r._rule_review(task, {'id': 'a'})
        assert result['passed'] is False

    def test_rule_review_search_present(self):
        r = Reviewer()
        task = FakeTask(
            result='搜索结果内容足够长满足条件测试验证通过了。',
            required_capabilities={'search'},
        )
        result = r._rule_review(task, {'id': 'a'})
        assert result['passed'] is True

    def test_rule_review_design_present(self):
        r = Reviewer()
        task = FakeTask(
            result='<html><body><div>页面</div></body></html>',
            required_capabilities={'design'},
        )
        result = r._rule_review(task, {'id': 'a'})
        assert result['passed'] is True

    def test_rule_review_design_absent(self):
        r = Reviewer()
        task = FakeTask(
            result='只有文字说明',
            required_capabilities={'design'},
        )
        result = r._rule_review(task, {'id': 'a'})
        assert result['passed'] is False

    def test_rule_review_default(self):
        r = Reviewer()
        task = FakeTask(result='足够长的结果内容，达到标准')
        result = r._rule_review(task, {'id': 'a'})
        assert result['passed'] is True

    def test_rule_review_default_short(self):
        r = Reviewer()
        task = FakeTask(result='短')
        result = r._rule_review(task, {'id': 'a'})
        assert result['passed'] is False

    def test_llm_review_fallback_on_error(self):
        def broken_caller(messages, **kwargs):
            raise RuntimeError('LLM 挂了')
        r = Reviewer(llm_caller=broken_caller)
        task = FakeTask(result='正常结果')
        result = r.review(task, {'id': 'a', 'name': 'A'})
        # 应该回退到规则评分
        assert 'passed' in result
        assert 'reason' in result

    def test_get_history(self):
        r = Reviewer()
        task = FakeTask(result='正常结果')
        r.review(task, {'id': 'a', 'name': 'A'})
        assert len(r.get_history()) == 1
        assert r.get_history()[0]['task_id'] == 'test_1'

    def test_get_history_limit(self):
        r = Reviewer()
        for i in range(5):
            t = FakeTask(id=f't{i}', result='ok')
            r.review(t, {'id': 'a'})
        assert len(r.get_history(limit=3)) == 3

    def test_stats(self):
        r = Reviewer()
        assert r.stats()['total'] == 0
        t1 = FakeTask(id='t1', result='正常执行结果，长度足够')
        r.review(t1, {'id': 'a'})
        t2 = FakeTask(id='t2', result='', error='执行出错')
        r.review(t2, {'id': 'a'})
        s = r.stats()
        assert s['total'] == 2
        assert s['passed'] == 1
        assert s['pass_rate'] == 50.0
