"""测试工作记忆 cognition/working_memory.py"""

import time
from cognition.working_memory import WorkingMemory, RECENT_KEEP


class FakeLLMCaller:
    """伪造的 LLM 调用器，返回固定摘要。"""
    def __call__(self, messages, **kwargs):
        return '这是一个测试摘要，长度已经超过了十一个字符。'


class TestWorkingMemory:
    def test_init(self):
        wm = WorkingMemory()
        assert wm.conversation == []
        assert wm.early_summary == ''
        assert wm.system_anchors == {}
        assert wm.messages_count == 0
        assert wm.owner_mood == 'normal'

    def test_add_message(self):
        wm = WorkingMemory()
        wm.add_message('user', '你好')
        assert len(wm.conversation) == 1
        assert wm.conversation[0]['role'] == 'user'
        assert wm.conversation[0]['content'] == '你好'
        assert wm.messages_count == 1

    def test_add_multiple_messages(self):
        wm = WorkingMemory()
        wm.add_message('user', '你好')
        wm.add_message('assistant', '嗨！')
        assert len(wm.conversation) == 2
        assert wm.messages_count == 2

    def test_system_anchor(self):
        wm = WorkingMemory()
        wm.set_system_anchor('name', 'Zero')
        anchors = wm.get_system_anchors()
        assert anchors == {'name': 'Zero'}

    def test_remove_system_anchor(self):
        wm = WorkingMemory()
        wm.set_system_anchor('name', 'Zero')
        wm.remove_system_anchor('name')
        assert wm.get_system_anchors() == {}

    def test_tool_result_set_and_get(self):
        wm = WorkingMemory()
        wm.set_tool_result('search_1', '结果1\n结果2\n结果3')
        result = wm.get_tool_result('search_1')
        assert '结果1' in result
        assert '结果2' in result

    def test_tool_result_auto_trim(self):
        wm = WorkingMemory()
        long_output = '\n'.join(f'行{i}' for i in range(20))
        wm.set_tool_result('test', long_output)
        result = wm.get_tool_result('test')
        assert '... (共 20 行)' in result

    def test_tool_results_summary(self):
        wm = WorkingMemory()
        wm.set_tool_result('a', '结果A', summary='摘要A')
        wm.set_tool_result('b', '结果B', summary='摘要B')
        summary = wm.get_tool_results_summary()
        assert '摘要A' in summary
        assert '摘要B' in summary

    def test_build_context_messages_empty(self):
        wm = WorkingMemory()
        msgs = wm.build_context_messages('你好')
        assert len(msgs) == 1
        assert msgs[0]['role'] == 'user'
        assert msgs[0]['content'] == '你好'

    def test_build_context_with_anchors(self):
        wm = WorkingMemory()
        wm.set_system_anchor('identity', '你是助手')
        msgs = wm.build_context_messages('你好')
        assert len(msgs) == 2
        assert msgs[0]['role'] == 'system'
        assert '[identity]' in msgs[0]['content']

    def test_build_context_with_conversation(self):
        wm = WorkingMemory()
        wm.add_message('user', '你好')
        wm.add_message('assistant', '嗨！')
        msgs = wm.build_context_messages('今天天气')
        assert len(msgs) == 3
        # 顺序：conversation[0], conversation[1], user
        assert msgs[0]['role'] == 'user'
        assert msgs[0]['content'] == '你好'
        assert msgs[1]['role'] == 'assistant'
        assert msgs[2]['role'] == 'user'
        assert msgs[2]['content'] == '今天天气'

    def test_auto_summarize_old_rounds(self):
        wm = WorkingMemory()
        # 添加超过 RECENT_KEEP * 2 条消息触发摘要
        for i in range(RECENT_KEEP * 2 + 1):
            wm.add_message('user', f'消息{i}')
            wm.add_message('assistant', f'回复{i}')
        assert wm.has_pending_summary() is True

    def test_summarize_with_llm(self):
        wm = WorkingMemory()
        for i in range(RECENT_KEEP * 2 + 1):
            wm.add_message('user', f'消息{i}')
            wm.add_message('assistant', f'回复{i}')
        assert wm.has_pending_summary() is True
        msgs = wm.build_context_messages('新消息', llm_caller=FakeLLMCaller())
        print(f'\nDEBUG early_summary={repr(wm.early_summary)} pending={wm.has_pending_summary()}')
        # 摘要应该被触发，early_summary 非空
        assert wm.early_summary != '', f'early_summary 是空的，但 build_context 应该触发摘要'
        # 上下文应包含 early summary
        has_summary = any('【早期对话摘要】' in m.get('content', '') for m in msgs)
        assert has_summary, f'未在上下文中找到 early summary，msgs={[(m["role"], m["content"][:40]) for m in msgs]}'

    def test_mood_inference_positive(self):
        wm = WorkingMemory()
        wm.add_message('user', '太好了，你真棒')
        assert wm.owner_mood == 'relaxed'

    def test_mood_inference_negative(self):
        wm = WorkingMemory()
        wm.add_message('user', '真是垃圾，不行')
        assert wm.owner_mood == 'tired'

    def test_mood_inference_busy(self):
        wm = WorkingMemory()
        wm.add_message('user', '快！赶紧马上立刻完成！')
        assert wm.owner_mood == 'busy'

    def test_track_project_and_file(self):
        wm = WorkingMemory()
        wm.track_project('测试项目')
        assert wm.active_project == '测试项目'
        wm.track_file('a.py')
        wm.track_file('b.py')
        assert 'a.py' in wm.active_files
        assert 'b.py' in wm.active_files

    def test_mark_task_done(self):
        wm = WorkingMemory()
        assert wm.tasks_completed == 0
        wm.mark_task_done()
        assert wm.tasks_completed == 1

    def test_status(self):
        wm = WorkingMemory()
        wm.add_message('user', 'hi')
        wm.mark_task_done()
        s = wm.status()
        assert s['messages'] == 1
        assert s['tasks_done'] == 1
        assert s['owner_mood'] == 'normal'

    def test_get_conversation_history(self):
        wm = WorkingMemory()
        wm.add_message('user', 'a')
        wm.add_message('assistant', 'b')
        wm.add_message('user', 'c')
        history = wm.get_conversation_history(limit=2)
        assert len(history) == 2
        assert history[0]['content'] == 'b'
        assert history[1]['content'] == 'c'

    def test_get_context_string(self):
        wm = WorkingMemory()
        wm.track_project('测试')
        wm.add_message('user', '你好')
        ctx = wm.get_context()
        assert '测试' in ctx
        assert '你好' in ctx


class TestWorkingMemoryThreadSafety:
    def test_concurrent_add_message(self):
        import threading
        wm = WorkingMemory()
        n = 50
        def add():
            for i in range(n):
                wm.add_message('user', f'msg{i}')
        threads = [threading.Thread(target=add) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 全部消息都记录了，但可能因为摘要而移出 conversation
        assert wm.messages_count == 5 * n
        # conversation 不会无限增长
        assert len(wm.conversation) <= RECENT_KEEP * 2 + 5

    def test_concurrent_set_tool_result(self):
        import threading
        wm = WorkingMemory()
        n = 30
        def add():
            for i in range(n):
                wm.set_tool_result(f'k{i}', 'data')
        threads = [threading.Thread(target=add) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 工具结果缓存有限制
        assert len(wm.tool_results) <= 20
