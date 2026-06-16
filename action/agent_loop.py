"""零 · AgentLoop
=================
Think → Act → Observe → Decide 循环。

修复要点：
  - JSON 解析：括号计数版 extract_first_json 替换贪婪正则，
    避免 LLM 回复中包含多个 JSON 块时被吞掉工具调用
  - 日志：用 get_logger 替代隐式 print
"""

import json
import time
from datetime import datetime

from config import get_logger
from utils.json_helpers import extract_first_json

logger = get_logger('zero.agent_loop')


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
- 搜索文件时用简短的 pattern（如搜'环'而不是'环这本小说在哪'）
- 相同任务应给出相同结果，避免随机变异，输出稳定一致"""
        
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': task[:500]}  # 截断超长任务描述
        ]
        
        self._task = task
        steps = []
        consecutive_fails = 0
        
        for turn in range(self.max_turns):
            # ── Think ──
            # 结构化传递：保留 role 结构，不再拍平成文本 blob
            llm_reply = self.llm(messages=messages, task_text=self._task,
                                 agent_id=getattr(self, '_agent_id', ''))
            
            # 解析 LLM 回复（用括号计数版的 extract_first_json，
            # 避免贪婪正则吞掉"一段自然语言+JSON+一段自然语言"的结构）
            decision = extract_first_json(llm_reply) or {}
            if not isinstance(decision, dict):
                decision = {}
            
            # Bug B fix: 非 JSON → turn 0 重试一次；turn≥1 用 fallback parser
            # 保护条件：回复需 ≥20 字符且不含工具名误判关键词，才接受为自然语言 done
            if not decision or 'action' not in decision:
                if turn == 0:
                    messages.append({'role': 'assistant', 'content': llm_reply})
                    messages.append({'role': 'user', 'content': '请输出合法JSON，格式: {"action": "done"|"工具名", ...}'})
                    continue
                # Fallback parser: 自然语言回复 → 当作 done（有保护门槛）
                reply_text = (llm_reply or '').strip()
                _error_keywords = ['error', '错误', '失败', 'exception', 'traceback']
                if len(reply_text) >= 20 and not any(kw in reply_text.lower() for kw in _error_keywords):
                    return {
                        'status': 'done', 'reply': reply_text[:2000],
                        'steps': steps, 'loops': turn + 1
                    }
                return {
                    'status': 'error',
                    'reply': reply_text[:500] if reply_text else '无响应',
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
            step['result'] = result.to_dict() if hasattr(result, 'to_dict') else result

            # 兼容 Result 对象 (.ok) 和旧 dict ({'success': ...})
            if getattr(result, 'ok', False):
                consecutive_fails = 0
                step['outcome'] = 'success'
            else:
                consecutive_fails += 1
                step['outcome'] = 'failure'
            
            steps.append(step)
            
            # ── Observe: 结果回传 LLM ──
            tool_output = json.dumps(
                result.to_dict() if hasattr(result, 'to_dict') else result,
                ensure_ascii=False,
            )[:1500]
            messages.append({'role': 'assistant', 'content': llm_reply[:1000]})
            messages.append({
                'role': 'user',
                'content': (
                    f'[tool:{tool_name}]\n{tool_output}\n[/tool]\n'
                    f'请继续。完成则回复 action="done"。'
                ),
            })
            
            # Bug C fix: 阈值 8→6，max_turns=3 时实际生效
            # turn1 后 6 条消息，turn2 后 8 条，>6 在 turn2 触发截断
            if len(messages) > 6:
                messages = [messages[0]] + messages[-5:]
            
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
