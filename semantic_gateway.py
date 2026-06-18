"""零 · Semantic Gateway
========================
L1 硬阻断 → L2 标准化映射 → L3 软约束。

所有 message 进入 LLM 前必须通过此网关。
职责：语义不可被污染，角色不可被滥用。
"""

from __future__ import annotations

from config import get_logger

logger = get_logger('zero.gateway')

# ═══════════════════════════════════════════
# L1: Hard Validator — 违规则拒绝，绝不通融
# ═══════════════════════════════════════════

VALID_ROLES = {'system', 'user', 'assistant', 'tool'}

# 工具输出伪装成 user 的典型特征（裸文本，无结构化标记包裹）
_TOOL_SMELL_PREFIXES = (
    '工具 ',           # "工具 read_file 返回: ..."
    '[工具结果',       # "[工具结果 read_file]\n..."
    'Tool ',           # "Tool read_file returned: ..."
)

# 合法的工具结果包装前缀（user role 下允许）
_TOOL_WRAPPER_PREFIX = '[tool:'

# system 被对话污染的典型特征
_CONVERSATION_SMELLS = (
    '[用户]:',         # 拍平残留
    '[零]:',           # 拍平残留
    '[assistant]:',    # 拍平残留
)


class ProtocolViolation(ValueError):
    """L1 语义协议违规——消息被拒绝进入模型。"""

    def __init__(self, index: int, role: str, reason: str):
        self.index = index
        self.role = role
        self.reason = reason
        super().__init__(f'msg[{index}] role={role}: {reason}')


def validate(messages: list[dict]) -> list[dict]:
    """L1: 硬阻断。不合规的消息直接抛 ProtocolViolation。

    检查项:
      V1 — role 必须是标准四类之一
      V2 — user role 不得包含工具输出
      V3 — system role 不得包含对话历史
    """
    for i, msg in enumerate(messages):
        role = msg.get('role', '')
        content = str(msg.get('content', ''))

        # ── V1: 标准 role 检查 ──
        if role not in VALID_ROLES:
            _last_violation = f'非标准role: {role}'
            raise ProtocolViolation(i, role,
                                    f'非标准role，合法值: {VALID_ROLES}')

        # ── V2: user role 工具污染检查 ──
        if role == 'user':
            stripped = content.lstrip()
            # 白名单：用 [tool:name]...[/tool] 包裹的合法工具结果
            if stripped.startswith(_TOOL_WRAPPER_PREFIX):
                continue
            for prefix in _TOOL_SMELL_PREFIXES:
                if stripped.startswith(prefix):
                    _last_violation = f'user消息包含裸工具输出: {prefix}'
                    raise ProtocolViolation(
                        i, role,
                        f'user消息包含裸工具输出（前缀"{prefix}"），'
                        f'请用 [tool:name]...[/tool] 包裹或使用 tool role',
                    )

        # ── V3: system role 对话污染检查 ──
        if role == 'system':
            for smell in _CONVERSATION_SMELLS:
                if smell in content:
                    _last_violation = f'system消息包含对话标记: {smell}'
                    raise ProtocolViolation(
                        i, role,
                        f'system消息包含对话历史标记"{smell}"，'
                        f'对话内容应在 user/assistant role 中',
                    )
    return messages


# ═══════════════════════════════════════════
# L2: Canonical Mapper — 标准化语义表达
# ═══════════════════════════════════════════

# 非标准 → 标准 role 映射表
_ROLE_MAP = {
    'zero': 'assistant',
    'executor': 'assistant',
    'llm_output': 'assistant',
    'human': 'user',
}


def canonicalize(messages: list[dict]) -> list[dict]:
    """L2: 标准化映射。不改语义，只统一表达方式。

    映射:
      M1 — 非标准 role → 标准 role
      M2 — 工具结果有结构化标记时保留为 user（兼容尚未支持 tool role 的模型）
    """
    result = []
    for msg in messages:
        role = msg.get('role', 'user')
        content = str(msg.get('content', ''))

        # ── M1: role 标准化 ──
        if role in _ROLE_MAP:
            old = role
            role = _ROLE_MAP[role]
            logger.debug('L2 role map: %s → %s', old, role)

        # ── M2: 工具结果有标记 → 保持 user，依赖 L1 已确保有标记 ──
        # （当后端不支持 tool role 时，带标记的 user 是合法降级）

        result.append({'role': role, 'content': content})
    return result


# ═══════════════════════════════════════════
# L3: Soft Discipline — 优化行为，不阻断
# ═══════════════════════════════════════════

def discipline(messages: list[dict]) -> list[dict]:
    """L3: 软约束。优化但不阻断。

    检查:
      D1 — system 消息是否明显缺身份声明
      D2 — 连续多条同 role 消息（可能丢失交替结构）
    """
    for i, msg in enumerate(messages):
        role = msg.get('role', '')
        content = str(msg.get('content', ''))

        # ── D1: system 缺关键信息（仅警告） ──
        if role == 'system' and len(content) < 20:
            logger.debug('L3: msg[%d] system 过短(%d chars)，可能缺上下文',
                         i, len(content))

    # ── D2: 连续同 role 检测（仅警告） ──
    prev_role = None
    streak = 0
    for i, msg in enumerate(messages):
        role = msg.get('role', '')
        if role == prev_role and role in ('user', 'assistant'):
            streak += 1
            if streak >= 3:
                logger.debug('L3: msg[%d] 连续%d条同role=%s，可能丢失交替结构',
                             i, streak, role)
        else:
            streak = 0
        prev_role = role

    return messages


# ═══════════════════════════════════════════
# 网关入口 — 三层流水线
# ═══════════════════════════════════════════

def process(messages: list[dict], *, strict: bool = True) -> list[dict]:
    """语义网关入口。所有进入 LLM 的消息必须通过此函数。

    Args:
        messages: 原始消息列表 [{role, content}, ...]
        strict: True=L1硬阻断, False=L1降级为警告（调试用）

    Returns:
        经过 L1→L2→L3 处理后的消息列表

    Raises:
        ProtocolViolation: strict=True 且消息不合规时
    """
    try:
        messages = validate(messages)
    except ProtocolViolation:
        if strict:
            raise
        logger.warning('L1 violation (non-strict mode, continuing): %s',
                       _current_violation())

    messages = canonicalize(messages)
    messages = discipline(messages)
    return messages


# ── 内部：记录最近一次违规供调试 ──

_last_violation: str | None = None


def _current_violation() -> str:
    return _last_violation or 'unknown'
