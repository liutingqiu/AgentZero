r"""零 · JSON 解析工具

解决：LLM 返回 JSON + 自然语言混合时，用括号计数法提取第一段完整 JSON，
避免贪婪正则把多段 JSON 一起吞掉。

用法：
    from utils.json_helpers import extract_first_json
    obj = extract_first_json(llm_reply)  # dict or None
"""

import json
import re


def extract_first_json(text):
    """从任意文本中提取第一段完整 JSON（对象或数组）。

    采用括号深度计数器；正确处理字符串、转义字符。
    返回解析后的 dict/list，或 None（找不到/解析失败）。
    """
    if not text:
        return None

    # 找到第一个 '{' 或 '['
    obj_start = text.find('{')
    arr_start = text.find('[')
    if obj_start == -1 and arr_start == -1:
        return None
    start_idx = min(
        x for x in (obj_start, arr_start) if x >= 0
    )

    opener = text[start_idx]
    closer = '}' if opener == '{' else ']'
    depth = 0
    in_str = False
    escape = False

    for i in range(start_idx, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                candidate = text[start_idx:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # 继续寻找（可能有多个片段）
                    return _fallback_regex(text)
    return None


def _fallback_regex(text):
    """兜底：用非贪婪正则提取第一段花括号 JSON。"""
    for m in re.finditer(r'\{[^{}]*\}', text):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def extract_all_json(text):
    """提取文本中的所有 JSON 段，返回 list。"""
    results = []
    pos = 0
    while True:
        obj_start = text.find('{', pos)
        arr_start = text.find('[', pos)
        if obj_start == -1 and arr_start == -1:
            break
        start_idx = min(x for x in (obj_start, arr_start) if x >= 0)
        opener = text[start_idx]
        closer = '}' if opener == '{' else ']'
        depth = 0
        in_str = False
        escape = False
        found_end = -1
        for i in range(start_idx, len(text)):
            ch = text[i]
            if in_str:
                if escape: escape = False
                elif ch == '\\': escape = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == opener: depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    found_end = i + 1
                    break
        if found_end == -1:
            break
        try:
            results.append(json.loads(text[start_idx:found_end]))
        except json.JSONDecodeError:
            pass
        pos = found_end
    return results
