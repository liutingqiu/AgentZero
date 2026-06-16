"""零 · Behavior Canonicalizer v2
==================================
Phase 4.1: Control Theory 架构成 — 动态控制系统，非固定规则系统。

核心变化:
  1. ControlStrength 替代固定 Profile（任务→控制强度，非任务→模板）
  2. AgentResidual 保留 Agent 差异（不抹平个性）
  3. TemperaturePolicy（温度是策略输出，不是固定参数）
  4. SchemaMode（strict/soft/free 三级，非二值）
  5. DualPath（确定性/探索性双路径）
  6. AntiCollapse 反馈（重试反馈指出语义问题，不强化模板）
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable

from config import get_logger

logger = get_logger('zero.behavior')


# ═══════════════════════════════════════════
# SchemaMode: 三级输出约束
# ═══════════════════════════════════════════

class SchemaMode(Enum):
    STRICT = 'strict'   # 强制校验，不合规重试
    SOFT = 'soft'       # 校验但仅警告，不重试
    FREE = 'free'       # 不校验


# ═══════════════════════════════════════════
# AgentResidual: 保留 Agent 个性差异
# ═══════════════════════════════════════════

@dataclass
class AgentResidual:
    """Agent 风格残差——叠加到标准化 system prompt 上，保留个性。"""
    agent_id: str
    style_hint: str         # 注入 system prompt 的风格提示
    code_density: float     # 代码密度偏好 0~1
    verbosity: float        # 详细程度 0~1
    structure_preference: str  # 'structured' | 'natural' | 'concise'


# 预定义 Agent 残差
AGENT_RESIDUALS: dict[str, AgentResidual] = {
    'reasonix': AgentResidual(
        agent_id='reasonix',
        style_hint='你偏好简洁直接的表达。代码紧凑、少注释、高信息密度。用最少的字说最清楚的事。',
        code_density=0.9,
        verbosity=0.3,
        structure_preference='concise',
    ),
    'agnes_text': AgentResidual(
        agent_id='agnes_text',
        style_hint='你偏好高效轻量的表达。快速给结论，不展开不必要细节。适合日常对话和快速任务。',
        code_density=0.5,
        verbosity=0.4,
        structure_preference='natural',
    ),
    'gpt4o': AgentResidual(
        agent_id='gpt4o',
        style_hint='你偏好结构化清晰的表达。分步解释、标注依据、给出多种方案对比。',
        code_density=0.7,
        verbosity=0.8,
        structure_preference='structured',
    ),
    # 默认回退
    '_default': AgentResidual(
        agent_id='_default',
        style_hint='',
        code_density=0.5,
        verbosity=0.5,
        structure_preference='natural',
    ),
}


def get_agent_residual(agent_id: str) -> AgentResidual:
    """获取 Agent 风格残差。"""
    return AGENT_RESIDUALS.get(agent_id, AGENT_RESIDUALS['_default'])


# ═══════════════════════════════════════════
# ControlStrength: 动态控制强度（核心）
# ═══════════════════════════════════════════

# 任务类型 → 基础控制强度
_TASK_BASE_STRENGTH: dict[str, float] = {
    'code': 0.85,
    'planning': 0.70,
    'analysis': 0.50,
    'chat': 0.20,
}



class ExternalAnchorGate:
    """外部锚点门控——检测信号来源，防止纯内部闭环。

    规则: 连续 N 次无外部信号 → 置信度降权 ×0.6
    """

    def __init__(self, window: int = 20):
        self._window = window
        self._signal_log: list[bool] = []  # True=外部信号, False=纯内部

    def record(self, has_external: bool):
        self._signal_log.append(has_external)
        if len(self._signal_log) > self._window:
            self._signal_log = self._signal_log[-self._window:]

    def downgrade_factor(self) -> float:
        """返回置信度降权系数 ∈ [0.6, 1.0]。

        全部内部信号 → 0.6；混合 → 线性插值。
        """
        if len(self._signal_log) < 5:
            return 1.0
        external_ratio = sum(self._signal_log) / len(self._signal_log)
        # ratio=0 → 0.6, ratio=1 → 1.0
        return 0.6 + external_ratio * 0.4


_anchor_gate = ExternalAnchorGate()
_anchor_lock = threading.Lock()


def record_signal_source(has_external: bool):
    """记录信号来源。外部信号 = 客观结果/工具执行/系统日志。"""
    with _anchor_lock:
        _anchor_gate.record(has_external)


def get_anchor_penalty() -> float:
    """获取当前外部锚点置信度降权系数。"""
    with _anchor_lock:
        return _anchor_gate.downgrade_factor()


class EntropyInjector:
    """熵注入器——奖励方差过低时注入噪声，防止收敛锁死。"""

    def __init__(self):
        self._recent_rewards: list[float] = []

    def maybe_inject(self, reward: float, window: int = 15,
                     epsilon: float = 0.05) -> float:
        """如果近期奖励方差过低，注入 ±epsilon 噪声。"""
        import random as _rnd
        self._recent_rewards.append(reward)
        if len(self._recent_rewards) > window:
            self._recent_rewards = self._recent_rewards[-window:]
        if len(self._recent_rewards) < window:
            return reward

        mean = sum(self._recent_rewards) / len(self._recent_rewards)
        variance = sum((r - mean) ** 2 for r in self._recent_rewards) / len(self._recent_rewards)
        if variance < 0.001:  # 方差极低 → 注入噪声
            noise = _rnd.uniform(-epsilon, epsilon)
            return max(0.0, min(1.0, reward + noise))
        return reward


_entropy = EntropyInjector()


def inject_entropy(reward: float) -> float:
    return _entropy.maybe_inject(reward)


# ═══════════════════════════════════════════
# Phase 9: External Grounding & Reality Alignment
# ═══════════════════════════════════════════


class ExternalSignalGateway:
    """外部信号网关——收集非 LLM 来源的评估信号。

    来源: 工具执行结果 / API 返回码 / 系统日志 / 用户行为。
    """

    def __init__(self):
        self._signals: dict[str, list[tuple[float, str]]] = defaultdict(list)
        # { task_type: [(score, source), ...] }
        self._lock = threading.Lock()

    def ingest(self, task_type: str, score: float, source: str):
        """摄入外部信号。source 示例: 'tool_exec', 'api_result', 'system_log'。"""
        with self._lock:
            self._signals[task_type].append((score, source))
            if len(self._signals[task_type]) > 100:
                self._signals[task_type] = self._signals[task_type][-100:]

    def get_external_score(self, task_type: str) -> float | None:
        """获取 task_type 的加权外部评分。无外部信号 → None。"""
        with self._lock:
            signals = self._signals.get(task_type, [])
            if not signals:
                return None
            # 近期权重更高（指数衰减）
            scores = [s for s, _ in signals[-20:]]
            return sum(scores) / len(scores)

    def has_external(self, task_type: str) -> bool:
        with self._lock:
            return len(self._signals.get(task_type, [])) > 0


_gateway = ExternalSignalGateway()
_gateway_lock = threading.Lock()


def ingest_external(task_type: str, score: float, source: str = 'tool_exec'):
    """Phase 9: 摄入外部信号。"""
    with _gateway_lock:
        _gateway.ingest(task_type, score, source)


def get_external_score(task_type: str) -> float | None:
    with _gateway_lock:
        return _gateway.get_external_score(task_type)


# ── Reality Consistency Check ──

def reality_check(
    internal_score: float,
    task_type: str,
) -> tuple[float, bool]:
    """Phase 9: 现实一致性校验。

    内部评分 vs 外部信号 → 偏差过大则降权并标记。
    """
    external = get_external_score(task_type)
    if external is None:
        return internal_score, False  # 无外部信号，无法校验

    drift = abs(internal_score - external)
    if drift < 0.2:
        return internal_score, False  # 一致，正常
    elif drift < 0.4:
        # 中等偏差 → 混合
        blended = internal_score * 0.4 + external * 0.6
        record_signal_source(True)
        return blended, True
    else:
        # 严重偏差 → 以外部为准
        record_signal_source(True)
        return external, True


# ── Drift Aligner ──

def drift_align(control_strength: float, task_type: str) -> float:
    """Phase 9: 漂移对齐——内部模型偏离现实时调整控制强度。

    外部信号持续低于内部预期 → 提高控制（更保守）。
    """
    external = get_external_score(task_type)
    if external is None:
        return control_strength

    # 最近是否有外部信号持续偏低的趋势
    drift_signal = 0.0
    with _gateway_lock:
        recent = _gateway._signals.get(task_type, [])[-10:]
        if len(recent) >= 3:
            avg_external = sum(s for s, _ in recent) / len(recent)
            if avg_external < 0.4:  # 外部信号持续差
                drift_signal = 0.1  # 提高控制
            elif avg_external > 0.8:  # 外部信号持续好
                drift_signal = -0.05  # 稍微放松

    return max(0.05, min(0.95, control_strength + drift_signal))


# ═══════════════════════════════════════════
# Phase 9 升级版 auto_ground
# ═══════════════════════════════════════════

def auto_ground_v3(
    output: str,
    task_type: str,
    agent_id: str,
    control_strength: float = 0.5,
    *,
    llm_caller=None,
    objective_score: float | None = None,
) -> float:
    """Phase 9: 完整锚定——合成评估 + 外部信号 + 现实校验 + 熵注入。

    与 v2 的区别:
      - 外部信号参与评分
      - 现实一致性校验
      - 熵注入防锁死
      - 外部锚点门控
    """
    # ── 1. 内部评分 ──
    rule_score, rule_conf = synthetic_evaluate(output, task_type, control_strength)
    internal_score = rule_score
    if rule_conf < 0.7 and llm_caller:
        try:
            ls = _llm_evaluate(output, task_type, llm_caller)
            internal_score = rule_score * 0.5 + ls * 0.5
        except Exception:
            pass

    # ── 2. 外部信号检入 ──
    external = get_external_score(task_type)
    has_external = external is not None
    record_signal_source(has_external or (objective_score is not None and objective_score >= 0))

    # ── 3. 现实一致性校验 ──
    if has_external:
        internal_score, _ = reality_check(internal_score, task_type)

    # ── 4. 融合: 内部 + 客观 ──
    if objective_score is not None and objective_score >= 0:
        final_score = internal_score * 0.4 + objective_score * 0.6
    elif has_external:
        final_score = internal_score * 0.5 + external * 0.5
    else:
        final_score = internal_score

    # ── 5. 熵注入 ──
    final_score = inject_entropy(final_score)

    # ── 6. 外部锚点门控 ──
    anchor_penalty = get_anchor_penalty()
    effective_conf = rule_conf * anchor_penalty

    # ── 7. 写入 ──
    if effective_conf >= 0.5:
        record_objective(task_type, agent_id, final_score)
    if has_external:
        record_signal_source(True)

    logger.debug(
        'auto_ground_v3: type=%s internal=%.2f external=%s final=%.2f '
        'anchor=%.2f entropy=✓',
        task_type, internal_score,
        f'{external:.2f}' if external else 'None',
        final_score, anchor_penalty,
    )
    return final_score

