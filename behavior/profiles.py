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


