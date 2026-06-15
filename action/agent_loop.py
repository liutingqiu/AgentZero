"""零 · AgentLoop
=================
Think → Act → Observe → Decide 循环。

替代旧的 plan_then_execute。
最多 3 轮。提前结束条件：目标达成、连续失败、轮次上限。

用法:
  loop = AgentLoop(llm_caller, tools_executor)
  result = loop.run("e盘环的小说在哪")
"""

import json, re, time
from datetime import datetime


class AgentLoop:
    """Think→Act→Observe 决策循环。
    
    每轮:
      1. Think: LLM 决定下一步（用什么工具、什么参数）
      2. Act: 执行工具
      3. Observe: 观察结果
      4. Decide: 完成任务 or 继续
    
    提前结束:
      - LLM 返回 action="done"
      - 连续 2 次工具失败
      - 达到 3 轮上限
    """
    
    def __init__(self, llm_caller, tools_executor):
        """
        Args:
            llm_caller: 函数 (system_prompt, user_prompt) -> str
            tools_executor: 函数 (tool_name, args, timeout) -> dict
        """
        self.llm = llm_caller
        self.execute_tool = tools_executor
        self.max_turns = 3
    
    def run(self, task, context=''):
        """执行任务。
        
        Args:
            task: 用户任务描述
            context: 上下文（来自 build_context）
        
        Returns:
            {
                'status': 'done'|'failed'|'max_turns',
                'reply': str,       # 最终回复
                'steps': list,      # 每步的详细信息
                'loops': int,
            }
        """
        system = f"""你是零，主人的个人 AI Agent。你能用工具完成任务。

{context}

## 可用工具
read_file, write_file, edit_file, list_directory, search_files, search_content,
create_directory, delete_file, move_file, copy_file, shell,
web_search, web_fetch, sysmon, agent_status

## 响应格式
当你需要执行操作时:
{{"action": "工具名", "args": {{"参数": "值"}}, "reasoning": "为什么"}}

当你已经完成任务、可以回复用户时:
{{"action": "done", "reply": "给用户的回复"}}

## 规则
- 每次只用一个工具
- 拿到结果后判断：还需要更多操作吗？还是可以结束了？
- 用中文回复
- 搜索文件时用简短的 pattern（如搜'环'而不是'环这本小说在哪'）"""
        
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': task[:500]}  # 截断超长任务描述
        ]
        
        steps = []
        consecutive_fails = 0
        
        for turn in range(self.max_turns):
            # ── Think ──
            msgs = [{'role': m['role'], 'content': m['content'][:2000]} for m in messages]
            llm_reply = self.llm('', json.dumps(msgs, ensure_ascii=False))
            
            # 解析 LLM 回复
            decision = {}
            try:
                json_match = re.search(r'\{[\s\S]*\}', llm_reply)
                if json_match:
                    decision = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
            
            # v2: 非 JSON → 重试一次，不是直接返回（GPT-4o: 会掩盖工具调用错误）
            if not decision or 'action' not in decision:
                if turn == 0:
                    messages.append({'role': 'assistant', 'content': llm_reply})
                    messages.append({'role': 'user', 'content': '请输出合法JSON，格式: {"action": "done|"工具名", ...}'})
                    continue
                else:
                    return {
                        'status': 'error',
                        'reply': llm_reply[:500] if llm_reply else '无响应',
                        'steps': steps, 'loops': turn + 1
                    }
            
            action = decision.get('action', '')
            
            # ── Decide: done? ──
            if action == 'done':
                reply = decision.get('reply', llm_reply)
                return {
                    'status': 'done', 'reply': reply,
                    'steps': steps, 'loops': turn + 1
                }
            
            # ── Act ──
            tool_name = action
            args = decision.get('args', {})
            reasoning = decision.get('reasoning', '')
            
            step = {
                'turn': turn + 1,
                'tool': tool_name,
                'args': args,
                'reasoning': reasoning,
            }
            
            result = self.execute_tool(tool_name, args, timeout=30)
            step['result'] = result
            
            if result.get('success'):
                consecutive_fails = 0
                step['outcome'] = 'success'
            else:
                consecutive_fails += 1
                step['outcome'] = 'failure'
            
            steps.append(step)
            
            # ── Observe: 结果回传 LLM ──
            tool_output = json.dumps(result, ensure_ascii=False)[:1500]
            messages.append({'role': 'assistant', 'content': llm_reply[:1000]})
            messages.append({
                'role': 'user',
                'content': f'工具 {tool_name} 返回: {tool_output}\n\n请继续。完成则回复 action="done"。'
            })
            
            # v2: 控制 token 消耗——保留 system + 最近6条消息
            if len(messages) > 8:
                messages = [messages[0]] + messages[-7:]
            
            # ── 提前终止 ──
            if consecutive_fails >= 2:
                return {
                    'status': 'failed',
                    'reply': f'连续{consecutive_fails}次工具失败',
                    'steps': steps, 'loops': turn + 1
                }
        
        # 达到最大轮数
        return {
            'status': 'max_turns',
            'reply': f'达到{self.max_turns}轮上限，任务未完成',
            'steps': steps, 'loops': self.max_turns
        }
