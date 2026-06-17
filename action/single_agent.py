"""零 · 单 Agent 流程链
=========================
Planner → Executor → Critic → Synthesizer 四角色，
共享同一个 LLM 调用，只是 system prompt 不同。

所有用户请求都尝试拆步骤链，不再硬判关键词。
Critic 支持规则评分 + LLM 评审双轨。

步骤链增量上下文传递：
  每步只传上一步的结论（步骤摘要），不传全量历史。
  避免步骤链中上下文不断膨胀。

设计文档：ZERO_REDESIGN.md §三、§4.5
"""

import json
import time
import uuid
from datetime import datetime

from config import get_logger
from utils.json_helpers import extract_first_json

logger = get_logger('zero.single_agent')


# ── 第 1 步：Planner ──

PLANNER_PROMPT = """你是任务拆解器（Planner）。
将用户的目标拆解为 1~5 个有序步骤。每步指定需要的能力。

可用能力: code_generation, visual_design, search, file_ops, chat, browser_control, reasoning

输出严格 JSON 格式（不要 markdown 包裹）：
{{"steps": [{{"step": 1, "action": "做什么", "capability": "能力名", "criteria": "验收标准"}}]}}

如果目标很简单（一句话问题、闲聊、问候），只返回 1 步即可。"""


# ── 第 2 步：Executor ──

EXECUTOR_PROMPT_TPL = """你是任务执行者（Executor）。
当前步骤: {action}
验收标准: {criteria}
可用工具: write_file, read_file, shell, search, browse

{context_summary}  {# 上一步的结论摘要，增量传递 #}
{feedback}

请直接输出结果。不需要用代码块包裹，直接输出内容。"""


# ── 第 3 步：Critic ──

CRITIC_RULES_PROMPT = """你是质量审查员（Critic）。
审查以下执行结果是否满足要求。

步骤: {action}
验收标准: {criteria}
执行结果:
---
{output}
---

请评估：
1. 结果是否完整、正确？
2. 是否满足验收标准？
3. 是否有明显错误或遗漏？

输出 JSON：
{{"passed": true/false, "score": 0-100, "issues": ["问题1"], "suggestions": ["建议1"]}}"""


# ── 第 4 步：Synthesizer ──

SYNTHESIZER_PROMPT = """你是结果整合者（Synthesizer）。
以下是各步骤的执行结果，整合为一份完整的最终答案输出给用户。

原始目标: {goal}

执行摘要: {summary}

步骤详情:
{steps_detail}

请给出最终答案（自然语言，包含关键输出和文件路径等）。"""


# ═══════════════════════════════════════════
# SingleAgentOrchestrator
# ═══════════════════════════════════════════


class StepResult:
    """一个步骤的执行结果。"""
    def __init__(self, step_num: int, action: str, capability: str,
                 criteria: str = ''):
        self.step_num = step_num
        self.action = action
        self.capability = capability
        self.criteria = criteria
        self.output: str = ''
        self.passed: bool = False
        self.score: float = 0.0
        self.issues: list[str] = []
        self.attempts: int = 0
        self.status: str = 'pending'  # pending | running | done | failed

    def to_dict(self) -> dict:
        return {
            'step': self.step_num,
            'action': self.action[:120],
            'capability': self.capability,
            'criteria': self.criteria[:120],
            'output': self.output[:500],
            'passed': self.passed,
            'score': self.score,
            'issues': self.issues,
            'attempts': self.attempts,
            'status': self.status,
        }

    def to_summary(self) -> str:
        """返回步骤的结论摘要（用于增量上下文传递）。"""
        passed_str = '通过' if self.passed else '失败'
        # 裁剪输出到关键结论
        output = self.output[:300] if self.output else '(无输出)'
        return (f'步骤{self.step_num}({self.action[:60]}): [{passed_str}]\n'
                f'结论: {output}')


class SingleAgentOrchestrator:
    """单 Agent 流程链。

    用户只有一个 LLM，拆成步骤链逐个执行。
    四角色共用一个 llm_caller，仅 system prompt 不同。

    步骤链增量上下文传递：
      - 每步 executor 只接收上一步的结论摘要
      - 不传全量历史
      - synthesizer 整合时传所有步骤的结论摘要（非原始输出）
    """

    def __init__(self, llm_caller,
                 max_retries: int = 2,
                 max_steps: int = 5,
                 enable_critic: bool = True):
        self.llm = llm_caller
        self.max_retries = max_retries
        self.max_steps = max_steps
        self.enable_critic = enable_critic

    # ── 公开入口 ──

    def run(self, goal: str, wm=None) -> dict:
        """完整流程：拆解 → 逐步执行（增量上下文传递） → 审查 → 整合。"""
        start = time.time()

        # 1. Planner: 拆解步骤
        steps = self._plan(goal)
        if not steps:
            steps = [StepResult(1, goal, 'chat', '')]

        # 2-3. Executor + Critic: 逐步骤执行（增量上下文传递）
        previous_summary = ''
        for step in steps:
            self._execute_step(step, previous_summary=previous_summary)
            # 累积上一步的结论摘要
            previous_summary = step.to_summary()
            # 将步骤结论记录到 working_memory 的工具结果缓存
            if wm:
                wm.set_tool_result(
                    key=f'step_{step.step_num}',
                    raw_output=step.output or '',
                    summary=step.to_summary(),
                )

        # 4. Synthesizer: 整合（只传步骤结论摘要）
        answer = self._synthesize(goal, steps)

        elapsed = time.time() - start
        done = sum(1 for s in steps if s.status == 'done')
        failed = sum(1 for s in steps if s.status == 'failed')

        # 有失败步骤时添加迭代提示
        if failed > 0:
            answer += '\n\n---\n💡 结果有部分步骤未通过审查，可以回复"再改"或"不够好"让我重新优化。'

        return {
            'status': 'done' if failed == 0 else ('partial' if done > 0 else 'failed'),
            'answer': answer,
            'steps': [s.to_dict() for s in steps],
            'stats': {
                'total': len(steps),
                'completed': done,
                'failed': failed,
                'elapsed_s': round(elapsed, 2),
            },
        }

    # ── Planner ──

    def _plan(self, goal: str) -> list[StepResult]:
        """用 LLM 拆解任务为步骤列表。"""
        try:
            reply = self.llm(messages=[
                {'role': 'system', 'content': PLANNER_PROMPT},
                {'role': 'user', 'content': f'目标: {goal}'},
            ], task_text=goal, task_type='reasoning', agent_id='planner')
        except Exception as exc:
            logger.warning('Planner 调用失败: %s', exc)
            return []

        plan = extract_first_json(str(reply)) if reply else None
        if not isinstance(plan, dict):
            return []

        raw_steps = plan.get('steps', [])
        if not isinstance(raw_steps, list) or not raw_steps:
            return []

        steps = []
        for i, s in enumerate(raw_steps[:self.max_steps]):
            if not isinstance(s, dict):
                continue
            steps.append(StepResult(
                step_num=i + 1,
                action=s.get('action', str(s)),
                capability=s.get('capability', 'chat'),
                criteria=s.get('criteria', ''),
            ))
        return steps

    # ── Executor + Critic（增量上下文） ──

    def _execute_step(self, step: StepResult, previous_summary: str = ''):
        """执行一个步骤（含重试和审查），只传上一步结论摘要。"""
        step.status = 'running'
        feedback = ''
        last_error = ''

        for attempt in range(self.max_retries + 1):
            step.attempts = attempt + 1
            try:
                # 构建 prompt，只带上一步的结论摘要
                context_section = ''
                if previous_summary:
                    context_section = f'上一步结果:\n{previous_summary}\n'

                prompt = EXECUTOR_PROMPT_TPL.format(
                    action=step.action,
                    criteria=step.criteria or '完成该步骤',
                    context_summary=context_section,
                    feedback=feedback,
                )
                output = self.llm(messages=[
                    {'role': 'system', 'content': '你是 Executor，执行步骤并输出结果。'},
                    {'role': 'user', 'content': prompt},
                ], task_text=step.action, task_type='reasoning',
                                   agent_id='executor')
                step.output = str(output) if output else ''

                if not step.output:
                    last_error = '空输出'
                    feedback = f'\n[修正反馈: 输出为空，请重试]\n'
                    continue

                # Critic 审查
                if self.enable_critic:
                    passed, score, issues = self._critic(step)
                    step.passed = passed
                    step.score = score
                    step.issues = issues

                    if passed:
                        step.status = 'done'
                        return

                    if attempt < self.max_retries:
                        suggestions = '; '.join(issues[:3]) if issues else '结果不满足要求'
                        feedback = f'\n[修正反馈: {suggestions}]\n请根据审查意见改进后重新输出。\n'
                        last_error = suggestions
                else:
                    step.passed = True
                    step.score = 60.0
                    step.status = 'done'
                    return

            except Exception as exc:
                last_error = str(exc)
                logger.warning('步骤 %d 执行异常: %s', step.step_num, exc)
                feedback = f'\n[执行异常: {exc}]\n请重试。\n'

        # 重试耗尽
        step.status = 'failed'
        step.issues = [last_error] if last_error else ['重试耗尽']
        step.passed = False
        step.score = 0.0

    # ── Critic ──

    def _critic(self, step: StepResult) -> tuple[bool, float, list[str]]:
        """审查步骤输出。返回 (passed, score, issues)。"""
        rule_passed, rule_score, rule_issues = self._rule_critic(step)

        llm_passed, llm_score, llm_issues = True, 100.0, []
        try:
            prompt = CRITIC_RULES_PROMPT.format(
                action=step.action,
                criteria=step.criteria or '完成该步骤',
                output=step.output[:3000],
            )
            reply = self.llm(messages=[
                {'role': 'system', 'content': '你是 Critic，审查执行结果。'},
                {'role': 'user', 'content': prompt},
            ], task_text=f'审查: {step.action}', task_type='reasoning',
                               agent_id='critic')
            verdict = extract_first_json(str(reply)) if reply else None
            if isinstance(verdict, dict):
                llm_passed = verdict.get('passed', True)
                llm_score = float(verdict.get('score', 80))
                llm_issues = verdict.get('issues', []) or []
        except Exception as exc:
            logger.warning('Critic LLM 失败: %s', exc)

        final_score = rule_score * 0.4 + llm_score * 0.6
        final_passed = rule_passed and llm_passed
        all_issues = list(dict.fromkeys(rule_issues + llm_issues))

        return final_passed, round(final_score, 1), all_issues[:5]

    @staticmethod
    def _rule_critic(step: StepResult) -> tuple[bool, float, list[str]]:
        """基于规则的快速审查（零成本）。"""
        issues = []
        score = 100.0
        output = step.output

        if not output or len(output.strip()) < 10:
            issues.append('输出内容过短')
            score -= 40

        error_patterns = ['error', 'exception', 'traceback', 'failed',
                          '未找到', '失败', '错误', '不可用']
        for pat in error_patterns:
            if pat.lower() in output.lower():
                issues.append(f'输出含错误关键词: {pat}')
                score -= 15
                break

        if '```' in output:
            count = output.count('```')
            if count % 2 != 0:
                issues.append('代码块未闭合')
                score -= 20

        if len(output) > 10000:
            issues.append('输出过长')
            score -= 5

        passed = score >= 50 and len(issues) == 0
        return passed, max(score, 0.0), issues

    # ── Synthesizer ──

    def _synthesize(self, goal: str, steps: list[StepResult]) -> str:
        """整合各步骤结果为最终答案（使用步骤结论摘要而非原始输出）。"""
        done = [s for s in steps if s.status == 'done']

        if not done:
            failed_parts = []
            for s in steps:
                if s.issues:
                    failed_parts.append(f'步骤{s.step_num}({s.action[:60]}): {"; ".join(s.issues[:2])}')
            summary = '; '.join(failed_parts) if failed_parts else '所有步骤执行失败'
            return f'任务执行未完成。\n{summary}'

        if len(done) == len(steps) and len(steps) == 1:
            return steps[0].output or '(空结果)'

        try:
            # 只使用步骤结论摘要（to_summary 返回裁剪后的文本）
            steps_detail = '\n\n'.join(
                f'## 步骤{s.step_num}: {s.action}\n'
                f'状态: {"通过" if s.passed else "失败"}\n'
                f'分数: {s.score}/100\n'
                f'结论:\n{s.to_summary()}'
                for s in steps
            )
            done_str = f'{len(done)}/{len(steps)}'
            reply = self.llm(messages=[
                {'role': 'system', 'content': SYNTHESIZER_PROMPT},
                {'role': 'user', 'content': SYNTHESIZER_PROMPT.format(
                    goal=goal,
                    summary=f'{done_str} 步骤成功完成',
                    steps_detail=steps_detail,
                )},
            ], task_text=f'整合: {goal}', task_type='reasoning',
                               agent_id='synthesizer')
            return str(reply) if reply else '(整合失败)'
        except Exception as exc:
            logger.warning('Synthesizer 失败: %s', exc)
            parts = [f'步骤{s.step_num}: {s.output[:500]}' for s in done]
            return '\n\n'.join(parts)
