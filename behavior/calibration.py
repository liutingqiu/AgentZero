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


