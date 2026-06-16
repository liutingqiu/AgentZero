"""零 · Reviewer
================
独立验证模块。对每个子任务的执行结果做质量评判。

修复要点：
  - JSON 解析：贪婪正则 → extract_first_json（括号计数）
  - 日志：统一 get_logger
"""

import json

from config import get_logger
from utils.json_helpers import extract_first_json

logger = get_logger('zero.reviewer')


class Reviewer:
    """结果验证器。"""

    def __init__(self, llm_caller=None):
        self.llm = llm_caller
        self._history = []

    def review(self, task, agent_info):
        """验证一个子任务的执行结果。"""
        if task.error:
            result = {'passed': False, 'reason': f'执行错误: {task.error}', 'score': 0}
            self._history.append({
                'task_id': task.id,
                'agent': agent_info.get('id', ''),
                **result,
            })
            return result

        if not task.result or len(str(task.result)) < 3:
            result = {'passed': False, 'reason': '结果为空或过短', 'score': 0}
            self._history.append({
                'task_id': task.id,
                'agent': agent_info.get('id', ''),
                **result,
            })
            return result

        if self.llm:
            # 双轨评分：规则 60% + LLM 40%（确定性层）
            rule = self._rule_review(task, agent_info)
            llm = self._llm_review(task, agent_info)
            return {
                'passed': rule['passed'] or llm.get('passed', False),
                'reason': llm.get('reason', rule['reason']),
                'score': int(rule['score'] * 0.6 + llm.get('score', rule['score']) * 0.4),
            }

        return self._rule_review(task, agent_info)

    def _llm_review(self, task, agent_info):
        """用 LLM 做深度验证。"""
        prompt = f"""你是质量审查员。严格按事实评判，不要主观发挥。评估这个子任务的执行结果。

任务: {task.description}
成功标准: {task.success_criteria}
执行Agent: {agent_info.get('name', '未知')}
执行结果: {str(task.result)[:2000]}

评判标准（逐项核对，不推断）:
- 是否完成了任务描述中的要求？
- 输出是否完整、可用？
- 如果有代码，逻辑是否正确？

请输出 JSON（相同输入应返回相同评分）:
{{"passed": true/false, "reason": "评判理由(30字以内)", "score": 0-100}}"""

        try:
            reply = self.llm(messages=[
                {'role': 'system', 'content': '你是质量审查员。严格按事实评判，不要主观发挥。'},
                {'role': 'user', 'content': prompt},
            ])
            verdict = extract_first_json(reply)
            if isinstance(verdict, dict) and 'passed' in verdict:
                record = {
                    'task_id': task.id,
                    'agent': agent_info.get('id', ''),
                    'passed': bool(verdict.get('passed', False)),
                    'reason': str(verdict.get('reason', '')),
                    'score': int(verdict.get('score', 50)),
                }
                self._history.append(record)
                return record
            logger.info('LLM review 未返回可解析结构，回退到规则')
        except Exception as exc:
            logger.warning('LLM review 异常: %s', exc)

        return self._rule_review(task, agent_info)

    def _rule_review(self, task, agent_info):
        """规则兜底验证。先做输出格式一致性检查，再做能力专项检查。"""
        result_text = str(task.result or '')

        # ── 第0层：输出格式一致性（不参与决策，只记录） ──
        fmt_issues = []
        # 检测截断：末尾是否在单词/标签中间断裂
        if len(result_text) > 100 and result_text.rstrip()[-1] not in '.。！？!?）》"\'\n':
            fmt_issues.append('末尾可能截断')
        # 检测未闭合代码块
        if result_text.count('```') % 2 != 0:
            fmt_issues.append('代码块未闭合')
        # 检测未闭合 HTML 标签（简单启发式）
        import re as _re_rev
        tags = _re_rev.findall(r'<(/?)(\w+)', result_text)
        tag_stack = []
        for closing, tag in tags:
            if closing:
                if tag_stack and tag_stack[-1] == tag:
                    tag_stack.pop()
            else:
                tag_stack.append(tag)
        if tag_stack:
            fmt_issues.append(f'HTML标签未闭合: {", ".join(tag_stack[-3:])}')
        if fmt_issues:
            logger.debug('格式一致性: %s — %s', task.id, '; '.join(fmt_issues))

        if 'code' in str(task.required_capabilities):
            has_code = any(kw in result_text.lower() for kw in
                          ['def ', 'class ', 'function', 'import', '<html', '{', '```'])
            passed = has_code and len(result_text) > 10
            reason = '包含代码结构' if passed else '未检测到代码'
        elif 'design' in str(task.required_capabilities):
            has_design = any(kw in result_text.lower() for kw in
                            ['<html', '<style', 'css', 'color', '#', '<div'])
            passed = has_design and len(result_text) > 20
            reason = '包含设计元素' if passed else '未检测到设计内容'
        elif 'search' in str(task.required_capabilities):
            passed = len(result_text) > 20
            reason = '搜索结果非空' if passed else '搜索结果为空'
        else:
            passed = len(result_text) > 10
            reason = '结果长度合格' if passed else '结果过短'

        score = 70 if passed else 20
        self._history.append({
            'task_id': task.id,
            'agent': agent_info.get('id', ''),
            'passed': passed,
            'reason': reason,
            'score': score,
        })
        return {'passed': passed, 'reason': reason, 'score': score}

    def get_history(self, limit=20):
        return self._history[-limit:]

    def stats(self):
        if not self._history:
            return {'total': 0, 'pass_rate': 0}
        total = len(self._history)
        passed = sum(1 for h in self._history if h['passed'])
        return {
            'total': total,
            'passed': passed,
            'pass_rate': round(passed / total * 100, 1),
        }
