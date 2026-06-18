"""零 · 意图引擎
================
事件/消息 → 意图分类。决定零该怎么响应。

分类策略:
  - 同类型+同上下文事件 → 缓存复用（5分钟 TTL）
  - 缓存未命中 → LLM 轻量分类（1 token）
  - 低置信度 → 降级为被动模式

意图类型:
  passive_chat    — 纯聊天，LLM 直接回复
  passive_action  — 需要工具，走 AgentLoop
  self_maintain   — 系统自维护，静默执行
"""

import time, json, hashlib
from datetime import datetime


# ── 意图缓存 ──
_cache = {}  # {hash: (intent, confidence, timestamp)}

CACHE_TTL = 300  # 5 分钟


def _cache_key(text, context=''):
    """生成缓存键（文本+上下文的哈希）
    v2: 扩展到100字符（GPT-4o: 50字符太短，高相似度输入会冲突）
    """
    return hashlib.sha256(f'{text[:100]}:{context[:100]}'.encode()).hexdigest()


def _check_cache(text, context=''):
    """检查缓存，命中返回 (intent, confidence) 或 None"""
    key = _cache_key(text, context)
    entry = _cache.get(key)
    if entry:
        intent, confidence, ts = entry
        if time.time() - ts < CACHE_TTL:
            return intent, confidence
        else:
            del _cache[key]
    return None


def _store_cache(text, context, intent, confidence):
    key = _cache_key(text, context)
    _cache[key] = (intent, confidence, time.time())
    # 限制缓存大小
    if len(_cache) > 200:
        oldest = min(_cache, key=lambda k: _cache[k][2])
        del _cache[oldest]


# ── 规则兜底（不调LLM）──

def _rule_classify(text):
    """规则分类——LLM 不可用时的兜底。
    
    只做最明显的判断，其余交给 LLM。
    """
    text_lower = text.lower()
    
    # 明确操作意图
    action_patterns = [
        ['找', '搜索', '搜', '查', '在哪', '哪里', '列出', '显示'],
        ['写', '改', '删', '创建', '安装', '下载', '运行', '执行', '启动'],
        ['爬虫', '状态', '检查', '系统', '磁盘', '内存'],
    ]
    
    # 高风险操作 → 降级为 chat，避免误触发
    danger = ['删除', '格式化', '清空', '卸载', 'rm ', 'sudo']
    if any(kw in text_lower for kw in danger):
        return 'passive_chat', 0.5  # 不确定，等主人明确指令
    
    for group in action_patterns:
        if any(kw in text_lower for kw in group):
            return 'passive_action', 0.6  # v2: 0.7→0.6（GPT-4o: 控制操作风险）
    
    # 明确聊天意图
    chat_patterns = ['你好', '谢谢', '哈哈', '嗯', '哦', '再见', '晚安', '早安', '什么是', '为什么']
    if any(kw in text_lower for kw in chat_patterns):
        return 'passive_chat', 0.8  # v2: 0.9→0.8（GPT-4o: 过于自信）
    
    # 无法判断 → 降级为 chat，不冒险
    return 'passive_chat', 0.2  # v2: 0.4→0.2, action→chat（GPT-4o: 不确定就聊）


# ── LLM 分类 ──

def _llm_classify(text, llm_caller):
    """用 LLM 做意图分类。
    
    llm_caller: 函数，签名为 (system_prompt, user_prompt) -> str
    """
    if not llm_caller:
        return _rule_classify(text)
    
    system = """你是意图分类器。分析用户消息，只回复一个词：chat 或 action。

chat  = 纯聊天、问候、闲聊、知识问答
action = 需要查找文件、搜索信息、执行操作、检查状态

只回复 chat 或 action。"""
    
    try:
        result = llm_caller(messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': text},
        ])
        result = result.strip().lower()
        
        if 'action' in result:
            return 'passive_action', 0.85
        elif 'chat' in result:
            return 'passive_chat', 0.85
        else:
            return 'passive_action', 0.5  # 无法解析 → 默认 action
    except Exception:
        return _rule_classify(text)


# ── 主入口 ──

def classify(text, context='', llm_caller=None):
    """分类用户意图。
    
    Args:
        text: 用户消息
        context: 当前上下文（来自工作记忆）
        llm_caller: LLM 调用函数（可选，不传则用规则兜底）
    
    Returns:
        (intent, confidence)
        intent: 'passive_chat' | 'passive_action' | 'self_maintain'
        confidence: 0.0 ~ 1.0
    """
    # 1. 检查缓存
    cached = _check_cache(text, context)
    if cached:
        return cached
    
    # 2. LLM 分类
    intent, confidence = _llm_classify(text, llm_caller)
    
    # 3. 低置信度 → 降级
    if confidence < 0.5:
        intent = 'passive_chat'  # 不确定就聊天，避免乱动工具
        confidence = 0.3
    
    # 4. 存缓存
    _store_cache(text, context, intent, confidence)
    
    return intent, confidence
