"""零 · 文本截断工具

统一 truncate 策略，避免不同文件用不同长度/方式的截断。
"""


def truncate(text, max_chars, suffix='…'):
    """按字符数截断（不按 token，够用且零依赖）。

    - 总是保留 UTF-8 多字节字符的完整性
    - 截断后追加 suffix（默认 '…'），除非文本本身就很短
    """
    if not text:
        return ''
    if len(text) <= max_chars:
        return text
    if max_chars <= len(suffix):
        return text[:max_chars]
    return text[:max_chars - len(suffix)] + suffix


def truncate_by_words(text, max_tokens, suffix='…'):
    """按"近似 token"数截断——每 4 个字符算 1 token。

    没有 tiktoken 依赖，离线可用，误差在 10-20% 内。
    """
    if not text:
        return ''
    approx_limit = max_tokens * 4
    return truncate(text, approx_limit, suffix)


def strip_ansi(text):
    """去掉 ANSI 控制字符（防止 shell 工具输出污染 LLM）。"""
    import re
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text or '')
