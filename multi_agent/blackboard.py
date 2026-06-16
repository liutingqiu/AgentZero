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
from multi_agent.events import CausalEvent, ShardedEventLog, EventType, StreamPartition
from multi_agent.contracts import enforce_event, enforce_output, ContractViolation
from multi_agent.consensus import AdversarialConsensus

logger = get_logger('zero.kernel')


# ═══════════════════════════════════════════
# Causal Event Graph
# ═══════════════════════════════════════════


class BlackboardV5:
    """v5 黑板——因果事件图 + 分片流 + 对抗式共识 + 运行时合约。"""

    def __init__(self, task: str = ''):
        self.task = task
        self.events = ShardedEventLog()
        self._consensus = AdversarialConsensus()
        self._steps: dict[str, dict] = {}
        self._step_order: list[str] = []
        self._lock = threading.RLock()

    # ── 合约保护的写入 ──

    def create_steps(self, plan: list[dict], agent: str = 'planner'
                     ) -> list[str]:
        enforce_event(agent, EventType.STEP_CREATED, StreamPartition.PLANNER)
        step_ids = []
        with self._lock:
            for item in plan:
                sid = f'step_{item.get("step", len(self._step_order) + 1)}'
                self.events.append(
                    EventType.STEP_CREATED, agent,
                    {'step_id': sid, 'action': item.get('action', ''),
                     'criteria': item.get('criteria', ''),
                     'owner': item.get('agent', 'executor')},
                    StreamPartition.PLANNER, step_id=sid,
                )
                self._step_order.append(sid)
                self._steps[sid] = {
                    'status': 'pending', 'action': item.get('action', ''),
                    'criteria': item.get('criteria', ''),
                    'owner': item.get('agent', 'executor'),
                    'versions': [], 'critiques': [],
                    'parent_event': None,
                }
                step_ids.append(sid)
        logger.info('kernel v5: %d steps created by %s', len(step_ids), agent)
        return step_ids

    def start_step(self, step_id: str, agent: str):
        enforce_event(agent, EventType.STEP_STARTED, StreamPartition.EXECUTOR)
        parent = self._last_event_for(step_id)
        e = self.events.append(
            EventType.STEP_STARTED, agent, {},
            StreamPartition.EXECUTOR, step_id=step_id,
            parent_ids=[parent.id] if parent else [],
        )
        self._steps.get(step_id, {})['status'] = 'running'
        self._steps.get(step_id, {})['parent_event'] = e.id

    def complete_step(self, step_id: str, output: str, agent: str) -> str:
        enforce_event(agent, EventType.STEP_COMPLETED, StreamPartition.EXECUTOR)
        enforce_output(agent, output)
        parent = self._last_event_for(step_id)
        e = self.events.append(
            EventType.STEP_COMPLETED, agent, {'output': output},
            StreamPartition.EXECUTOR, step_id=step_id,
            parent_ids=[parent.id] if parent else [],
        )
        s = self._steps.get(step_id, {})
        s['status'] = 'done'
        s.setdefault('versions', []).append({
            'v': len(s.get('versions', [])) + 1,
            'output': output, 'agent': agent, 'event_id': e.id,
        })
        return e.id

    def fail_step(self, step_id: str, agent: str, reason: str = ''):
        enforce_event(agent, EventType.STEP_FAILED, StreamPartition.EXECUTOR)
        parent = self._last_event_for(step_id)
        self.events.append(
            EventType.STEP_FAILED, agent, {'reason': reason},
            StreamPartition.EXECUTOR, step_id=step_id,
            parent_ids=[parent.id] if parent else [],
        )
        self._steps.get(step_id, {})['status'] = 'failed'

    def submit_critique(self, step_id: str, critique: dict,
                        agent: str) -> str:
        enforce_event(agent, EventType.CRITIQUE_SUBMITTED, StreamPartition.CRITIC)
        parent = self._last_event_for(step_id)
        e = self.events.append(
            EventType.CRITIQUE_SUBMITTED, agent, critique,
            StreamPartition.CRITIC, step_id=step_id,
            parent_ids=[parent.id] if parent else [],
        )
        self._steps.get(step_id, {}).setdefault('critiques', []).append({
            'data': critique, 'event_id': e.id,
        })
        return e.id

    def adversarial_check(self, step_id: str, output: str,
                          rule_score: float, critic_score: float,
                          adversarial_issues: list[str],
                          judge_score: float | None = None
                          ) -> AdversarialResult:
        """对抗式共识——四阶段评估。"""
        result = self._consensus.evaluate(
            output, 'code', rule_score, critic_score,
            adversarial_issues, judge_score,
        )
        parent = self._last_event_for(step_id)
        self.events.append(
            EventType.CONSENSUS_REACHED, 'consensus',
            {'passed': result.passed, 'score': result.final_score,
             'decision': result.decision, 'attacks': len(adversarial_issues)},
            StreamPartition.SYSTEM, step_id=step_id,
            parent_ids=[parent.id] if parent else [],
        )
        return result

    # ── 因果查询 ──

    def _last_event_for(self, step_id: str) -> CausalEvent | None:
        all_events = self.events.replay()
        for e in reversed(all_events):
            if e.step_id == step_id:
                return e
        return None

    def causal_chain(self, step_id: str) -> list[CausalEvent]:
        events = self.events.replay()
        step_events = [e for e in events if e.step_id == step_id]
        if not step_events:
            return []
        last = step_events[-1]
        return self.events.causal_chain(last.id)

    # ── 读写 ──

    def get_step(self, step_id: str) -> dict | None:
        return self._steps.get(step_id)

    def next_pending(self) -> dict | None:
        for sid in self._step_order:
            s = self._steps.get(sid)
            if s and s['status'] == 'pending':
                return {'id': sid, **s}
        return None

    def latest_output(self, step_id: str) -> str:
        s = self._steps.get(step_id, {})
        vs = s.get('versions', [])
        return vs[-1]['output'] if vs else ''

    def summary(self) -> str:
        lines = [f'## {self.task}', '']
        for sid in self._step_order:
            s = self._steps.get(sid, {})
            st = s.get('status', '?')
            icon = {'pending': '⏳', 'running': '🔄', 'done': '✅',
                    'failed': '❌'}.get(st, '❓')
            out = self.latest_output(sid)[:120] if st == 'done' else '(未)'
            chain = self.causal_chain(sid)
            links = f' [{len(chain)}因果链]' if chain else ''
            lines.append(f'{icon} {sid}: {s.get("action","")[:60]} → {out}{links}')
        return '\n'.join(lines)

    def stats(self) -> dict:
        return {
            'events': self.events.stats(),
            'steps': len(self._steps),
            'done': sum(1 for s in self._steps.values() if s['status'] == 'done'),
            'pending': sum(1 for s in self._steps.values() if s['status'] == 'pending'),
            'failed': sum(1 for s in self._steps.values() if s['status'] == 'failed'),
            'causal_chains': sum(1 for sid in self._step_order if self.causal_chain(sid)),
        }


# ═══════════════════════════════════════════
# Contract Agents v5
# ═══════════════════════════════════════════

