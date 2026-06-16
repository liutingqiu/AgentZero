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


def compute_control_strength(
    task_type: str,
    task_text: str = '',
    context_uncertainty: float = 0.0,   # 0=明确, 1=高度不确定
    user_intent_clarity: float = 1.0,   # 0=模糊, 1=非常清晰
) -> float:
    """计算控制强度 ∈ [0.0, 1.0]。

    control_strength 决定: temperature / schema_mode / path / retry 策略。

    公式:
      base = _TASK_BASE_STRENGTH[task_type]
      adjusted = base - (context_uncertainty * 0.3) + ((1.0 - user_intent_clarity) * -0.2)
      final = clamp(adjusted, 0.05, 0.95)
    """
    base = _TASK_BASE_STRENGTH.get(task_type, 0.3)

    # 上下文不确定 → 降低控制（允许探索）
    uncertainty_penalty = context_uncertainty * 0.3

    # 意图模糊 → 降低控制（不强行按模板）
    clarity_bonus = (user_intent_clarity - 0.5) * 0.4

    strength = base - uncertainty_penalty + clarity_bonus
    return max(0.05, min(0.95, strength))


def estimate_uncertainty(task_text: str) -> float:
    """从任务文本估算不确定性。

    短文本 / 模糊关键词 → 高不确定性。
    长文本 / 明确动作词 → 低不确定性。
    """
    if not task_text or len(task_text) < 10:
        return 0.8

    # 明确动作词降低不确定性
    clear_signals = ['写', '生成', '创建', '修复', '删除', '列出', '搜索',
                     '运行', '执行', '分析', '检查', 'def ', 'class ',
                     '```', '代码', '实现']
    clarity_hits = sum(1 for sig in clear_signals if sig in task_text)

    # 模糊词增加不确定性
    vague_signals = ['可能', '也许', '或者', '不知道', '看看', '试试',
                     '随便', '怎么', '为什么', '能不能']
    vagueness = sum(1 for sig in vague_signals if sig in task_text)

    base = 0.5
    base -= clarity_hits * 0.1
    base += vagueness * 0.15
    return max(0.0, min(1.0, base))


# ═══════════════════════════════════════════
# TemperaturePolicy: 温度是策略输出
# ═══════════════════════════════════════════

@dataclass
class TempPolicy:
    """温度策略——不是固定值，是范围。"""
    min_temp: float
    max_temp: float
    mode: str  # 'sample' | 'fixed_low' | 'fixed_high'

    def sample(self, control_strength: float, prefer_explore: bool = False) -> float:
        """根据控制强度和探索偏好采样温度。"""
        if self.mode == 'fixed_low':
            return self.min_temp
        if self.mode == 'fixed_high':
            return self.max_temp
        # sample 模式：高控制→低温端，探索→高温端
        if prefer_explore:
            return self.min_temp + (self.max_temp - self.min_temp) * (1.0 - control_strength * 0.3)
        return self.min_temp + (self.max_temp - self.min_temp) * (1.0 - control_strength)


def temperature_policy(control_strength: float) -> TempPolicy:
    """从控制强度推导温度策略。

    高控制(≥0.7) → 低温窄范围  [0.0, 0.2]
    中控制(0.3~0.7) → 中温      [0.2, 0.5]
    低控制(<0.3) → 高温宽范围   [0.5, 0.9]
    """
    if control_strength >= 0.7:
        return TempPolicy(min_temp=0.0, max_temp=0.2, mode='sample')
    elif control_strength >= 0.3:
        return TempPolicy(min_temp=0.2, max_temp=0.5, mode='sample')
    else:
        return TempPolicy(min_temp=0.5, max_temp=0.85, mode='sample')


# ═══════════════════════════════════════════
# SchemaMode + Output Validator
# ═══════════════════════════════════════════

def schema_mode(control_strength: float, task_type: str) -> SchemaMode:
    """从控制强度推导 schema 模式。

    strict(≥0.7): 代码类高确定性任务
    soft(0.3~0.7): 分析类
    free(<0.3): 聊天/创意
    """
    if task_type in ('code', 'planning') and control_strength >= 0.6:
        return SchemaMode.STRICT
    if control_strength >= 0.3:
        return SchemaMode.SOFT
    return SchemaMode.FREE


def validate_output(
    output: str,
    control_strength: float,
    task_type: str,
    mode: SchemaMode | None = None,
) -> tuple[bool, list[str]]:
    """验证输出。根据 schema_mode 决定行为。

    strict → 不合规 = False（触发重试）
    soft → 不合规 = True（仅记录 issues）
    free → 永远 True（不校验）
    """
    if mode is None:
        mode = schema_mode(control_strength, task_type)

    if mode == SchemaMode.FREE:
        return True, []

    issues: list[str] = []

    # 代码类检查
    if task_type == 'code':
        if '```' not in output and control_strength >= 0.5:
            issues.append('缺少代码块标记(```)')

    # 规划类检查
    if task_type == 'planning':
        if not re.search(r'[-*•]\s', output) and control_strength >= 0.5:
            issues.append('缺少子任务列表(- 或 * 开头)')

    # 分析类检查
    if task_type == 'analysis':
        if len(output.strip()) < 30:
            issues.append('分析结果过短(<30字符)')

    # soft 模式：有 issues 也通过，只记录
    passed = (mode == SchemaMode.SOFT) or len(issues) == 0
    return passed, issues


# ═══════════════════════════════════════════
# Task Classification
# ═══════════════════════════════════════════

def classify(text: str) -> str:
    """分类任务文本 → task_type。"""
    if not text or not text.strip():
        return 'chat'
    text_lower = text.lower()

    # 强聊天信号
    chat_sigs = ['你好', '谢谢', '哈哈', '嗯', '哦', '再见', '晚安', '早安',
                 '在吗', '怎么样', '天气', '今天', '累', '开心']
    if any(sig in text_lower for sig in chat_sigs):
        return 'chat'

    # 代码信号
    code_kw = ['写', '生成', '创建', '实现', '编写', '代码', '函数', '类',
               'html', 'css', 'js', 'python', '脚本', '修复', 'debug',
               'def ', 'class ', 'import ', '```', '重构']
    # 规划信号
    plan_kw = ['计划', '规划', '步骤', '流程', '方案', '拆解', '设计架构',
               '技术选型', '如何实现', '怎么做', '分几步']
    # 分析信号
    analysis_kw = ['分析', '审查', '检查', '评估', '对比', '为什么', '原因',
                   'review', 'audit', '解释', '区别', '优缺点', '是否']

    scores = {
        'code': sum(1 for kw in code_kw if kw in text_lower),
        'planning': sum(1 for kw in plan_kw if kw in text_lower),
        'analysis': sum(1 for kw in analysis_kw if kw in text_lower),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'chat'


# ═══════════════════════════════════════════
# Behavior Seed
# ═══════════════════════════════════════════

def seed(task_type: str, input_text: str, extra: str = '') -> str:
    """确定性种子。相同(类型+输入) → 相同种子。"""
    material = f'{task_type}:{input_text[:200]}:{extra}'
    return hashlib.sha256(material.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════
# System Prompt Builder
# ═══════════════════════════════════════════

def build_system(
    identity: str = '你是零，主人的智能助手。',
    agent_id: str = '',
    control_strength: float = 0.5,
    task_type: str = 'chat',
    extra_rules: str = '',
) -> str:
    """构建 system prompt：规范基础 + Agent 残差叠加。

    不再使用固定 profile 模板。基于 control_strength 调节语气。
    """
    now = datetime.now()
    weekday_cn = ['一', '二', '三', '四', '五', '六', '日'][now.weekday()]
    hour = now.hour
    period = ('凌晨' if hour < 6 else '早上' if hour < 9
              else '上午' if hour < 12 else '下午' if hour < 18 else '晚上')
    time_ctx = f'当前时间: {now.month}/{now.day} 周{weekday_cn} {period}'

    # ── 基础身份 + 时间 ──
    parts = [identity, time_ctx]

    # ── 控制强度驱动的行为提示 ──
    if control_strength >= 0.7:
        parts.append('本次任务需要高确定性输出。严格按需求执行，不添加未要求的内容。')
    elif control_strength >= 0.3:
        parts.append('本次任务可适度发挥。给出清晰结论，允许简要展开。')
    else:
        parts.append('本次任务可自由对话。自然回应，不需要严格格式。')

    # ── 任务类型提示 ──
    type_hints = {
        'code': '生成代码时：完整可运行，用```包裹，标注语言。',
        'planning': '输出规划时：用缩进列表表示步骤和依赖关系。不执行步骤。',
        'analysis': '分析时：逐项核对事实，不确定处标注"待确认"。',
    }
    if task_type in type_hints:
        parts.append(type_hints[task_type])

    # ── Agent 残差注入（保留个性差异）──
    if agent_id:
        residual = get_agent_residual(agent_id)
        if residual.style_hint:
            parts.append(residual.style_hint)

    # ── 额外规则 ──
    if extra_rules:
        parts.append(extra_rules)

    return '\n\n'.join(parts)


# ═══════════════════════════════════════════
# Anti-Collapse Feedback（重试时不强化模板）
# ═══════════════════════════════════════════

def retry_feedback(issues: list[str], attempt: int) -> str:
    """生成反坍缩重试反馈。

    不说"严格按格式输出"——而是指出语义问题，允许换路径。
    """
    if attempt == 1:
        return (
            f'上次输出有这些可以改进的地方: {"; ".join(issues)}。'
            f'不需要完全按模板来，换一种方式重新表达核心内容即可。'
        )
    else:
        return (
            f'还是不太对: {"; ".join(issues)}。'
            f'试试完全换一个角度或结构。重点是把内容说清楚，格式是次要的。'
        )


# ═══════════════════════════════════════════
# DualPath: 确定性 / 探索性路径选择
# ═══════════════════════════════════════════

class Path(Enum):
    DETERMINISTIC = 'A'
    EXPLORATORY = 'B'


def select_path(control_strength: float, confidence: float = 0.5) -> Path:
    """选择执行路径。

    Path A (确定性): control_strength ≥ 0.5 或 confidence ≥ 0.7
    Path B (探索性): 低控制 且 低置信度
    """
    if control_strength >= 0.5 or confidence >= 0.7:
        return Path.DETERMINISTIC
    return Path.EXPLORATORY


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

@dataclass
class BehaviorContext:
    """行为上下文——canonicalize 的完整输出。"""
    messages: list[dict]
    control_strength: float       # 校准后的控制强度
    control_raw: float            # 原始计算值（校准前）
    task_type: str
    temp_policy: TempPolicy
    schema_mode: SchemaMode
    path: Path
    agent_id: str
    behavior_seed: str


def canonicalize(
    messages: list[dict],
    task_text: str = '',
    task_type: str | None = None,
    agent_id: str = '',
    agent_identity: str = '你是零，主人的智能助手。',
    extra_rules: str = '',
    confidence: float = 0.5,
) -> BehaviorContext:
    """行为标准化主入口（v2: 控制理论架构）。

    不再选"profile"——而是计算控制强度，推导所有下游参数。

    Returns:
        BehaviorContext: 包含标准化 messages + 所有控制参数
    """
    # 1. 分类
    if task_type is None or task_type not in _TASK_BASE_STRENGTH:
        if task_text:
            task_type = classify(task_text)
        else:
            task_type = 'chat'

    # 2. 计算原始控制强度 → 校准（Phase 4.2: bias + drift 修正）
    uncertainty = estimate_uncertainty(task_text)
    control_raw = compute_control_strength(
        task_type, task_text,
        context_uncertainty=uncertainty,
        user_intent_clarity=1.0 - uncertainty,
    )
    control = calibrated_strength(control_raw, task_type, agent_id)

    # 3. 推导下游参数
    temp_pol = temperature_policy(control)
    sch_mode = schema_mode(control, task_type)
    path = select_path(control, confidence)
    behavior_seed = seed(task_type, task_text)

    # 4. 构建 system prompt
    system_content = build_system(
        identity=agent_identity,
        agent_id=agent_id,
        control_strength=control,
        task_type=task_type,
        extra_rules=extra_rules,
    )
    system_content += f'\n\n[seed:{behavior_seed}]'

    # 5. 替换/插入 system message
    result = []
    system_inserted = False
    for msg in messages:
        if msg.get('role') == 'system':
            result.append({'role': 'system', 'content': system_content})
            system_inserted = True
        else:
            result.append(msg)
    if not system_inserted:
        result.insert(0, {'role': 'system', 'content': system_content})

    logger.debug(
        'canonicalize: type=%s control=%.2f temp=[%.2f,%.2f] schema=%s path=%s agent=%s',
        task_type, control, temp_pol.min_temp, temp_pol.max_temp,
        sch_mode.value, path.value, agent_id or 'default',
    )

    return BehaviorContext(
        messages=result,
        control_strength=control,
        control_raw=control_raw,
        task_type=task_type,
        temp_policy=temp_pol,
        schema_mode=sch_mode,
        path=path,
        agent_id=agent_id,
        behavior_seed=behavior_seed,
    )


# ═══════════════════════════════════════════
# Phase 4.2: Control Calibration Layer
# ═══════════════════════════════════════════
# 控制信号校准：让 control_strength 从"估算"变成"学习"。
#
# 三个机制:
#   1. ControlMemory — 记录每次控制决策+结果
#   2. Bias Correction — 从历史成功率学习偏置
#   3. Drift Correction — 检测系统行为漂移并修正

import json
import os
import threading
import time
from collections import defaultdict


@dataclass
class ControlRecord:
    """一次控制决策记录。"""
    task_type: str
    agent_id: str
    control_raw: float       # 原始计算值
    control_final: float     # 校准后的实际使用值
    success: bool            # 结果是否符合预期
    output_quality: float    # 0~1，自动输出质量评估
    timestamp: float         # time.time()
    feedback: int = 0        # 用户显式反馈: 0=无, +1=好, -1=差
    objective_score: float = -1.0  # Phase 6: 客观结果信号(-1=未评估)


class ControlMemory:
    """控制记忆——记录历史决策，提供校准数据。

    Phase 6 新增（对齐层）:
      1. 客观结果锚点 — code执行成功/plan步骤完成 → 最高权重信号
      2. 权重重平衡 — 客观(3.0x) > 用户反馈(1.5x) > 自动(1.0x)
      3. 耦合阻尼 — 不稳定Agent的bias衰减传播，防止系统级漂移
    """

    MAX_RECORDS = 500
    HALF_LIFE_SECONDS = 7 * 24 * 3600  # 7 天
    # Phase 6: 三信号权重（客观 > 用户 > 自动）
    OBJECTIVE_WEIGHT = 3.0
    FEEDBACK_WEIGHT = 1.5              # 从 3.0 降到 1.5
    AUTO_WEIGHT = 1.0
    COUPLING_FACTOR = 0.3              # 跨Agent基础耦合系数
    COUPLING_MIN_SAMPLES = 5           # 对方Agent最少样本数才参与耦合
    COUPLING_MAX_QUALITY_SPREAD = 0.5  # 对方质量方差过大 → 衰减耦合

    def __init__(self, persist_path: str = ''):
        self._records: list[ControlRecord] = []
        self._lock = threading.Lock()
        self._persist_path = persist_path
        self._load()

    # ── 记录 ──

    def record(
        self,
        task_type: str,
        agent_id: str,
        control_raw: float,
        control_final: float,
        success: bool,
        output_quality: float = 0.5,
    ):
        """记录一次控制决策及其结果。"""
        rec = ControlRecord(
            task_type=task_type,
            agent_id=agent_id,
            control_raw=control_raw,
            control_final=control_final,
            success=success,
            output_quality=output_quality,
            timestamp=time.time(),
        )
        with self._lock:
            self._records.append(rec)
            if len(self._records) > self.MAX_RECORDS:
                self._records = self._records[-self.MAX_RECORDS:]
        self._save()

    def record_feedback(self, task_type: str, agent_id: str,
                        rating: int):
        """Phase 5: 记录用户显式反馈。

        rating: +1 = 好, -1 = 差, 0 = 中性

        反馈写入最近一条匹配 (task_type, agent_id) 的记录。
        如果找不到则创建一条新记录。
        """
        with self._lock:
            # 找最近一条匹配记录
            for r in reversed(self._records):
                if r.task_type == task_type and r.agent_id == agent_id:
                    r.feedback = rating
                    self._save()
                    return
            # 无匹配 → 创建新记录
            rec = ControlRecord(
                task_type=task_type, agent_id=agent_id,
                control_raw=0.5, control_final=0.5,
                success=(rating >= 0), output_quality=(0.8 if rating > 0 else 0.3),
                timestamp=time.time(), feedback=rating,
            )
            self._records.append(rec)
        self._save()

    # ── 时间衰减权重 ──

    def _weight(self, record: ControlRecord, now: float | None = None) -> float:
        """计算记录的时间衰减权重 ∈ (0, 1]。

        w = exp(-age / HALF_LIFE)
        刚发生的记录权重≈1，7天前的≈0.5，14天前的≈0.25
        """
        if now is None:
            now = time.time()
        age = now - record.timestamp
        if age <= 0:
            return 1.0
        import math
        return math.exp(-age / self.HALF_LIFE_SECONDS)

    def record_objective(
        self,
        task_type: str,
        agent_id: str,
        score: float,
    ):
        """Phase 6: 记录客观结果信号。

        score: 0.0~1.0，基于可验证事实:
          - code: 是否运行成功 (0.0=报错, 1.0=通过)
          - plan: 步骤完成率
          - tool: 是否正确调用
          -1.0 = 未评估（跳过）

        写入最近一条匹配记录的 objective_score。
        """
        if score < 0:
            return
        score = max(0.0, min(1.0, score))
        with self._lock:
            for r in reversed(self._records):
                if r.task_type == task_type and r.agent_id == agent_id:
                    r.objective_score = score
                    self._save()
                    return
        self._save()

    def _effective_quality(self, record: ControlRecord) -> float:
        """Phase 6: 三信号加权混合。

        权重: 客观(3.0) > 用户反馈(1.5) > 自动(1.0)

        有客观信号 → 客观为主，用户为辅
        无客观有反馈 → 反馈 + 自动混合
        都无 → 纯自动评分
        """
        total_weight = self.AUTO_WEIGHT
        quality = record.output_quality * self.AUTO_WEIGHT

        # 用户反馈
        if record.feedback != 0:
            feedback_q = 1.0 if record.feedback > 0 else 0.0
            quality += feedback_q * self.FEEDBACK_WEIGHT
            total_weight += self.FEEDBACK_WEIGHT

        # 客观信号（最高权重）
        if record.objective_score >= 0:
            quality += record.objective_score * self.OBJECTIVE_WEIGHT
            total_weight += self.OBJECTIVE_WEIGHT

        return quality / total_weight if total_weight > 0 else 0.5

    # ── 校准查询 ──

    def get_bias(self, task_type: str, agent_id: str = '') -> float:
        """计算偏置修正量 ∈ [-0.2, 0.2]（含时间衰减+跨Agent耦合）。

        正偏置 = 历史成功率低 → 应提高控制强度
        负偏置 = 历史成功率高 → 可降低控制强度
        """
        records = self._filter(task_type, agent_id, limit=50)
        if len(records) < 5:
            return 0.0

        now = time.time()
        # 时间加权成功率
        weighted_success = 0.0
        total_weight = 0.0
        for r in records:
            w = self._weight(r, now)
            weighted_success += (1.0 if r.success else 0.0) * w
            total_weight += w

        if total_weight < 0.01:
            return 0.0
        success_rate = weighted_success / total_weight

        # 基础 bias
        bias = (0.5 - success_rate) * 0.4

        # ── Phase 5: 跨Agent耦合 ──
        # 同 task_type 的其他 Agent 的 bias 以 COUPLING_FACTOR 传播
        if agent_id:
            coupling = self._cross_agent_coupling(task_type, agent_id, now)
            bias = bias * (1 - self.COUPLING_FACTOR) + coupling * self.COUPLING_FACTOR

        return max(-0.2, min(0.2, bias))

    def _cross_agent_coupling(self, task_type: str, exclude_agent: str,
                              now: float) -> float:
        """Phase 6: 跨Agent耦合偏置（含阻尼）。

        阻尼条件:
          - 对方样本不足 → 权重衰减
          - 对方质量方差过大 → 不稳定，权重衰减
          - 对方bias与己方差距过大 → 可能是噪声，衰减
        """
        all_agents = set()
        with self._lock:
            for r in self._records:
                if r.task_type == task_type and r.agent_id != exclude_agent:
                    all_agents.add(r.agent_id)

        if not all_agents:
            return 0.0

        biases_with_damping = []
        for aid in all_agents:
            recs = self._filter(task_type, aid, limit=30)
            n = len(recs)
            if n < self.COUPLING_MIN_SAMPLES:
                continue

            # 计算该Agent的时间加权成功率
            w_succ = 0.0
            w_tot = 0.0
            qualities = []
            for r in recs:
                w = self._weight(r, now)
                w_succ += (1.0 if r.success else 0.0) * w
                w_tot += w
                qualities.append(self._effective_quality(r))
            if w_tot < 0.01:
                continue
            sr = w_succ / w_tot
            raw_bias = (0.5 - sr) * 0.4

            # ── 阻尼计算 ──
            damping = 1.0

            # 阻尼1: 样本不足
            if n < 10:
                damping *= n / 10

            # 阻尼2: 质量方差过大（不稳定Agent）
            if len(qualities) >= 3:
                mean_q = sum(qualities) / len(qualities)
                variance = sum((q - mean_q) ** 2 for q in qualities) / len(qualities)
                if variance > self.COUPLING_MAX_QUALITY_SPREAD:
                    damping *= 0.3  # 高方差 → 大幅衰减

            biases_with_damping.append(raw_bias * damping)

        if not biases_with_damping:
            return 0.0
        return sum(biases_with_damping) / len(biases_with_damping)

    def get_drift(self, task_type: str, agent_id: str = '',
                  window: int = 20) -> float:
        """检测近期漂移 ∈ [-0.1, 0.1]（含时间衰减）。

        近期质量 vs 长期质量 的偏差 = 漂移信号。
        正漂移 = 近期质量下降 → 提高控制
        """
        records = self._filter(task_type, agent_id, limit=100)
        if len(records) < 10:
            return 0.0

        now = time.time()

        # 长期加权平均质量
        long_q = 0.0
        long_w = 0.0
        for r in records:
            w = self._weight(r, now)
            long_q += self._effective_quality(r) * w
            long_w += w
        long_term_quality = long_q / long_w if long_w > 0.01 else 0.5

        # 近期加权平均质量
        recent = records[-window:]
        recent_q = 0.0
        recent_w = 0.0
        for r in recent:
            w = self._weight(r, now)
            recent_q += self._effective_quality(r) * w
            recent_w += w
        recent_quality = recent_q / recent_w if recent_w > 0.01 else 0.5

        drift = (long_term_quality - recent_quality) * 0.2  # [-0.1, 0.1]
        return max(-0.1, min(0.1, drift))

    def get_stats(self, task_type: str = '', agent_id: str = '') -> dict:
        """获取统计摘要。"""
        records = self._filter(task_type, agent_id, limit=200)
        if not records:
            return {'total': 0, 'success_rate': 0, 'avg_quality': 0}

        total = len(records)
        success_rate = sum(1 for r in records if r.success) / total
        avg_quality = sum(r.output_quality for r in records) / total
        avg_control = sum(r.control_final for r in records) / total

        # 按 task_type 分组
        by_type: dict[str, dict] = {}
        for r in records:
            if r.task_type not in by_type:
                by_type[r.task_type] = {'total': 0, 'success': 0, 'quality_sum': 0}
            by_type[r.task_type]['total'] += 1
            if r.success:
                by_type[r.task_type]['success'] += 1
            by_type[r.task_type]['quality_sum'] += r.output_quality

        type_stats = {}
        for t, d in by_type.items():
            type_stats[t] = {
                'total': d['total'],
                'success_rate': round(d['success'] / d['total'], 2),
                'avg_quality': round(d['quality_sum'] / d['total'], 2),
            }

        return {
            'total': total,
            'success_rate': round(success_rate, 2),
            'avg_quality': round(avg_quality, 2),
            'avg_control': round(avg_control, 2),
            'bias': round(self.get_bias(task_type, agent_id), 3),
            'drift': round(self.get_drift(task_type, agent_id), 3),
            'by_type': type_stats,
        }

    # ── 内部 ──

    def _filter(self, task_type: str, agent_id: str,
                limit: int) -> list[ControlRecord]:
        with self._lock:
            records = list(self._records)
        if task_type:
            records = [r for r in records if r.task_type == task_type]
        if agent_id:
            records = [r for r in records if r.agent_id == agent_id]
        return records[-limit:]

    def _save(self):
        if not self._persist_path:
            return
        try:
            data = [
                {
                    'task_type': r.task_type,
                    'agent_id': r.agent_id,
                    'control_raw': r.control_raw,
                    'control_final': r.control_final,
                    'success': r.success,
                    'output_quality': r.output_quality,
                    'timestamp': r.timestamp,
                    'feedback': r.feedback,
                    'objective_score': r.objective_score,
                }
                for r in self._records[-200:]  # 只持久化最近 200 条
            ]
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except (IOError, OSError):
            pass

    def _load(self):
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            with self._lock:
                self._records = [
                    ControlRecord(
                        task_type=d.get('task_type', 'chat'),
                        agent_id=d.get('agent_id', ''),
                        control_raw=d.get('control_raw', 0.5),
                        control_final=d.get('control_final', 0.5),
                        success=d.get('success', True),
                        output_quality=d.get('output_quality', 0.5),
                        timestamp=d.get('timestamp', time.time()),
                        feedback=d.get('feedback', 0),
                        objective_score=d.get('objective_score', -1.0),
                    )
                    for d in data
                ]
        except (json.JSONDecodeError, IOError, KeyError):
            pass


# ── 全局单例 ──

_memory: ControlMemory | None = None
_memory_lock = threading.Lock()


def get_control_memory(persist_path: str = '') -> ControlMemory:
    """获取全局 ControlMemory 单例。"""
    global _memory
    if _memory is None:
        with _memory_lock:
            if _memory is None:
                if not persist_path:
                    from config import DATA_DIR
                    persist_path = os.path.join(DATA_DIR, 'control_memory.json')
                _memory = ControlMemory(persist_path=persist_path)
    return _memory


# ── 校准后的 control_strength ──

def calibrated_strength(
    raw_strength: float,
    task_type: str,
    agent_id: str = '',
) -> float:
    """对原始 control_strength 施加 bias + drift 修正。

    final = clamp(raw + bias + drift, 0.05, 0.95)
    """
    mem = get_control_memory()
    bias = mem.get_bias(task_type, agent_id)
    drift = mem.get_drift(task_type, agent_id)
    adjusted = raw_strength + bias + drift
    calibrated = max(0.05, min(0.95, adjusted))

    if abs(bias) > 0.01 or abs(drift) > 0.01:
        logger.debug(
            'calibrate: raw=%.2f bias=%+.3f drift=%+.3f → final=%.2f (%s/%s)',
            raw_strength, bias, drift, calibrated, task_type, agent_id or 'default',
        )

    return calibrated


def record_outcome(
    task_type: str,
    agent_id: str,
    control_raw: float,
    control_final: float,
    success: bool,
    output_quality: float = 0.5,
):
    """便捷函数：记录一次控制决策的结果。"""
    get_control_memory().record(
        task_type=task_type,
        agent_id=agent_id,
        control_raw=control_raw,
        control_final=control_final,
        success=success,
        output_quality=output_quality,
    )


def record_feedback(task_type: str, agent_id: str, rating: int):
    """Phase 5: 记录用户显式反馈。

    rating: +1 = 好, -1 = 差, 0 = 中性
    """
    get_control_memory().record_feedback(task_type, agent_id, rating)


def record_objective(task_type: str, agent_id: str, score: float):
    """Phase 6: 记录客观结果信号（最高权重）。

    score: 0.0~1.0，基于可验证事实:
      - code: 运行结果 (0=报错, 1=通过)
      - plan: 步骤完成率
      - tool: 调用正确性

    调用示例:
      record_objective('code', 'reasonix', 1.0)  # 代码运行成功
      record_objective('code', 'reasonix', 0.0)  # 编译报错
    """
    get_control_memory().record_objective(task_type, agent_id, score)


# ═══════════════════════════════════════════
# Phase 7: Synthetic Grounding Layer
# ═══════════════════════════════════════════
# 合成评估器 — 为无自然 ground truth 的任务生成伪客观信号。
# 规则层覆盖 90% 场景（快速、确定性），复杂场景可扩展 LLM 评估。
#
# 原则:
#   - 确定性：相同输入永远返回相同分数
#   - 透明性：每个分数可追溯到具体规则
#   - 分层：规则层优先，confidence 标注可靠性

import re as _sre


def synthetic_evaluate(
    output: str,
    task_type: str,
    control_strength: float = 0.5,
) -> tuple[float, float]:
    """Phase 7: 合成评估——为任意 task_type 生成 (score, confidence)。

    score: 0.0~1.0
    confidence: 0.0~1.0（该分数的可靠度）

    规则按 task_type 分层:
      code     — 代码结构检查（高置信度）
      analysis — 结构化推理检查（中高置信度）
      planning — 步骤完整性检查（中高置信度）
      chat     — 连贯性检查（中置信度）
    """
    if not output or not output.strip():
        return 0.0, 1.0

    output = output.strip()

    if task_type == 'code':
        return _eval_code(output)
    elif task_type == 'analysis':
        return _eval_analysis(output)
    elif task_type == 'planning':
        return _eval_planning(output)
    else:
        return _eval_chat(output)


def _eval_code(output: str) -> tuple[float, float]:
    """代码输出评估。高置信度——结构特征明确。"""
    score = 0.0
    checks = 0

    # 有代码块
    if '```' in output:
        score += 0.35
    checks += 1

    # 代码块有语言标注
    if _sre.search(r'```\w+', output):
        score += 0.10
    checks += 1

    # 有解释文字（代码块外的内容）
    parts = output.split('```')
    has_explanation = any(len(p.strip()) > 30 for i, p in enumerate(parts) if i % 2 == 0)
    if has_explanation:
        score += 0.15
    checks += 1

    # 不是纯错误信息
    error_patterns = ['traceback', 'error:', 'exception', '错误:', '报错']
    if not any(ep in output.lower() for ep in error_patterns):
        score += 0.15
    checks += 1

    # 输出足够长
    if len(output) > 80:
        score += 0.10
    checks += 1

    # 含函数/类定义或完整结构
    if _sre.search(r'(def |class |function |<html|<div|import )', output):
        score += 0.15
    checks += 1

    return min(score, 1.0), 0.85  # 高置信度


def _eval_analysis(output: str) -> tuple[float, float]:
    """分析输出评估。中高置信度。"""
    score = 0.0

    # 结构化标记
    if _sre.search(r'[-*•#]\s', output):
        score += 0.20

    # 有结论段
    if _sre.search(r'(结论|总结|综上|因此|所以|建议)', output):
        score += 0.20

    # 长度
    if len(output) > 100:
        score += 0.15

    # 证据标记
    evidence_words = ['因为', '根据', '由于', '数据', '显示', '表明', '来源']
    evidence_hits = sum(1 for w in evidence_words if w in output)
    if evidence_hits >= 2:
        score += 0.20
    elif evidence_hits >= 1:
        score += 0.10

    # 不确定处标注
    if '待确认' in output or '不确定' in output or '可能' in output:
        score += 0.10  # 诚实标注是好事

    # 分段结构
    paragraphs = [p for p in output.split('\n\n') if len(p.strip()) > 20]
    if len(paragraphs) >= 2:
        score += 0.15

    return min(score, 1.0), 0.75


def _eval_planning(output: str) -> tuple[float, float]:
    """规划输出评估。中高置信度。"""
    score = 0.0

    # 有列表项
    list_items = _sre.findall(r'^[-*•]\s', output, _sre.MULTILINE)
    if len(list_items) >= 3:
        score += 0.35
    elif len(list_items) >= 1:
        score += 0.15

    # 每项有描述（不只是标题）
    items_with_detail = len(_sre.findall(r'^[-*•]\s.{20,}', output, _sre.MULTILINE))
    if items_with_detail >= 3:
        score += 0.20
    elif items_with_detail >= 1:
        score += 0.10

    # 依赖标记
    if _sre.search(r'(依赖|前置|→|需要先|必须先|之后|然后)', output):
        score += 0.15

    # 验收标准
    if _sre.search(r'(验收|完成标准|成功条件|检查|验证)', output):
        score += 0.15

    # 长度
    if len(output) > 100:
        score += 0.10

    # 有阶段分组
    if _sre.search(r'(阶段|步骤|Phase|Step|第[一二三\d]+步)', output):
        score += 0.05

    return min(score, 1.0), 0.75


def _eval_chat(output: str) -> tuple[float, float]:
    """对话输出评估。中置信度——主观性较强。"""
    score = 0.0

    # 非空且有意义
    if len(output) > 20:
        score += 0.25
    elif len(output) > 5:
        score += 0.10

    # 非单字/单词
    if len(output.split()) >= 3 or len(output) >= 10:
        score += 0.15

    # 自然标点
    if _sre.search(r'[。！？.!?,，]', output):
        score += 0.15

    # 非乱码检测（中日英字符比例合理）
    alpha_chars = len(_sre.findall(r'[a-zA-Z\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', output))
    total_chars = len(output.replace(' ', ''))
    if total_chars > 0 and alpha_chars / total_chars > 0.5:
        score += 0.20

    # 非纯错误/否定回复
    negative_only = ['不知道', '不清楚', '不会', '无法', '错误']
    if not any(output.strip().startswith(w) and len(output) < 30
               for w in negative_only):
        score += 0.15

    # 有实质性内容
    if len(output) > 50:
        score += 0.10

    return min(score, 1.0), 0.55  # 中置信度——对话质量主观性强


def auto_ground(
    output: str,
    task_type: str,
    agent_id: str,
    control_strength: float = 0.5,
    *,
    llm_caller=None,
) -> float:
    """Phase 7: 自动锚定——合成评估 + 可选 LLM 双裁判。

    低置信度(<0.7)时自动启用 LLM judge 作为第二评估器。
    双裁判融合: final = 0.5 * rule_score + 0.5 * llm_score

    Returns:
        unified_score: 0.0~1.0
    """
    rule_score, rule_conf = synthetic_evaluate(output, task_type, control_strength)

    # ── 规则层置信度足够 → 直接使用 ──
    if rule_conf >= 0.7 or llm_caller is None:
        if rule_conf >= 0.5:
            record_objective(task_type, agent_id, rule_score)
        logger.debug('synthetic: type=%s score=%.2f conf=%.2f', task_type, rule_score, rule_conf)
        return rule_score

    # ── 低置信度 → 启用 LLM 双裁判 ──
    try:
        llm_score = _llm_evaluate(output, task_type, llm_caller)
        # 融合: 规则 + LLM 各 50%
        unified = rule_score * 0.5 + llm_score * 0.5
        # 融合后置信度提升
        unified_conf = max(rule_conf, 0.7)
        if unified_conf >= 0.5:
            record_objective(task_type, agent_id, unified)
        logger.debug('dual_judge: type=%s rule=%.2f llm=%.2f → unified=%.2f',
                     task_type, rule_score, llm_score, unified)
        return unified
    except Exception:
        # LLM judge 不可用 → 回退规则评分
        if rule_conf >= 0.5:
            record_objective(task_type, agent_id, rule_score)
        return rule_score


def _llm_evaluate(output: str, task_type: str, llm_caller) -> float:
    """LLM 评估器——用确定性 prompt 做第二裁判。

    使用极简 prompt + 低温度，确保评分稳定。
    """
    judge_prompt = f"""你是输出质量评估器。严格按标准评分，不给主观评价。

任务类型: {task_type}
输出内容:
---
{output[:2000]}
---

评分标准:
- code: 代码完整可运行(0.4) + 有解释(0.3) + 结构清晰(0.3)
- analysis: 逻辑完整(0.4) + 证据充分(0.3) + 结论明确(0.3)
- planning: 步骤清晰(0.4) + 依赖明确(0.3) + 可执行(0.3)
- chat: 自然流畅(0.5) + 信息完整(0.5)

只回复一个 0.0~1.0 的数字，不要其他内容。"""

    try:
        reply = llm_caller(messages=[
            {'role': 'system', 'content': '你是客观评估器。只输出0.0~1.0的数字。'},
            {'role': 'user', 'content': judge_prompt},
        ], task_type='chat', task_text='', extra_rules='',
           agent_id='_judge', skip_ground=True)
        # 提取数字
        import re as _jre
        match = _jre.search(r'(\d+\.?\d*)', str(reply))
        if match:
            return max(0.0, min(1.0, float(match.group(1))))
    except Exception:
        pass
    return 0.5  # 回退中性分


# ═══════════════════════════════════════════
# Phase 8: Evaluator Calibration Layer
# ═══════════════════════════════════════════
# 让评估系统本身变成可学习系统。
# 解决: evaluator drift / reward hacking / confidence miscalibration
#
# 三个核心:
#   1. JudgeRegistry — 版本锁定 + 权重自动调优
#   2. CalibratedConfidence — 置信度回归校准
#   3. RewardValidator — 刷分检测 + 自适应权重

import math as _math
from collections import defaultdict


# ═══════════════════════════════════════════
# JudgeRegistry — 评估器版本 + 权重管理
# ═══════════════════════════════════════════

@dataclass
class JudgeInfo:
    """评估器元信息。"""
    judge_id: str           # 'rule_v1' | 'llm_gpt' | 'llm_ds'
    version: str            # 'v1.0'
    weight: float = 1.0     # 当前权重
    total_evals: int = 0
    total_error: float = 0.0  # 累积绝对误差
    last_calibrated: float = 0.0


class JudgeRegistry:
    """评估器注册表——跟踪版本、校准权重、检测漂移。"""

    CALIBRATION_INTERVAL = 100  # 每 N 次评估重新校准

    def __init__(self):
        self._judges: dict[str, JudgeInfo] = {}
        self._lock = threading.Lock()

    def register(self, judge_id: str, version: str = 'v1.0'):
        with self._lock:
            if judge_id not in self._judges:
                self._judges[judge_id] = JudgeInfo(
                    judge_id=judge_id, version=version,
                )

    def record_error(self, judge_id: str, predicted: float, actual: float):
        """记录评估器误差。actual 来自客观信号或共识。"""
        with self._lock:
            j = self._judges.get(judge_id)
            if not j:
                return
            error = abs(predicted - actual)
            j.total_evals += 1
            j.total_error += error

            # 定期重新校准权重
            if j.total_evals >= self.CALIBRATION_INTERVAL:
                avg_error = j.total_error / j.total_evals
                # 误差低 → 权重高
                j.weight = max(0.2, min(2.0, 1.0 / max(avg_error, 0.05)))
                j.total_evals = 0
                j.total_error = 0.0
                j.last_calibrated = time.time()
                logger.debug('judge %s recalibrated: weight=%.2f err=%.3f',
                             judge_id, j.weight, avg_error)

    def get_weight(self, judge_id: str) -> float:
        with self._lock:
            j = self._judges.get(judge_id)
            return j.weight if j else 1.0

    def drift_score(self, judge_id: str) -> float:
        """检测评估器漂移 ∈ [0,1]。高值 = 评估不稳定。"""
        with self._lock:
            j = self._judges.get(judge_id)
            if not j or j.total_evals < 10:
                return 0.0
            return min(1.0, j.total_error / j.total_evals)


# ── 全局单例 ──
_judge_registry: JudgeRegistry | None = None
_judge_lock = threading.Lock()


def get_judge_registry() -> JudgeRegistry:
    global _judge_registry
    if _judge_registry is None:
        with _judge_lock:
            if _judge_registry is None:
                _judge_registry = JudgeRegistry()
                _judge_registry.register('rule_v1', 'v1.0')
                _judge_registry.register('llm_ds', 'v1.0')
    return _judge_registry


# ═══════════════════════════════════════════
# CalibratedConfidence — 置信度回归
# ═══════════════════════════════════════════

class CalibratedConfidence:
    """置信度校准器——从历史数据学习 actual_accuracy(confidence)。

    分桶统计: bin(conf) → actual_correct_rate
    """

    BINS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    def __init__(self):
        self._bins: dict[str, list[float]] = defaultdict(list)
        # { '0.5-0.6': [correct_rates...], ... }

    def record(self, confidence: float, was_correct: bool):
        """记录一次评估: 预测置信度 + 实际是否正确。"""
        bin_key = self._bin_key(confidence)
        self._bins[bin_key].append(1.0 if was_correct else 0.0)
        # 限制 bin 大小
        if len(self._bins[bin_key]) > 200:
            self._bins[bin_key] = self._bins[bin_key][-200:]

    def calibrate(self, raw_confidence: float) -> float:
        """校准置信度: 输入原始值，输出校准值。"""
        bin_key = self._bin_key(raw_confidence)
        rates = self._bins.get(bin_key, [])
        if len(rates) < 5:
            return raw_confidence  # 样本不足，不校准
        actual_rate = sum(rates) / len(rates)
        # 校准: 往实际准确率方向拉
        return raw_confidence * 0.5 + actual_rate * 0.5

    def _bin_key(self, conf: float) -> str:
        for b in self.BINS:
            if conf <= b:
                low = self.BINS[self.BINS.index(b) - 1] if self.BINS.index(b) > 0 else 0.0
                return f'{low:.1f}-{b:.1f}'
        return '0.9-1.0'

    def is_calibrated(self, confidence: float) -> bool:
        """检查该置信度区间是否已有足够样本。"""
        return len(self._bins.get(self._bin_key(confidence), [])) >= 5


# ── 全局单例 ──
_calibrator: CalibratedConfidence | None = None
_cal_lock = threading.Lock()


def get_calibrator() -> CalibratedConfidence:
    global _calibrator
    if _calibrator is None:
        with _cal_lock:
            if _calibrator is None:
                _calibrator = CalibratedConfidence()
    return _calibrator


# ═══════════════════════════════════════════
# MultiJudge — 多裁判池
# ═══════════════════════════════════════════

def multi_judge(
    output: str,
    task_type: str,
    llm_callers: dict[str, object] | None = None,
) -> tuple[float, float]:
    """Phase 8: 多裁判评分——trimmed mean 排除极端值。

    Args:
        output: LLM 输出文本
        task_type: 任务类型
        llm_callers: {judge_name: callable} 可选 LLM 裁判

    Returns:
        (final_score, confidence)
    """
    registry = get_judge_registry()
    scores: list[tuple[float, float]] = []  # [(score, weight), ...]

    # 1. 规则裁判（始终可用）
    rule_score, rule_conf = synthetic_evaluate(output, task_type, 0.5)
    rule_weight = registry.get_weight('rule_v1')
    scores.append((rule_score, rule_weight))

    # 2. LLM 裁判（如果提供）
    if llm_callers:
        for name, caller in llm_callers.items():
            try:
                ls = _llm_evaluate(output, task_type, caller)
                lw = registry.get_weight('llm_ds')
                scores.append((ls, lw))
            except Exception:
                pass

    if not scores:
        return 0.5, 0.5

    # ── Trimmed mean: 去掉最高和最低分 ──
    if len(scores) >= 3:
        sorted_scores = sorted(scores, key=lambda x: x[0])
        scores = sorted_scores[1:-1]  # 去掉两端

    # 加权平均
    total_w = sum(w for _, w in scores)
    if total_w < 0.01:
        return 0.5, 0.5
    final = sum(s * w for s, w in scores) / total_w

    # 置信度: 加权平均置信度 + 裁判一致性加分
    consensus_bonus = 0.1 if len(scores) >= 2 and max(s for s, _ in scores) - min(s for s, _ in scores) < 0.3 else 0.0
    confidence = min(1.0, rule_conf + consensus_bonus)

    return final, confidence


# ═══════════════════════════════════════════
# RewardValidator — 刷分检测
# ═══════════════════════════════════════════

@dataclass
class RewardValidation:
    """奖励验证结果。"""
    score: float
    is_suspicious: bool
    divergence: float       # 合成 vs 客观的偏差
    action: str             # 'accept' | 'dampen' | 'reject'


def validate_reward(
    synthetic_score: float,
    objective_score: float | None,
    task_type: str,
) -> RewardValidation:
    """Phase 8: 验证合成评分是否可信。

    检测刷分: 合成评分与客观评分偏差过大 → 降权或拒绝。
    """
    # 无客观信号 → 无法验证，直接接受
    if objective_score is None or objective_score < 0:
        return RewardValidation(
            score=synthetic_score,
            is_suspicious=False, divergence=0.0, action='accept',
        )

    divergence = abs(synthetic_score - objective_score)

    # 偏差阈值: chat 更宽容（主观性强），code 更严格
    thresholds = {'code': 0.3, 'planning': 0.35, 'analysis': 0.35, 'chat': 0.5}
    threshold = thresholds.get(task_type, 0.4)

    if divergence < threshold * 0.5:
        # 偏差很小 → 正常接受
        return RewardValidation(
            score=synthetic_score,
            is_suspicious=False, divergence=divergence, action='accept',
        )
    elif divergence < threshold:
        # 中等偏差 → 降权
        dampened = synthetic_score * 0.5 + objective_score * 0.5
        return RewardValidation(
            score=dampened,
            is_suspicious=True, divergence=divergence, action='dampen',
        )
    else:
        # 严重偏差 → 以客观评分为准
        return RewardValidation(
            score=objective_score,
            is_suspicious=True, divergence=divergence, action='reject',
        )


# ═══════════════════════════════════════════
# 升级版 auto_ground (v2)
# ═══════════════════════════════════════════

def auto_ground_v2(
    output: str,
    task_type: str,
    agent_id: str,
    control_strength: float = 0.5,
    *,
    llm_caller=None,
    objective_score: float | None = None,
    llm_callers: dict[str, object] | None = None,
) -> float:
    """Phase 8: 升级版自动锚定——多裁判 + 校准 + 刷分检测。

    流程:
      1. 多裁判评分 (trimmed mean)
      2. 置信度校准
      3. 刷分检测
      4. 记录评估器误差
      5. 写入 ControlMemory
    """
    registry = get_judge_registry()
    calibrator = get_calibrator()

    # ── 1. 多裁判评分 ──
    rule_score, rule_conf = synthetic_evaluate(output, task_type, control_strength)
    if llm_callers:
        score, conf = multi_judge(output, task_type, llm_callers)
    else:
        # 回退单裁判
        score, conf = rule_score, rule_conf
        if rule_conf < 0.7 and llm_caller:
            try:
                ls = _llm_evaluate(output, task_type, llm_caller)
                score = rule_score * 0.5 + ls * 0.5
                conf = max(rule_conf, 0.7)
            except Exception:
                pass

    # ── 2. 置信度校准 ──
    calibrated_conf = calibrator.calibrate(conf)

    # ── 3. 刷分检测 ──
    validation = validate_reward(score, objective_score, task_type)
    final_score = validation.score

    # ── 4. 记录评估器误差（用于后续校准）──
    if objective_score is not None and objective_score >= 0:
        registry.record_error('rule_v1', rule_score, objective_score)
        calibrator.record(conf, abs(final_score - objective_score) < 0.3)

    # ── 5. 写入 ──
    if calibrated_conf >= 0.5 and not validation.is_suspicious:
        record_objective(task_type, agent_id, final_score)
    elif validation.action == 'dampen':
        record_objective(task_type, agent_id, final_score)  # 降权后仍写入

    logger.debug(
        'auto_ground_v2: type=%s score=%.2f conf=%.2f(cal=%.2f) '
        'div=%.2f action=%s',
        task_type, final_score, conf, calibrated_conf,
        validation.divergence, validation.action,
    )
    return final_score


# ═══════════════════════════════════════════
# Phase 8 修复: External Anchor Gate + Entropy + Holdout
# ═══════════════════════════════════════════


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
