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
