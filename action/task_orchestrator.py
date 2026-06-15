"""零 · Task Orchestrator
==========================
中控台核心——拆任务、分Agent、追状态、管重试。

v2: 连接 TaskStateMachine + AgentRegistry。
每步发布事件，状态变化可追溯。
"""

import uuid, threading, time
from datetime import datetime


class Task:
    """一个子任务"""
    def __init__(self, task_id, description, required_capabilities,
                 success_criteria=None, parent_id=None):
        self.id = task_id
        self.description = description
        self.required_capabilities = required_capabilities  # ['code_generation', ...]
        self.success_criteria = success_criteria or f'完成: {description[:50]}'
        self.parent_id = parent_id
        self.agent_id = None
        self.result = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.completed_at = None
    
    def to_dict(self):
        return {
            'id': self.id, 'description': self.description,
            'capabilities': self.required_capabilities,
            'success_criteria': self.success_criteria,
            'agent': self.agent_id, 'result': self.result,
            'error': self.error, 'created': self.created_at,
            'completed': self.completed_at
        }


class TaskOrchestrator:
    """任务编排器——中控台核心。
    
    流程:
      用户任务 → decompose → 逐个子任务 → match Agent → execute → 
      record result → 下一个子任务 → 汇总返回
    
    连接 TaskStateMachine(状态追踪) 和 AgentRegistry(能力匹配)。
    """
    
    def __init__(self, state_machine, agent_registry, llm_caller=None, reviewer=None):
        self.tsm = state_machine        # TaskStateMachine
        self.registry = agent_registry  # AgentRegistry
        self.llm = llm_caller           # LLM 调用（用于拆任务）
        self.reviewer = reviewer        # Reviewer（v2: 结果验证）
        self._tasks = {}                # {task_id: Task}
        self._lock = threading.Lock()
    
    # ── 任务拆解 ──
    
    def decompose(self, goal, max_subtasks=5):
        """将大任务拆解为子任务列表。
        
        简单任务不拆（写函数、查资料、聊天等）。
        只有明确的多步骤任务才拆（做个网站、写项目等）。
        """
        # 不拆的情况：太短、单一请求
        if len(goal) < 30 or not any(kw in goal for kw in 
            ['做', '建', '搭', '开发', '项目', '全流程', '整个', '完整']):
            return self._simple_decompose(goal)
        
        if self.llm:
            return self._llm_decompose(goal, max_subtasks)
        else:
            return self._simple_decompose(goal)
    
    def _kanban_log(self, task, status='todo'):
        """自动写入看板"""
        try:
            from action.kanban import add_task as kb_add, update_status as kb_update
            if status == 'todo':
                kb_id = kb_add(task.description, body=task.success_criteria or '',
                              priority='normal', assignee=task.agent_id or '')
                task._kb_id = kb_id  # 记住看板ID
            else:
                kb_id = getattr(task, '_kb_id', 0)
                if kb_id:
                    kb_update(kb_id, status, 
                             result=str(task.result)[:200] if task.result else '',
                             error=str(task.error)[:200] if task.error else '')
        except:
            pass  # 看板不可用不影响主流程
    
    def _simple_decompose(self, goal):
        """无 LLM 时的简单拆解——整个目标就是一个任务"""
        tid = f'task_{uuid.uuid4().hex[:8]}'
        task = Task(tid, goal, ['chat'])  # 默认聊天能力
        with self._lock:
            self._tasks[tid] = task
        return [task]
    
    def _llm_decompose(self, goal, max_subtasks):
        """让 LLM 拆解任务"""
        prompt = f"""将以下任务拆解为 {max_subtasks} 步以内的子任务。每步指定需要的能力。

任务: {goal}

可用能力: code_generation, visual_design, search, file_ops, chat, browser_control

输出 JSON:
{{"steps": [{{"step": 1, "action": "做什么", "capability": "能力名"}}]}}"""
        
        try:
            reply = self.llm('你是任务拆解器', prompt)
            import json, re
            m = re.search(r'\{[\s\S]*\}', reply)
            if m:
                plan = json.loads(m.group())
                steps = plan.get('steps', [])
                tasks = []
                for s in steps[:max_subtasks]:
                    tid = f'task_{uuid.uuid4().hex[:8]}'
                    cap = s.get('capability', 'chat')
                    caps = [cap.strip()] if isinstance(cap, str) else cap
                    task = Task(tid, s.get('action', str(s)), caps)
                    with self._lock:
                        self._tasks[tid] = task
                    tasks.append(task)
                return tasks if tasks else self._simple_decompose(goal)
        except:
            pass
        return self._simple_decompose(goal)
    
    # ── 任务执行 ──
    
    def execute(self, goal, max_subtasks=5):
        """执行一个完整任务。拆解→逐子任务执行→汇总。
        
        Returns:
            {'status': 'done'|'partial'|'failed',
             'results': [...], 'summary': '...'}
        """
        # 1. 拆解
        subtasks = self.decompose(goal, max_subtasks)
        results = []
        
        for task in subtasks:
            self._kanban_log(task, 'todo')  # 看板记录
            result = self._execute_one(task)
            results.append(result)
            # 看板更新状态
            final_status = 'done' if result['status'] == 'done' else 'blocked'
            self._kanban_log(task, final_status)
            
            # 如果子任务失败且无 Agent 可用 → 提前终止
            if result['status'] == 'failed' and result.get('no_agent', False):
                break
        
        # 2. 汇总
        done = sum(1 for r in results if r['status'] == 'done')
        failed = sum(1 for r in results if r['status'] == 'failed')
        
        return {
            'status': 'done' if failed == 0 else ('partial' if done > 0 else 'failed'),
            'results': results,
            'summary': f'{len(results)}个子任务, {done}完成, {failed}失败',
            'subtasks': len(results),
            'completed': done,
            'failed': failed,
        }
    
    def _execute_one(self, task):
        """执行单个子任务——匹配Agent→执行→记录结果"""
        self.tsm.transition(task.id, 'task.created')
        
        # 1. 匹配 Agent
        agent = self.registry.match(task.required_capabilities, 
                                     prefer_free=True, task_id=task.id)
        if not agent:
            self.tsm.transition(task.id, 'task.failed')
            return {'status': 'failed', 'task_id': task.id,
                    'error': '没有可用的Agent', 'no_agent': True}
        
        task.agent_id = agent['id']
        self.tsm.transition(task.id, 'task.assigned')
        self.tsm.transition(task.id, 'task.started')
        
        # 2. 执行（通过 Agent 的 endpoint）
        try:
            result = self._call_agent(agent, task)
            task.result = result.get('output', str(result))
            task.completed_at = datetime.now().isoformat()
            
            if result.get('success'):
                # v2: Reviewer 验证（Agnes建议：执行后、状态更新前）
                if self.reviewer:
                    self.tsm.transition(task.id, 'task.reviewing')
                    verdict = self.reviewer.review(task, agent)
                    if not verdict.get('passed'):
                        self.registry.record_result(agent['id'], False)
                        self.tsm.transition(task.id, 'task.review_failed')
                        return {'status': 'failed', 'task_id': task.id,
                                'error': "Reviewer不通过: " + verdict.get('reason', '未知'),
                                'score': verdict.get('score', 0),
                                'agent': agent['name']}
                    self.tsm.transition(task.id, 'task.review_passed')
                
                self.registry.record_result(agent['id'], True)
                self.tsm.transition(task.id, 'task.completed')
                return {'status': 'done', 'task_id': task.id,
                        'agent': agent['name'], 'result': task.result,
                        'review_score': verdict.get('score') if self.reviewer else None}
            else:
                self.registry.record_result(agent['id'], False)
                task.error = result.get('error', '未知错误')
                self.tsm.transition(task.id, 'task.failed')
                return {'status': 'failed', 'task_id': task.id,
                        'error': task.error, 'agent': agent['name']}
        except Exception as e:
            self.registry.record_result(agent['id'], False)
            task.error = str(e)
            self.tsm.transition(task.id, 'task.failed')
            return {'status': 'failed', 'task_id': task.id,
                    'error': str(e), 'agent': agent['name']}
    
    def _call_agent(self, agent, task):
        """调用 Agent 执行任务。
        
        v2: 不再硬编码分支。Agent 注册时自带 executor 方法。
            如果没有 executor，回退到 LLM caller。
        """
        # 优先用 Agent 自带的 executor
        executor = agent.get('executor')
        if executor:
            try:
                return executor(task.description, task.required_capabilities)
            except Exception as e:
                return {'success': False, 'error': f'Agent执行异常: {e}'}
        
        # 回退：通过 LLM caller
        if self.llm:
            try:
                reply = self.llm('你是零的执行Agent', task.description)
                return {'success': True, 'output': reply}
            except Exception as e:
                return {'success': False, 'error': f'LLM调用失败: {e}'}
        
        return {'success': False, 'error': 'Agent未配置executor且无LLM'}
    
    # ── 状态查询 ──
    
    def status(self):
        return {
            'tasks_total': len(self._tasks),
            'tasks_active': sum(1 for t in self._tasks.values() 
                               if self.tsm.get_state(t.id) not in (
                                   'task.review_passed', 'task.cancelled', None)),
            'state_summary': self.tsm.get_all(),
        }
