"""零 v1 · 上线版
=================
精简架构: Router → Agent → Light Memory → Optional Judge

砍掉: control system / evaluator graph / drift / multi-judge / grounding / behavior canon
保留: Router + Agent 调度 + 轻量记忆 + 可选自检
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zero_server import call_llm, wm, session, detect_jailbreak
from cognition import memory_manager


# ═══════════════════════════════════════════
# v1 Router — 任务 → Agent 映射
# ═══════════════════════════════════════════

def route(task: str) -> tuple[str, str]:
    """v1 路由器：任务文本 → (agent_id, task_type)。

    规则:
      - 含代码关键词 → reasonix (DeepSeek)
      - 含分析关键词 → reasonix
      - 含生图/视频 → agnes_image
      - 含搜索 → tavily
      - 默认 → reasonix
    """
    t = task.lower()

    # 生图/视频
    if any(kw in t for kw in ['生成图片', '画', '生图', '图片', '视频',
                               'image', 'generate image', '图']):
        return 'agnes_image', 'image'

    # 搜索
    if any(kw in t for kw in ['搜索', '查一下', '搜', '找一下', 'search']):
        return 'tavily', 'search'

    # 代码/分析 → DeepSeek
    code_kw = ['写', '生成', '创建', '代码', '函数', '类', '修复', 'debug',
               '重构', '优化', 'python', 'html', 'css', 'js', '分析', '审查']
    if any(kw in t for kw in code_kw):
        return 'reasonix', 'reasoning'

    # 默认聊天 → Agnes (免费)
    return 'agnes_text', 'text'


# ═══════════════════════════════════════════
# v1 Handle — 精简版消息处理
# ═══════════════════════════════════════════

def handle_v1(text: str) -> str:
    """v1 消息处理——精简、稳定、可上线。

    流程:
      1. 越狱检测
      2. 路由选择 Agent
      3. 调用 Agent
      4. 记录记忆
    """
    # 1. 安全
    is_attack, reason = detect_jailbreak(text)
    if is_attack:
        return f'🛡️ 检测到{reason}，已拒绝。'

    # 2. 路由
    agent_id, task_type = route(text)
    wm.add_message('user', text)

    # 3. 调用
    agent_map = {
        'reasonix': lambda: call_llm(messages=[
            {'role': 'system', 'content': '你是 Reasonix，擅长代码和推理。中文回复。'},
            {'role': 'user', 'content': text},
        ], prefer_free=False, task_type='reasoning'),
        'agnes_text': lambda: call_llm(messages=[
            {'role': 'system', 'content': '你是零，主人的智能助手。中文回复，简洁友好。'},
            {'role': 'user', 'content': text},
        ], prefer_free=True, task_type='text'),
        'agnes_image': lambda: _handle_image(text),
        'tavily': lambda: _handle_search(text),
    }

    handler = agent_map.get(agent_id, agent_map['reasonix'])
    reply = handler()

    # 4. 记忆
    wm.add_message('assistant', reply)
    try:
        memory_manager.save_task(
            task_id=f'v1_{text[:30]}',
            agent=agent_id, task_type=task_type,
            input_summary=text[:100], outcome='success',
            tokens_used=len(reply),
        )
    except Exception:
        pass

    return reply


def _handle_image(text: str) -> str:
    """生图处理。"""
    from action.tools import execute
    result = execute('image_generate', {'prompt': text})
    if result.ok:
        data = result.data if isinstance(result.data, dict) else {}
        url = data.get('url', '')
        return f'🖼️ 已生成图片:\n{url}' if url else '生图完成，但未获取到URL'
    return f'生图失败: {result.error.message if result.error else "未知错误"}'


def _handle_search(text: str) -> str:
    """搜索处理。"""
    from action.tools import execute
    result = execute('web_search', {'query': text})
    if result.ok:
        data = result.data
        return str(data)[:3000] if data else '未找到结果'
    return '搜索不可用'


# ═══════════════════════════════════════════
# Multi-Agent 协作入口
# ═══════════════════════════════════════════

def handle_collaborate(text: str) -> str:
    """多Agent协作模式——由 GoalOrchestrator 接管。"""
    from action.goal_orchestrator import GoalOrchestrator
    result = GoalOrchestrator(llm_caller=call_llm).run(text)
    if result['status'] == 'done':
        return result['answer']
    return f'[{result["status"]}] {result["answer"]}'


# ═══════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        task = ' '.join(sys.argv[2:]) if len(sys.argv) > 2 else ''
    else:
        mode = 'chat'
        task = input('任务: ').strip()

    if not task:
        print('未输入任务')
        sys.exit(1)

    if mode == 'collab':
        print('🤝 多Agent协作模式')
        result = handle_collaborate(task)
    else:
        agent, _ = route(task)
        print(f'🎯 路由到: {agent}')
        result = handle_v1(task)

    print(f'\n{"=" * 50}')
    print(result)
