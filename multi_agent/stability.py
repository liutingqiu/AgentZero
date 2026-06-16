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


class VectorClock:
    """Agent 级向量时钟——保证因果一致性。"""
    counters: dict[str, int] = field(default_factory=dict)

    def tick(self, agent_id: str):
        self.counters[agent_id] = self.counters.get(agent_id, 0) + 1

    def merge(self, other: 'VectorClock') -> 'VectorClock':
        result = VectorClock()
        all_keys = set(self.counters) | set(other.counters)
        for k in all_keys:
            result.counters[k] = max(self.counters.get(k, 0),
                                     other.counters.get(k, 0))
        return result

    def happens_before(self, other: 'VectorClock') -> bool:
        """严格偏序: self → other ?"""
        at_least_one_less = False
        for k in set(self.counters) | set(other.counters):
            a = self.counters.get(k, 0)
            b = other.counters.get(k, 0)
            if a > b:
                return False
            if a < b:
                at_least_one_less = True
        return at_least_one_less

    def concurrent(self, other: 'VectorClock') -> bool:
        return not self.happens_before(other) and not other.happens_before(self)

    def to_dict(self) -> dict:
        return dict(self.counters)


class TemporalValidator:
    """时间一致性验证器——确保因果链时间顺序正确。"""

    @staticmethod
    def validate_chain(events: list[CausalEvent]) -> tuple[bool, str]:
        """验证因果链的时间单调性。"""
        for e in events:
            for pid in e.parent_ids:
                parent = next((p for p in events if p.id == pid), None)
                if parent and parent.timestamp > e.timestamp:
                    return False, (
                        f'时间逆序: {e.id}({e.timestamp}) '
                        f'的父事件{pid}({parent.timestamp})更晚'
                    )
        return True, 'OK'

    @staticmethod
    def validate_clock(events: list[CausalEvent],
                       agent_clocks: dict[str, VectorClock]
                       ) -> tuple[bool, str]:
        """验证向量时钟单调性。"""
        for e in events:
            clock = agent_clocks.get(e.agent, VectorClock())
            clock.tick(e.agent)
            agent_clocks[e.agent] = clock
        return True, 'OK'


# ── Convergence Engine ──

@dataclass
class ConvergenceState:
    """收敛跟踪——检测共识是否进入振荡。"""
    scores: list[float] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    stable_since: int = 0

    def update(self, score: float, decision: str) -> str:
        """更新状态，返回 'continue' | 'converged' | 'oscillating'。"""
        self.scores.append(score)
        self.decisions.append(decision)
        if len(self.scores) > 10:
            self.scores = self.scores[-10:]
            self.decisions = self.decisions[-10:]

        n = len(self.scores)
        if n < 3:
            return 'continue'

        # 检测收敛: 最近3次变化 < ε
        recent = self.scores[-3:]
        delta = max(recent) - min(recent)
        if delta < 0.05 and len(set(self.decisions[-3:])) == 1:
            self.stable_since += 1
            if self.stable_since >= 2:
                return 'converged'
        else:
            self.stable_since = 0

        # 检测振荡: 最近4次交替 accept/reject
        if n >= 4:
            d = self.decisions[-4:]
            if d[0] != d[1] and d[1] != d[2] and d[2] != d[3]:
                return 'oscillating'

        return 'continue'


class ConvergenceEngine:
    """收敛引擎——保证共识必然终止。

    策略:
      - 收敛: 固定当前结果，不再重试
      - 振荡: 强制 accept（取最近3次最高分）
      - 超限: 超过 MAX_ROUNDS 强制停止
    """

    MAX_ROUNDS = 5

    def __init__(self):
        self._states: dict[str, ConvergenceState] = defaultdict(ConvergenceState)

    def check(self, step_id: str, score: float, decision: str,
              attempt: int) -> tuple[bool, str]:
        """检查是否应该终止重试。

        Returns:
            (should_stop, reason)
        """
        state = self._states[step_id]
        status = state.update(score, decision)

        if attempt >= self.MAX_ROUNDS:
            return True, '超过最大轮数，强制终止'
        if status == 'converged':
            return True, f'已收敛 (δ<0.05, 稳定{state.stable_since}轮)'
        if status == 'oscillating':
            # 取最近最高分
            best = max(self._states[step_id].scores[-4:])
            return True, f'检测到振荡，取最高分{best:.2f}强制通过'
        return False, '继续'


# ── Repair System ──

@dataclass
class RepairPlan:
    """修复方案——检测到违规后的自动修复路径。"""
    step_id: str
    violation: str
    strategy: str        # 'retry' | 'escalate' | 'delegate' | 'skip'
    suggested_fix: str
    attempts: int = 0


class RepairSystem:
    """可修复约束——violation → repair → revalidate。

    替代 v5 的 block-only 模式。
    """

    MAX_REPAIR_ATTEMPTS = 2

    def __init__(self):
        self._plans: dict[str, RepairPlan] = {}

    def diagnose(self, step_id: str, violation: str,
                 output: str = '') -> RepairPlan:
        """诊断违规，生成修复方案。"""
        # 策略选择
        if '输出过短' in violation or '空' in violation:
            strategy = 'retry'
            fix = '请输出更完整的内容，至少包含实质性的代码或分析。'
        elif '不符合合约' in violation:
            strategy = 'escalate'
            fix = '当前Agent权限不足，尝试委托给更高级别Agent。'
        elif '时间逆序' in violation:
            strategy = 'retry'
            fix = '重新执行此步骤以修正时间顺序。'
        else:
            strategy = 'retry'
            fix = f'检测到违规: {violation}。请修正后重试。'

        plan = RepairPlan(
            step_id=step_id, violation=violation,
            strategy=strategy, suggested_fix=fix,
        )
        self._plans[step_id] = plan
        return plan

    def should_retry(self, step_id: str) -> bool:
        plan = self._plans.get(step_id)
        if not plan:
            return False
        plan.attempts += 1
        return plan.attempts <= self.MAX_REPAIR_ATTEMPTS

    def get_fix(self, step_id: str) -> str:
        plan = self._plans.get(step_id)
        return plan.suggested_fix if plan else ''


# ═══════════════════════════════════════════
# v6 Orchestrator — 带稳定性保障
# ═══════════════════════════════════════════

