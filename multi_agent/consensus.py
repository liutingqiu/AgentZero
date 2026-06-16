"""零 · AI OS Kernel v5
=======================
因果事件图 + 对抗式共识 + 运行时合约执行 + 分片事件流。

v5 核心升级:
  1. Causal Event Graph: parent_event_ids → 可解释因果链
  2. Adversarial Consensus: proposer→adversary→judge→referee 四阶段
  3. Runtime Enforcement: 每次 execute 前 validate_input + authority_ok
  4. Sharded Streams: planner/executor/critic/system 独立事件流
"""

from __future__ import annotations

import copy
import json
import math
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from config import get_logger
from utils.json_helpers import extract_first_json

logger = get_logger('zero.kernel')
from multi_agent.events import CausalEvent, EventType



# ═══════════════════════════════════════════
# Causal Event Graph
# ═══════════════════════════════════════════


class AdversarialResult:
    """对抗式共识结果。"""
    passed: bool
    final_score: float
    confidence: float
    decision: str       # 'accept' | 'revise' | 'reject'
    attack_surface: list[str]  # 对手发现的弱点
    judge_rationale: str
    referee_ruling: str


class AdversarialConsensus:
    """对抗式共识——四阶段验证。

    阶段:
      1. Proposer  → 提出方案
      2. Adversary → 主动攻击（找弱点）
      3. Judge     → LLM 评分
      4. Referee   → 规则引擎最终裁定
    """

    def __init__(self, pass_threshold: float = 0.5):
        self.pass_threshold = pass_threshold

    def evaluate(self, output: str, task_type: str,
                 rule_score: float, critic_score: float,
                 adversarial_issues: list[str] | None = None,
                 judge_score: float | None = None
                 ) -> AdversarialResult:
        """四阶段共识评估。"""
        attacks = adversarial_issues or []

        # 基础评分: 规则 + Critic
        base_score = rule_score * 0.4 + critic_score * 0.4
        # Judge 评分
        if judge_score is not None:
            base_score = base_score * 0.6 + judge_score * 0.4

        # 对手攻击惩罚
        attack_penalty = min(0.3, len(attacks) * 0.08)
        final = max(0.0, base_score - attack_penalty)

        # Referee 裁定
        if final >= self.pass_threshold:
            decision = 'accept'
            ruling = f'通过 (score={final:.2f}≥{self.pass_threshold})'
        elif final >= self.pass_threshold * 0.6:
            decision = 'revise'
            ruling = f'需修正 (score={final:.2f}, 接近阈值)'
        else:
            decision = 'reject'
            ruling = f'驳回 (score={final:.2f}, 对抗发现{len(attacks)}个弱点)'

        # 置信度: 攻击越多置信度越低
        confidence = max(0.3, 0.9 - len(attacks) * 0.1)

        return AdversarialResult(
            passed=decision == 'accept',
            final_score=final, confidence=confidence,
            decision=decision, attack_surface=attacks,
            judge_rationale=f'规则{rule_score:.2f}+Critic{critic_score:.2f}-攻击{attack_penalty:.2f}',
            referee_ruling=ruling,
        )


# ═══════════════════════════════════════════
# Runtime Contract Enforcement
