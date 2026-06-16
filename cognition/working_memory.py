"""零 · 工作记忆
================
会话级上下文。存储在内存中，会话结束写入短期记忆。

内容:
  - 当前对话历史
  - 活跃项目追踪
  - 主人状态推断
  - 本次会话统计
"""

import time, os, threading
from datetime import datetime


class WorkingMemory:
    """工作记忆——当前会话的临时上下文。
    
    不是持久化的。会话结束时通过 flush() 写入短期记忆。
    """
    
    def __init__(self):
        self.session_start = datetime.now()
        self.conversation = []        # [{'role':'user'|'assistant', 'content':'...', 'time':'...'}]
        self.active_project = None    # 当前活跃项目名
        self.active_files = []        # 最近操作的文件列表
        self.messages_count = 0
        self.tasks_completed = 0
        self.owner_mood = 'normal'    # busy|normal|relaxed
        self.last_activity = time.time()
        self._lock = threading.Lock()  # 保护并发写入
    
    # ── 对话管理 ──
    
    def add_message(self, role, content):
        """记录一条对话（线程安全）。"""
        with self._lock:
            self.conversation.append({
                'role': role,
                'content': content,
                'time': datetime.now().strftime('%H:%M:%S')
            })
            self.messages_count += 1
            self.last_activity = time.time()

            # 推断情绪
            self._infer_mood(content, role)

            # 保留最近 20 条
            if len(self.conversation) > 20:
                self.conversation = self.conversation[-20:]
    
    def _infer_mood(self, content, role):
        """从消息内容推断主人情绪。
        
        v2: 加否定检测+语气强度加权（GPT-4o: 关键词计数会误判'我不是在夸奖'）
        """
        if role != 'user':
            return
        
        # 先检测否定前缀（'不是'、'没有'、'别'），否定范围内跳过正面词
        negated = False
        neg_patterns = ['不是', '没有', '别', '不算', '并非', '哪有']
        for np_word in neg_patterns:
            if np_word in content[:20]:  # 句首否定
                negated = True
                break
        
        positive = {'好':1, '不错':2, '厉害':2, '谢谢':1, '哈哈':2, '可以':1, '行':1, 'ok':1, '牛':2, '棒':2, '太好了':3}
        negative = {'不行':2, '错误':1, '失败':2, '生气':2, '烦':2, '垃圾':3, '烂':2, '唉':2, '算了':1, '糟糕':2}
        busy = {'快':1, '急':2, '马上':2, '赶紧':2, '速度':1, '立刻':2}
        
        pos = sum(w for k, w in positive.items() if k in content) if not negated else 0
        neg = sum(w for k, w in negative.items() if k in content)
        urgent = sum(w for k, w in busy.items() if k in content)
        
        if urgent > 1:
            self.owner_mood = 'busy'
        elif neg > pos + 2:
            self.owner_mood = 'tired'
        elif pos > neg + 1:
            self.owner_mood = 'relaxed'
        else:
            self.owner_mood = 'normal'
    
    # ── 项目追踪 ──
    
    def track_project(self, project_name):
        """标记当前活跃项目（线程安全）。"""
        with self._lock:
            self.active_project = project_name

    def track_file(self, filepath):
        """记录操作的文件（线程安全）。"""
        with self._lock:
            if filepath not in self.active_files:
                self.active_files.append(filepath)
            if len(self.active_files) > 10:
                self.active_files = self.active_files[-10:]

    def mark_task_done(self):
        with self._lock:
            self.tasks_completed += 1
    
    # ── 上下文导出 ──
    
    def get_context(self):
        """构建注入 LLM 的上下文摘要（控制在 600 chars 内）"""
        parts = []
        
        # 活跃项目
        if self.active_project:
            parts.append(f'活跃项目: {self.active_project}')
        
        # 最近对话摘要
        if self.conversation:
            recent = self.conversation[-3:]
            msgs = []
            for m in recent:
                role_icon = '👤' if m['role'] == 'user' else '🤖'
                msgs.append(f'{role_icon} {m["content"][:40]}')
            parts.append('最近: ' + ' | '.join(msgs))
        
        # 主人状态
        mood_map = {'busy': '忙碌中', 'tired': '疲惫', 'relaxed': '轻松', 'normal': '正常'}
        parts.append(f'主人: {mood_map.get(self.owner_mood, "正常")}')
        
        # 会话统计
        parts.append(f'本轮: {self.messages_count}消息/{self.tasks_completed}任务')
        
        return ' | '.join(parts)
    
    def get_conversation_history(self, limit=10):
        """返回最近 N 条对话（供 LLM 上下文注入）"""
        return self.conversation[-limit:]
    
    # ── 持久化 ──
    
    def flush(self, memory_manager):
        """会话结束时，将工作记忆写入短期记忆。
        
        v2: 加异常恢复备份（GPT-4o: flush 失败会丢数据）
        """
        if not memory_manager:
            return
        
        try:
            # 写入对话摘要
            if self.conversation:
                topic = self.active_project or '一般对话'
                summary = ' | '.join(
                    f'{m["role"]}: {m["content"][:50]}' 
                    for m in self.conversation[-5:]
                )
                memory_manager.save_conversation_summary(
                    topic=topic,
                    summary=summary[:200],
                    emotion=self.owner_mood,
                    messages_count=self.messages_count
                )
            
            # 写入会话级摘要（save_daily_state 不存在，改用 save_task）
            memory_manager.save_task(
                task_id=f'session_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                agent='zero',
                task_type='session_summary',
                input_summary=f'项目:{self.active_project or "none"} '
                              f'情绪:{self.owner_mood}',
                outcome='success',
                tokens_used=self.messages_count,
            )
        except Exception as e:
            # v2: 异常恢复——写入备份文件
            import json
            backup_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'data', 'memory_backup.json'
            )
            try:
                backup = {
                    'time': datetime.now().isoformat(),
                    'topic': self.active_project,
                    'conversation': self.conversation[-10:],
                    'mood': self.owner_mood,
                    'messages_count': self.messages_count,
                    'tasks_completed': self.tasks_completed,
                    'error': str(e)
                }
                with open(backup_path, 'w', encoding='utf-8') as f:
                    json.dump(backup, f, ensure_ascii=False, indent=2)
            except:
                pass
            print(f'[memory] flush 失败，已备份: {e}')
    
    def status(self):
        return {
            'session_duration': round(
                (datetime.now() - self.session_start).total_seconds() / 60, 1),
            'messages': self.messages_count,
            'tasks_done': self.tasks_completed,
            'active_project': self.active_project,
            'owner_mood': self.owner_mood,
        }
