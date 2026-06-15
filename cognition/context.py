"""零 · 上下文注入器
====================
每次 LLM 调用前，自动组装上下文。

从工作记忆 + 短期记忆中提取最关键的信息，
压缩到 2000 chars 以内注入 LLM prompt。
"""

from datetime import datetime


def build_context(working_memory, memory_manager):
    """构建注入 LLM 的上下文（控制在 2000 chars 内）
    
    注入内容:
      1. 时间标识（压缩格式）
      2. 活跃项目
      3. 今日摘要
      4. 主人状态
      5. 相关记忆（从长期记忆中检索）
    
    Args:
        working_memory: WorkingMemory 实例
        memory_manager: memory_manager 模块
    
    Returns:
        str: 上下文文本（可直接注入 LLM system prompt）
    """
    parts = []
    
    # 1. 时间
    now = datetime.now()
    weekday_cn = ['一','二','三','四','五','六','日'][now.weekday()]
    hour = now.hour
    period = '凌晨' if hour < 6 else '早上' if hour < 9 else '上午' if hour < 12 else '下午' if hour < 18 else '晚上'
    parts.append(f'时间: {now.month}/{now.day} 周{weekday_cn} {period}')
    
    # 2. 主人身份
    parts.append('主人: 柳橙')
    
    # 3. 工作记忆上下文
    wm_ctx = working_memory.get_context()
    if wm_ctx:
        parts.append(wm_ctx)
    
    # 4. 今日状态
    if memory_manager:
        today = memory_manager.get_today_state()
        if today:
            parts.append(
                f'今日: {today.get("messages_count",0)}消息 '
                f'{today.get("tasks_completed",0)}任务 '
                f'{today.get("files_modified",0)}文件修改'
            )
    
    # 5. 长期记忆检索（v2: GPT-4o 指出这是坑，build_context 应该检索长期记忆）
    if memory_manager:
        search_terms = []
        if working_memory.active_project:
            search_terms.append(working_memory.active_project)
        if working_memory.conversation:
            last_msg = working_memory.conversation[-1]['content'][:50]
            search_terms.append(last_msg)
        
        for term in search_terms[:2]:
            related = memory_manager.search_memory(term, limit=3)
            if related:
                memories = '; '.join(
                    f'{r.get("input_summary","")[:50]}' 
                    for r in related if r.get('outcome') != 'failure'
                )
                if memories:
                    parts.append(f'长期记忆: {memories}')
                    break  # 一个来源就够了，节省 token
    
    # 6. 对话摘要（最近7天的对话主题）
    if memory_manager:
        summaries = memory_manager.get_conversation_summaries(days=7, limit=3)
        if summaries:
            topics = '; '.join(s['topic'][:30] for s in summaries)
            if topics:
                parts.append(f'最近话题: {topics}')
    
    return '\n'.join(parts)


def build_llm_messages(working_memory, system_prompt, user_message):
    """构建完整的 LLM messages 数组
    
    Args:
        working_memory: WorkingMemory 实例
        system_prompt: 系统提示词
        user_message: 当前用户消息
    
    Returns:
        list: [{'role':'system',...}, {'role':'user',...}, ...]
    """
    messages = [{'role': 'system', 'content': system_prompt}]
    
    # 注入最近对话历史（最多 6 条）
    history = working_memory.get_conversation_history(limit=6)
    for h in history:
        messages.append({'role': h['role'], 'content': h['content'][:500]})
    
    # 当前消息
    if not history or history[-1]['content'] != user_message:
        messages.append({'role': 'user', 'content': user_message})
    
    return messages
