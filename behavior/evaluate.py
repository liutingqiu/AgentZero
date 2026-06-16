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


