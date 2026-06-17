"""零 · 统一目标编排器 (GoalOrchestrator)
=========================================
替代 v4 TaskOrchestrator + v5-v8 MultiAgentOrchestrator。

单一入口，接收用户目标 → 返回执行结果。
内部路由：
  - 复杂任务 → SingleAgentOrchestrator（Planner→Executor→Critic→Synthesizer）
  - 简单任务 → 直接 LLM 调用（走三层上下文）

设计意图：
  - 所有历史编排器（v4 task_orchestrator, v5-v8 multi_agent/）都是死代码
  - 它们被维护但从未被调用（或已被单 Agent 流程链取代）
  - GoalOrchestrator 是零的统一编排入口，长期只维护这一个
"""

import time
from config import get_logger

logger = get_logger('zero.orchestrator')


class GoalOrchestrator:
    """统一目标编排器。
    
    用法:
        orch = GoalOrchestrator(llm_caller=call_llm)
        result = orch.run("写一个Python脚本解析CSV")
    
    返回:
        {
            'status': 'done' | 'partial' | 'failed',
            'answer': str,
            'steps': [...],     # 步骤详情
            'stats': {...},     # 统计
        }
    """
    
    def __init__(self, llm_caller, max_steps: int = 5):
        self._llm_caller = llm_caller
        self._max_steps = max_steps
        self._single_agent = None
        self._init_agent()
    
    def _init_agent(self):
        """延迟初始化 SingleAgentOrchestrator。"""
        if self._single_agent is None:
            try:
                from action.single_agent import SingleAgentOrchestrator
                self._single_agent = SingleAgentOrchestrator(
                    llm_caller=self._llm_caller,
                    max_steps=self._max_steps,
                )
                logger.info('GoalOrchestrator: SingleAgentOrchestrator 已就绪')
            except Exception as exc:
                logger.warning('GoalOrchestrator: 初始化失败: %s', exc)
    
    def run(self, goal: str, wm=None) -> dict:
        """执行目标。内部判断走单 Agent 流程链还是直接调用。"""
        if not goal or not goal.strip():
            return {
                'status': 'failed',
                'answer': '目标为空',
                'steps': [],
                'stats': {'total': 0, 'completed': 0, 'failed': 0, 'elapsed_s': 0},
            }
        
        start = time.time()
        
        # 判断是否复杂任务
        _complex_keywords = ['做', '建', '搭', '开发', '项目', '全流程', '整个', '完整',
                             '帮我', '写一个', '创建一个', '设计', '分析', '比较']
        is_complex = (len(goal) > 40 and
                     any(kw in goal for kw in _complex_keywords))
        
        if is_complex and self._single_agent:
            logger.debug('GoalOrchestrator: 走单 Agent 流程链: %s..', goal[:40])
            result = self._single_agent.run(goal, wm=wm)
        else:
            logger.debug('GoalOrchestrator: 直接调用 LLM: %s..', goal[:40])
            reply = self._llm_caller(messages=[
                {'role': 'system', 'content': '你是零，一个智能助手。直接回答用户的问题。'},
                {'role': 'user', 'content': goal},
            ], task_text=goal, task_type='reasoning', agent_id='goal_orch')
            elapsed = time.time() - start
            result = {
                'status': 'done',
                'answer': str(reply) if reply else '(无响应)',
                'steps': [{
                    'step': 1, 'action': goal, 'capability': 'chat',
                    'output': str(reply)[:500] if reply else '',
                    'passed': bool(reply), 'score': 100 if reply else 0,
                    'status': 'done' if reply else 'failed',
                }],
                'stats': {'total': 1, 'completed': 1 if reply else 0,
                          'failed': 0 if reply else 1, 'elapsed_s': round(elapsed, 2)},
            }
        
        return result
    
    def run_stream(self, goal: str) -> dict:
        """流式分段执行（兼容旧 collab API 格式）。
        
        返回格式兼容 v8 collaborate_v8 输出结构。
        """
        result = self.run(goal)
        # 转成类似 blackboard 的格式以兼容前端
        return {
            'status': result['status'],
            'answer': result.get('answer', ''),
            'steps': result.get('steps', []),
            'completed': result['stats']['completed'],
            'failed': result['stats']['failed'],
        }
