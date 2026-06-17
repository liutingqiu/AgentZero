"""零 · 工作记忆
================
会话级上下文。存储在内存中，会话结束写入短期记忆。

三层上下文结构（类似 Reasonix 的分层设计）：
  1. recent — 最近 N 轮对话完整保留（默认 6 轮，逐字可用）
  2. tool_trimmed — 中间轮次的工具输出被裁剪为结论
  3. early_summary — 早期对话的渐进式摘要

系统注入内容（system_anchors）永不过期，永远锁在上下文里。
"""

import time, os, threading
from datetime import datetime
from pathlib import Path

# 三层上下文的默认轮次配置
RECENT_KEEP = 6       # 保留完整的最新 N 轮（包含 user + assistant 各算一轮）
SUMMARIZE_BATCH = 2   # 每次满多少轮触发一次摘要提炼
TOOL_TRIM_LENGTH = 200  # 工具输出裁剪到多少字符以内


class WorkingMemory:
    """工作记忆——当前会话的临时上下文。
    
    三层结构：
      .conversation    — 最近 RECENT_KEEP 轮完整对话（最新）
      .tool_results   — 步骤工具输出裁剪后的结论缓存
      .early_summary  — 早期对话的渐进式摘要（最旧）
    
    系统注入（.system_anchors）永不过期。
    """
    
    def __init__(self):
        self.session_start = datetime.now()
        self.conversation = []         # 最近完整对话 [{'role','content','time'}]
        self.tool_results = {}         # {step_id_or_key: {'raw_len': int, 'summary': str}}
        self.early_summary = ''        # 早期对话的渐进式摘要文本
        self.system_anchors = {}       # 系统注入内容 {key: content} 永不过期
        self.active_project = None
        self.active_files = []
        self.messages_count = 0
        self.tasks_completed = 0
        self.owner_mood = 'normal'
        self.last_activity = time.time()
        self._lock = threading.Lock()
        self._summarize_lock = threading.Lock()  # 防止并发摘要冲突
    
    # ── 系统锚点（永不过期） ──
    
    def set_system_anchor(self, key: str, content: str):
        """设置系统级锚点内容。永远保留在上下文中。"""
        with self._lock:
            self.system_anchors[key] = content
    
    def remove_system_anchor(self, key: str):
        with self._lock:
            self.system_anchors.pop(key, None)
    
    def get_system_anchors(self) -> dict:
        with self._lock:
            return dict(self.system_anchors)
    
    # ── 工具输出裁剪 ──
    
    def set_tool_result(self, key: str, raw_output: str, summary: str = ''):
        """记录工具输出，只保留结论摘要。
        
        summary 为外部 LLM 提炼后的结论，如果为空则自动裁剪 raw_output。
        """
        with self._lock:
            if not summary:
                # 自动裁剪：取前 TOOL_TRIM_LENGTH 字符 + 行数缩略
                lines = raw_output.split('\n')
                if len(lines) > 5:
                    summary = '\n'.join(lines[:3]) + f'\n... (共 {len(lines)} 行)'
                else:
                    summary = raw_output[:TOOL_TRIM_LENGTH]
            self.tool_results[key] = {
                'raw_len': len(raw_output),
                'summary': summary,
                'time': time.time(),
            }
            # 限制缓存大小
            if len(self.tool_results) > 20:
                oldest = sorted(self.tool_results.keys(),
                                key=lambda k: self.tool_results[k]['time'])[:10]
                for k in oldest:
                    del self.tool_results[k]
    
    def get_tool_result(self, key: str) -> str:
        """获取裁剪后的工具结果摘要。"""
        with self._lock:
            entry = self.tool_results.get(key)
            return entry['summary'] if entry else ''
    
    def get_tool_results_summary(self) -> str:
        """将所有工具结果合并为一段摘要文本。"""
        with self._lock:
            if not self.tool_results:
                return ''
            parts = []
            for k, v in self.tool_results.items():
                parts.append(f'{k}: {v["summary"]}')
            return '\n'.join(parts)
    
    # ── 对话管理（三层上下文） ──
    
    def add_message(self, role, content):
        """记录一条对话，自动触发渐进式摘要（线程安全）。
        
        流程：
          1. 追加到 conversation（最新轮次）
          2. 超过 RECENT_KEEP → 把最旧的 SUMMARIZE_BATCH 轮提炼成摘要
          3. 摘要追加到 early_summary，从 conversation 移除
        """
        with self._lock:
            self.conversation.append({
                'role': role,
                'content': content,
                'time': datetime.now().strftime('%H:%M:%S')
            })
            self.messages_count += 1
            self.last_activity = time.time()
            self._infer_mood(content, role)
        
        # 检查是否需要将旧轮次提炼为摘要
        self._maybe_summarize_old()
    
    def _maybe_summarize_old(self):
        """当 conversation 超过 RECENT_KEEP 时，将最旧的提炼为摘要。
        
        这是静默操作，不在前台阻塞——摘要由外部 LLM 调用补充，
        这里只做标记和移动，实际的 LLM 提炼由 llm.py 的 handle_message 触发。
        """
        with self._lock:
            # 需要提炼的阈值 = RECENT_KEEP * 2（user+assistant 一对算2条）
            threshold = RECENT_KEEP * 2
            if len(self.conversation) <= threshold:
                return
            
            # 取最旧的 SUMMARIZE_BATCH*2 条（user+assistant 配对）
            batch = self.conversation[:SUMMARIZE_BATCH * 2]
            self._pending_summarize = batch
            # 从 conversation 移除，等待 LLM 提炼
            self.conversation = self.conversation[SUMMARIZE_BATCH * 2:]
    
    def has_pending_summary(self) -> bool:
        """检查是否有待提炼的旧对话。"""
        with self._lock:
            return bool(getattr(self, '_pending_summarize', None))
    
    def pop_pending_summary(self) -> list:
        """取出待提炼的旧对话批次。"""
        with self._lock:
            batch = getattr(self, '_pending_summarize', [])
            self._pending_summarize = []
            return batch
    
    def append_early_summary(self, summary_text: str):
        """追加一段早期对话摘要到 early_summary。"""
        with self._lock:
            if self.early_summary:
                self.early_summary += '\n' + summary_text
            else:
                self.early_summary = summary_text
            # 限制 early_summary 长度（最多保留 5 段摘要）
            parts = self.early_summary.split('\n')
            if len(parts) > 10:
                self.early_summary = '\n'.join(parts[-10:])
    
    # ── 上下文导出（供 LLM 构建 messages） ──
    
    def build_context_messages(self, user_text: str, llm_caller=None) -> list:
        """按三层结构构建 LLM messages。
        
        返回格式：
          [
            system_anchors...,           # 系统注入（永不过期）
            early_summary 消息,          # 早期对话摘要
            recent 完整对话...,          # 最近 N 轮完整
            user 消息,                   # 当前用户输入
          ]
        
        如果有待提炼的旧对话，自动调用 llm_caller 进行摘要。
        """
        # 先检查是否需要摘要提炼
        if self.has_pending_summary() and llm_caller:
            self._summarize_old_rounds(llm_caller)
        
        messages = []
        
        # 第一层：系统锚点（永不过期）
        with self._lock:
            for key, content in self.system_anchors.items():
                messages.append({
                    'role': 'system',
                    'content': f'[{key}]\n{content}',
                })
        
        # 第二层：早期对话摘要
        with self._lock:
            if self.early_summary:
                messages.append({
                    'role': 'system',
                    'content': f'【早期对话摘要】\n{self.early_summary[:1500]}',
                })
        
        # 第三层：最近完整对话
        with self._lock:
            for m in self.conversation:
                messages.append({
                    'role': m['role'],
                    'content': m['content'],
                })
        
        # 第四层：工具结果摘要（若有）
        tool_summary = self.get_tool_results_summary()
        if tool_summary:
            messages.append({
                'role': 'system',
                'content': f'【工具执行摘要】\n{tool_summary[:1000]}',
            })
        
        # 第五层：当前用户消息
        messages.append({'role': 'user', 'content': user_text})
        
        return messages
    
    def _summarize_old_rounds(self, llm_caller):
        """调用 LLM 将待提炼的旧对话批次生成摘要。"""
        batch = self.pop_pending_summary()
        if not batch:
            return
        
        # 构建摘要 prompt
        dialogue_text = '\n'.join(
            f'{m["role"]}: {m["content"][:200]}'
            for m in batch
        )
        
        try:
            summary = llm_caller(messages=[
                {'role': 'system', 'content': '你是对话摘要器。将以下对话提炼为1-2句话，保留关键信息、决策和结论。'},
                {'role': 'user', 'content': f'请摘要以下对话:\n{dialogue_text}'},
            ], task_type='reasoning', agent_id='summarizer')
            
            if summary and len(str(summary)) > 10:
                self.append_early_summary(
                    f'[{batch[0].get("time", "")}] {str(summary).strip()}'
                )
        except Exception as exc:
            # 摘要失败不阻塞，降级为简单截断
            logger = __import__('logging').getLogger('zero.memory')
            logger.debug('摘要生成失败: %s', exc)
            # 降级：直接保存原文片段
            self.append_early_summary(
                f'[摘要降级] {" ".join(m["content"][:80] for m in batch[:2])}'
            )
    
    # ── 原有接口（保持向下兼容） ──
    
    def _infer_mood(self, content, role):
        if role != 'user':
            return
        negated = False
        neg_patterns = ['不是', '没有', '别', '不算', '并非', '哪有']
        for np_word in neg_patterns:
            if np_word in content[:20]:
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
    
    def track_project(self, project_name):
        with self._lock:
            self.active_project = project_name
    
    def track_file(self, filepath):
        with self._lock:
            if filepath not in self.active_files:
                self.active_files.append(filepath)
            if len(self.active_files) > 10:
                self.active_files = self.active_files[-10:]
    
    def mark_task_done(self):
        with self._lock:
            self.tasks_completed += 1
    
    def get_context(self):
        parts = []
        if self.active_project:
            parts.append(f'活跃项目: {self.active_project}')
        if self.conversation:
            recent = self.conversation[-3:]
            msgs = []
            for m in recent:
                role_icon = '👤' if m['role'] == 'user' else '🤖'
                msgs.append(f'{role_icon} {m["content"][:40]}')
            parts.append('最近: ' + ' | '.join(msgs))
        mood_map = {'busy': '忙碌中', 'tired': '疲惫', 'relaxed': '轻松', 'normal': '正常'}
        parts.append(f'主人: {mood_map.get(self.owner_mood, "正常")}')
        parts.append(f'本轮: {self.messages_count}消息/{self.tasks_completed}任务')
        return ' | '.join(parts)
    
    def get_conversation_history(self, limit=10):
        with self._lock:
            return self.conversation[-limit:]
    
    def flush(self, memory_manager):
        if not memory_manager:
            return
        try:
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

        # ── 写入 session_memory.md（无论 memory_manager 是否成功） ──
        try:
            mem_text = self._format_session_memory()
            path = Path(self.SESSION_MEMORY_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(mem_text, encoding='utf-8')
        except Exception as e:
            print(f'[memory] session_memory.md 写入失败: {e}')
    
    def status(self):
        with self._lock:
            return {
                'session_duration': round(
                    (datetime.now() - self.session_start).total_seconds() / 60, 1),
                'messages': self.messages_count,
                'tasks_done': self.tasks_completed,
                'active_project': self.active_project,
                'owner_mood': self.owner_mood,
                'conversation_len': len(self.conversation),
                'early_summary_len': len(self.early_summary),
                'tool_results_count': len(self.tool_results),
                'system_anchors': list(self.system_anchors.keys()),
            }

    # ── 会话持久化：flush → session_memory.md ──

    SESSION_MEMORY_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'memory', 'session_memory.md'
    )

    def _format_session_memory(self) -> str:
        """将当前工作记忆格式化为 session_memory.md 文本。"""
        lines = []
        lines.append(f'# 会话记忆 — {self.session_start.strftime("%Y-%m-%d %H:%M")}')
        lines.append('')
        lines.append('## 进度')
        lines.append('')
        lines.append(f'- **消息总数:** {self.messages_count}')
        lines.append(f'- **完成任务:** {self.tasks_completed}')
        lines.append(f'- **活跃项目:** {self.active_project or "无"}')
        lines.append(f'- **用户情绪:** {self.owner_mood}')

        if self.system_anchors:
            lines.append('')
            lines.append('## 系统锚点')
            lines.append('')
            for key, content in self.system_anchors.items():
                # 只保留前 200 字符
                truncated = content[:200].replace('\n', ' ')
                lines.append(f'- **{key}:** {truncated}')
            lines.append('')

        if self.early_summary:
            lines.append('')
            lines.append('## 早期摘要')
            lines.append('')
            lines.append(self.early_summary[:1000])
            lines.append('')

        if self.conversation:
            lines.append('')
            lines.append('## 最近对话')
            lines.append('')
            for m in self.conversation[-6:]:
                content_preview = m['content'][:120].replace('\n', ' ')
                lines.append(f'- {m["role"]} ({m.get("time","")}): {content_preview}')
            lines.append('')

        if self.tool_results:
            lines.append('')
            lines.append('## 工具结果摘要')
            lines.append('')
            for k, v in self.tool_results.items():
                lines.append(f'- {k}: {v["summary"][:100]}')
            lines.append('')

        lines.append('')
        lines.append(f'_最后活动: {datetime.fromtimestamp(self.last_activity).strftime("%H:%M:%S")}_')
        lines.append('')
        return '\n'.join(lines)

    @staticmethod
    def _next_section_line(lines, start):
        """从 start 开始向后找第一个 ## 行，或返回 False"""
        for j in range(start, min(start + 5, len(lines))):
            if lines[j].startswith('## '):
                return True
        return False

    def _restore_from_text(self, text: str):
        """从 session_memory.md 文本中恢复状态。
        
        按行解析 Markdown 结构，提取关键字段。
        """
        lines = text.split('\n')
        restored_anchors = {}
        restored_early = []
        restored_conversation = []
        restored_tool_results = {}

        # 先用章节标题分割文本
        sections = {}  # name -> [lines]
        current_sec = 'header'
        sec_lines = []
        for line in lines:
            if line.startswith('## '):
                sections[current_sec] = sec_lines
                current_sec = line[3:].strip()
                sec_lines = []
            else:
                sec_lines.append(line)
        sections[current_sec] = sec_lines

        # 解析 header 中的顶级字段
        header_lines = sections.get('header', [])
        sec_progress = sections.get('进度', [])
        for line in header_lines + sec_progress:
            if line.startswith('- **消息总数:**'):
                self.messages_count = self._parse_int_after(line, ':**')
            elif line.startswith('- **完成任务:**'):
                self.tasks_completed = self._parse_int_after(line, ':**')
            elif line.startswith('- **活跃项目:**'):
                val = line.split(':**', 1)[1].strip() if ':**' in line else ''
                if val and val != '无':
                    self.active_project = val
            elif line.startswith('- **用户情绪:**'):
                val = line.split(':**', 1)[1].strip() if ':**' in line else ''
                if val in ('normal', 'busy', 'tired', 'relaxed'):
                    self.owner_mood = val

        # 解析系统锚点
        for line in sections.get('系统锚点', []):
            stripped = line.strip()
            if stripped.startswith('- **'):
                # 格式: - **key:** content
                inner = stripped[4:]  # 去掉 '- **' (4 chars)
                end_key = inner.find(':**')
                if end_key >= 0:
                    key = inner[:end_key]
                    content = inner[end_key + 3:].strip()
                    restored_anchors[key] = content

        # 解析早期摘要
        for line in sections.get('早期摘要', []):
            stripped = line.strip()
            if stripped and not stripped.startswith('-') and not stripped.startswith('_'):
                restored_early.append(stripped)

        # 解析最近对话
        for line in sections.get('最近对话', []):
            stripped = line.strip()
            if stripped.startswith('- '):
                # 格式: - role (time): content
                inner = stripped[2:]
                role_end = inner.find(' (')
                if role_end >= 0:
                    role = inner[:role_end]
                    rest2 = inner[role_end + 2:]
                    time_end = rest2.find('):')
                    if time_end >= 0:
                        tm = rest2[:time_end]
                        content = rest2[time_end + 2:].strip()
                        restored_conversation.append({
                            'role': role,
                            'content': content,
                            'time': tm,
                        })

        # 解析工具结果
        for line in sections.get('工具结果摘要', []):
            stripped = line.strip()
            if stripped.startswith('- '):
                inner = stripped[2:]
                colon = inner.find(': ')
                if colon >= 0:
                    key = inner[:colon]
                    summary = inner[colon + 2:].strip()
                    restored_tool_results[key] = {
                        'raw_len': 0,
                        'summary': summary,
                        'time': time.time(),
                    }

        # 写回
        with self._lock:
            if restored_anchors:
                self.system_anchors = restored_anchors
            if restored_early:
                self.early_summary = '\n'.join(restored_early)
            if restored_conversation:
                self.conversation = restored_conversation
            if restored_tool_results:
                self.tool_results = restored_tool_results

    @staticmethod
    def _parse_int_after(line, sep):
        try:
            return int(line.split(sep, 1)[1].strip())
        except (ValueError, IndexError):
            return 0

    @classmethod
    def restore_from_memory(cls) -> 'WorkingMemory':
        """从 session_memory.md 恢复工作记忆，返回 WorkingMemory 实例。
        
        如果记忆文件不存在或解析失败，返回一个空白的新实例。
        """
        wm = cls()
        path = Path(cls.SESSION_MEMORY_PATH)
        if path.exists():
            try:
                text = path.read_text(encoding='utf-8')
                wm._restore_from_text(text)
            except Exception as e:
                print(f'[memory] restore_from_memory 解析失败: {e}')
        return wm
