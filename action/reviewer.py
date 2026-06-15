"""零 · Reviewer
================
独立验证模块。对每个子任务的执行结果做质量评判。

v2: GPT-4o 建议独立出来，不和 AgentLoop 耦合。
    不同任务类型用不同的验证标准。
"""


class Reviewer:
    """结果验证器。
    
    对 TaskOrchestrator 执行完的每个子任务，评判是否合格。
    不合格 → 触发重试或回炉重拆。
    """
    
    def __init__(self, llm_caller=None):
        self.llm = llm_caller
        self._history = []  # [{task_id, result, passed, reason}]
    
    def review(self, task, agent_info):
        """验证一个子任务的执行结果。
        
        Args:
            task: Task 对象（含 description, result, success_criteria）
            agent_info: 执行该任务的 Agent 信息
        
        Returns:
            {'passed': True/False, 'reason': '...', 'score': 0-100}
        """
        # 1. 基础检查
        if task.error:
            return {'passed': False, 'reason': f'执行错误: {task.error}', 'score': 0}
        
        if not task.result or len(str(task.result)) < 3:
            return {'passed': False, 'reason': '结果为空或过短', 'score': 0}
        
        # 2. LLM 深度验证（如果可用）
        if self.llm:
            return self._llm_review(task, agent_info)
        
        # 3. 简单规则兜底
        return self._rule_review(task, agent_info)
    
    def _llm_review(self, task, agent_info):
        """用 LLM 做深度验证"""
        prompt = f"""你是质量审查员。评估这个子任务的执行结果。

任务: {task.description}
成功标准: {task.success_criteria}
执行Agent: {agent_info.get('name', '未知')}
执行结果: {str(task.result)[:2000]}

评判标准:
- 是否完成了任务描述中的要求？
- 输出是否完整、可用？
- 如果有代码，逻辑是否正确？

请输出 JSON:
{{"passed": true/false, "reason": "评判理由(30字以内)", "score": 0-100}}"""
        
        try:
            reply = self.llm('你是质量审查员', prompt)
            import json, re
            m = re.search(r'\{[\s\S]*\}', reply)
            if m:
                verdict = json.loads(m.group())
                self._history.append({
                    'task_id': task.id,
                    'agent': agent_info.get('id', ''),
                    'passed': verdict.get('passed', False),
                    'reason': verdict.get('reason', ''),
                    'score': verdict.get('score', 50)
                })
                return verdict
        except:
            pass
        
        return self._rule_review(task, agent_info)
    
    def _rule_review(self, task, agent_info):
        """规则兜底验证"""
        result_text = str(task.result or '')
        
        # 代码生成检查
        if 'code' in str(task.required_capabilities):
            has_code = any(kw in result_text.lower() for kw in 
                          ['def ', 'class ', 'function', 'import', '<html', '{', '```'])
            passed = has_code and len(result_text) > 10
            reason = '包含代码结构' if passed else '未检测到代码'
        # 设计检查
        elif 'design' in str(task.required_capabilities):
            has_design = any(kw in result_text.lower() for kw in 
                           ['<html', '<style', 'css', 'color', '#', '<div'])
            passed = has_design and len(result_text) > 20
            reason = '包含设计元素' if passed else '未检测到设计内容'
        # 搜索检查
        elif 'search' in str(task.required_capabilities):
            passed = len(result_text) > 20
            reason = '搜索结果非空' if passed else '搜索结果为空'
        # 通用检查
        else:
            passed = len(result_text) > 10
            reason = '结果长度合格' if passed else '结果过短'
        
        score = 70 if passed else 20
        
        self._history.append({
            'task_id': task.id,
            'agent': agent_info.get('id', ''),
            'passed': passed, 'reason': reason, 'score': score
        })
        
        return {'passed': passed, 'reason': reason, 'score': score}
    
    def get_history(self, limit=20):
        return self._history[-limit:]
    
    def stats(self):
        if not self._history:
            return {'total': 0, 'pass_rate': 0}
        total = len(self._history)
        passed = sum(1 for h in self._history if h['passed'])
        return {'total': total, 'passed': passed, 
                'pass_rate': round(passed/total*100, 1)}
