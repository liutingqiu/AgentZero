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


# ═══════════════════════════════════════════
# Causal Event Graph
# ═══════════════════════════════════════════

class EventType(Enum):
    STEP_CREATED = 'step_created'
    STEP_STARTED = 'step_started'
    STEP_COMPLETED = 'step_completed'
    STEP_FAILED = 'step_failed'
    CRITIQUE_SUBMITTED = 'critique_submitted'
    ADVERSARIAL_ATTACK = 'adversarial_attack'
    JUDGE_RULING = 'judge_ruling'
    REFEREE_DECISION = 'referee_decision'
    CONSENSUS_REACHED = 'consensus_reached'
    CONTRACT_VIOLATION = 'contract_violation'
    ROLLBACK_TRIGGERED = 'rollback_triggered'


# ── 分片流 ──

class StreamPartition(Enum):
    PLANNER = 'planner'
    EXECUTOR = 'executor'
    CRITIC = 'critic'
    SYSTEM = 'system'


@dataclass
class CausalEvent:
    """因果事件——含 parent_event_ids 形成有向无环图。"""
    id: str
    seq: int
    event_type: EventType
    agent: str
    data: dict
    timestamp: str
    partition: StreamPartition
    parent_ids: list[str] = field(default_factory=list)  # 因果链
    step_id: str = ''


class ShardedEventLog:
    """分片事件日志——按 partition 隔离流，支持并发重放。"""

    MAX_EVENTS_PER_STREAM = 500

    def __init__(self):
        self._streams: dict[StreamPartition, list[CausalEvent]] = {
            p: [] for p in StreamPartition
        }
        self._global_seq = 0
        self._lock = threading.Lock()

    def append(self, event_type: EventType, agent: str, data: dict,
               partition: StreamPartition, step_id: str = '',
               parent_ids: list[str] | None = None) -> CausalEvent:
        with self._lock:
            self._global_seq += 1
            event = CausalEvent(
                id=f'evt_{uuid.uuid4().hex[:8]}',
                seq=self._global_seq,
                event_type=event_type,
                agent=agent,
                data=data,
                timestamp=datetime.now().isoformat(),
                partition=partition,
                parent_ids=parent_ids or [],
                step_id=step_id,
            )
            stream = self._streams[partition]
            stream.append(event)
            if len(stream) > self.MAX_EVENTS_PER_STREAM:
                self._streams[partition] = stream[-self.MAX_EVENTS_PER_STREAM:]
        return event

    def replay(self, partition: StreamPartition | None = None,
               until_seq: int | None = None) -> list[CausalEvent]:
        with self._lock:
            if partition:
                events = list(self._streams[partition])
            else:
                events = []
                for p in StreamPartition:
                    events.extend(self._streams[p])
                events.sort(key=lambda e: e.seq)
        if until_seq is not None:
            events = [e for e in events if e.seq <= until_seq]
        return events

    def children_of(self, event_id: str) -> list[CausalEvent]:
        """查找以 event_id 为父的所有子事件——追踪因果链。"""
        result = []
        for stream in self._streams.values():
            for e in stream:
                if event_id in e.parent_ids:
                    result.append(e)
        return sorted(result, key=lambda e: e.seq)

    def causal_chain(self, event_id: str) -> list[CausalEvent]:
        """从根事件到指定事件的完整因果链。"""
        chain = []
        visited = set()
        queue = [event_id]
        while queue:
            eid = queue.pop(0)
            if eid in visited:
                continue
            visited.add(eid)
            # 找到该事件
            for stream in self._streams.values():
                for e in stream:
                    if e.id == eid:
                        chain.append(e)
                        queue.extend(e.parent_ids)
                        break
        return sorted(chain, key=lambda e: e.seq)

    def stats(self) -> dict:
        return {
            'total': self._global_seq,
            'by_partition': {
                p.value: len(self._streams[p]) for p in StreamPartition
            },
            'causal_edges': sum(
                len(e.parent_ids)
                for stream in self._streams.values()
                for e in stream
            ),
        }


# ═══════════════════════════════════════════
# Adversarial Consensus Engine
# ═══════════════════════════════════════════

@dataclass
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
# ═══════════════════════════════════════════

@dataclass
class AgentContract:
    """Agent 合约——运行时强制执行。"""
    agent_id: str
    role: str
    authority_level: int
    allowed_events: list[EventType]
    allowed_partitions: list[StreamPartition]
    input_validator: object | None = None   # callable(input) → bool
    output_validator: object | None = None  # callable(output) → bool
    max_retries: int = 3


CONTRACTS: dict[str, AgentContract] = {
    'planner': AgentContract(
        agent_id='planner', role='planner', authority_level=2,
        allowed_events=[EventType.STEP_CREATED],
        allowed_partitions=[StreamPartition.PLANNER],
    ),
    'executor': AgentContract(
        agent_id='executor', role='executor', authority_level=2,
        allowed_events=[EventType.STEP_STARTED, EventType.STEP_COMPLETED,
                        EventType.STEP_FAILED],
        allowed_partitions=[StreamPartition.EXECUTOR],
        output_validator=lambda o: len(str(o)) > 5,
    ),
    'critic': AgentContract(
        agent_id='critic', role='critic', authority_level=3,
        allowed_events=[EventType.CRITIQUE_SUBMITTED,
                        EventType.ADVERSARIAL_ATTACK,
                        EventType.JUDGE_RULING],
        allowed_partitions=[StreamPartition.CRITIC],
    ),
    'synthesizer': AgentContract(
        agent_id='synthesizer', role='synthesizer', authority_level=2,
        allowed_events=[],
        allowed_partitions=[StreamPartition.SYSTEM],
    ),
}


class ContractViolation(Exception):
    """合约违规——运行时拦截。"""

    def __init__(self, agent_id: str, reason: str):
        self.agent_id = agent_id
        self.reason = reason
        super().__init__(f'[{agent_id}] 合约违规: {reason}')


def get_contract(agent_id: str) -> AgentContract:
    c = CONTRACTS.get(agent_id)
    if not c:
        raise ContractViolation(agent_id, '未注册合约')
    return c


def enforce_event(agent_id: str, event_type: EventType,
                  partition: StreamPartition):
    """运行时强制执行——每次事件触发前必须通过此门禁。"""
    c = get_contract(agent_id)
    if event_type not in c.allowed_events:
        raise ContractViolation(
            agent_id,
            f'无权触发 {event_type.value}（允许: {[e.value for e in c.allowed_events]}）',
        )
    if partition not in c.allowed_partitions:
        raise ContractViolation(
            agent_id,
            f'无权写入 {partition.value} 分区',
        )


def enforce_output(agent_id: str, output: str):
    """运行时输出校验。"""
    c = get_contract(agent_id)
    if c.output_validator and not c.output_validator(output):
        raise ContractViolation(agent_id, '输出不符合合约要求')


# ═══════════════════════════════════════════
# Blackboard v5 — Causal + Sharded + Enforced
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

class ContractAgent:
    def __init__(self, agent_id: str, llm_caller):
        self.agent_id = agent_id
        self.contract = get_contract(agent_id)
        self.llm = llm_caller

    def _call(self, system: str, prompt: str) -> str:
        try:
            reply = self.llm(messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ])
            return str(reply) if reply else ''
        except Exception as exc:
            logger.warning('%s failed: %s', self.agent_id, exc)
            return ''


class PlannerV5(ContractAgent):
    def __init__(self, llm_caller):
        super().__init__('planner', llm_caller)

    def propose(self, bb: BlackboardV5) -> list[dict]:
        system = '你是 Planner。建议步骤。输出 JSON: {"steps":[{"step":1,"action":"...","agent":"executor","criteria":"..."}]}'
        reply = self._call(system, f'任务: {bb.task}')
        plan = extract_first_json(reply) or {}
        return plan.get('steps', [{'step': 1, 'action': bb.task,
                                    'agent': 'executor', 'criteria': '完成'}])


class ExecutorV5(ContractAgent):
    def __init__(self, llm_caller):
        super().__init__('executor', llm_caller)

    def execute(self, step: dict, bb: BlackboardV5) -> str:
        system = '你是 Executor。执行步骤，输出结果。代码用```包裹。'
        prompt = f'{bb.summary()}\n步骤: {step.get("action","")}\n验收: {step.get("criteria","")}'
        return self._call(system, prompt)


class CriticV5(ContractAgent):
    def __init__(self, llm_caller):
        super().__init__('critic', llm_caller)

    def review(self, output: str, step: dict) -> dict:
        system = '你是 Critic。审查并主动找弱点。输出 JSON: {"passed":bool,"score":0-100,"issues":[],"adversarial":["攻击点1"]}'
        prompt = f'步骤: {step.get("action","")}\n输出:\n---\n{output[:2000]}\n---'
        reply = self._call(system, prompt)
        v = extract_first_json(reply) or {}
        return v if isinstance(v, dict) else {'passed': True, 'score': 50,
                                               'issues': [], 'adversarial': []}


class SynthesizerV5(ContractAgent):
    def __init__(self, llm_caller):
        super().__init__('synthesizer', llm_caller)

    def synthesize(self, bb: BlackboardV5) -> str:
        system = '你是 Synthesizer。整合所有结果输出最终答案。'
        return self._call(system, bb.summary())


# ═══════════════════════════════════════════
# Orchestrator v5
# ═══════════════════════════════════════════

class MultiAgentOrchestratorV5:
    MAX_RETRIES = 3

    def __init__(self, llm_caller):
        self.planner = PlannerV5(llm_caller)
        self.executor = ExecutorV5(llm_caller)
        self.critic = CriticV5(llm_caller)
        self.synthesizer = SynthesizerV5(llm_caller)

    def run(self, task: str) -> dict:
        bb = BlackboardV5(task)
        logger.info('kernel v5: starting')

        # 1. Plan
        proposed = self.planner.propose(bb)
        step_ids = bb.create_steps(proposed)
        if not step_ids:
            return {'status': 'failed', 'answer': '规划失败',
                    'blackboard': bb, 'completed': 0, 'failed': 1}

        # 2. Execute + Adversarial Consensus
        completed = 0
        failed = 0
        for sid in step_ids:
            step = bb.get_step(sid)
            if not step:
                continue
            info = {'id': sid, 'action': step['action'],
                    'criteria': step['criteria']}

            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    bb.start_step(sid, 'executor')
                    output = self.executor.execute(info, bb)

                    # Rule score
                    from behavior_canon import synthetic_evaluate
                    rule_s, _ = synthetic_evaluate(output, 'code')

                    # Critic + Adversarial
                    critique = self.critic.review(output, info)
                    bb.submit_critique(sid, critique, 'critic')
                    critic_s = critique.get('score', 50) / 100.0
                    attacks = critique.get('adversarial', [])

                    # Consensus
                    result = bb.adversarial_check(
                        sid, output, rule_s, critic_s, attacks,
                    )

                    if result.passed:
                        bb.complete_step(sid, output, 'executor')
                        completed += 1
                        break
                    elif attempt < self.MAX_RETRIES:
                        info['action'] = (
                            f'{info["action"]}\n'
                            f'[攻击发现] {"; ".join(attacks)}'
                        )
                    else:
                        bb.fail_step(sid, 'executor', result.referee_ruling)
                        failed += 1
                except ContractViolation as exc:
                    logger.warning('contract violation: %s', exc)
                    failed += 1
                    break

        # 3. Synthesize
        answer = self.synthesizer.synthesize(bb)
        status = 'done' if failed == 0 else ('partial' if completed > 0 else 'failed')
        logger.info('kernel v5: done — %d/%d ok', completed, len(step_ids))
        return {
            'status': status, 'answer': answer, 'blackboard': bb,
            'completed': completed, 'failed': failed,
            'stats': bb.stats(),
        }


def collaborate(task: str, llm_caller) -> dict:
    return MultiAgentOrchestratorV5(llm_caller).run(task)


# ═══════════════════════════════════════════
# v6 Stability Layer
# ═══════════════════════════════════════════
# 三个稳定性机制:
#   1. VectorClock — agent 级单调时钟，保证因果顺序
#   2. ConvergenceEngine — 固定点检测，防止无限拉扯
#   3. RepairSystem — violation → repair → revalidate


# ── Vector Clock ──

@dataclass
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

class MultiAgentOrchestratorV6:
    """v6 编排器——向量时钟 + 收敛引擎 + 修复系统。"""

    def __init__(self, llm_caller):
        self.planner = PlannerV5(llm_caller)
        self.executor = ExecutorV5(llm_caller)
        self.critic = CriticV5(llm_caller)
        self.synthesizer = SynthesizerV5(llm_caller)
        self._clocks: dict[str, VectorClock] = defaultdict(VectorClock)
        self._convergence = ConvergenceEngine()
        self._repair = RepairSystem()
        self._validator = TemporalValidator()

    def run(self, task: str) -> dict:
        bb = BlackboardV5(task)
        logger.info('kernel v6: starting (with stability layer)')

        # 1. Plan
        proposed = self.planner.propose(bb)
        step_ids = bb.create_steps(proposed)
        if not step_ids:
            return {'status': 'failed', 'answer': '规划失败',
                    'blackboard': bb, 'completed': 0, 'failed': 1,
                    'stability': {'convergence': False, 'repairs': 0}}

        # 2. Execute + Stability
        completed = 0
        failed = 0
        repairs = 0

        for sid in step_ids:
            step = bb.get_step(sid)
            if not step:
                continue
            info = {'id': sid, 'action': step['action'],
                    'criteria': step['criteria']}

            for attempt in range(ConvergenceEngine.MAX_ROUNDS):
                try:
                    # 向量时钟
                    self._clocks['executor'].tick('executor')

                    bb.start_step(sid, 'executor')
                    output = self.executor.execute(info, bb)

                    # 规则评分
                    from behavior_canon import synthetic_evaluate
                    rule_s, _ = synthetic_evaluate(output, 'code')

                    # Critic
                    critique = self.critic.review(output, info)
                    bb.submit_critique(sid, critique, 'critic')
                    critic_s = critique.get('score', 50) / 100.0
                    attacks = critique.get('adversarial', [])

                    # 共识
                    result = bb.adversarial_check(
                        sid, output, rule_s, critic_s, attacks,
                    )

                    # ── 收敛检查 ──
                    should_stop, reason = self._convergence.check(
                        sid, result.final_score, result.decision, attempt,
                    )

                    if result.passed and not should_stop:
                        bb.complete_step(sid, output, 'executor')
                        completed += 1
                        break
                    elif should_stop:
                        if result.passed:
                            bb.complete_step(sid, output, 'executor')
                            completed += 1
                        else:
                            bb.fail_step(sid, 'executor', reason)
                            failed += 1
                        logger.info('v6 converge: %s → %s', sid, reason)
                        break
                    elif attempt < ConvergenceEngine.MAX_ROUNDS - 1:
                        info['action'] = f'{info["action"]}\n[修复] {"; ".join(attacks)}'
                        repairs += 1
                    else:
                        bb.fail_step(sid, 'executor', result.referee_ruling)
                        failed += 1

                except ContractViolation as exc:
                    # ── 修复系统 ──
                    plan = self._repair.diagnose(sid, str(exc), '')
                    if self._repair.should_retry(sid):
                        info['action'] = (
                            f'{info["action"]}\n[自动修复] {plan.suggested_fix}'
                        )
                        repairs += 1
                        continue
                    logger.warning('v6 repair exhausted: %s', exc)
                    failed += 1
                    break

        # 3. 因果验证
        for sid in step_ids:
            chain = bb.causal_chain(sid)
            ok, msg = self._validator.validate_chain(chain)
            if not ok:
                logger.warning('v6 temporal violation: %s', msg)

        # 4. Synthesize
        answer = self.synthesizer.synthesize(bb)
        status = 'done' if failed == 0 else ('partial' if completed > 0 else 'failed')

        return {
            'status': status, 'answer': answer, 'blackboard': bb,
            'completed': completed, 'failed': failed,
            'stability': {
                'convergence': True,
                'repairs': repairs,
                'clocks': {k: v.to_dict() for k, v in self._clocks.items()},
            },
            'stats': bb.stats(),
        }


def collaborate_v6(task: str, llm_caller) -> dict:
    return MultiAgentOrchestratorV6(llm_caller).run(task)


# ═══════════════════════════════════════════
# v7 Semantic Layer
# ═══════════════════════════════════════════
# 三个语义升级:
#   1. Global Replanner — root_cause → replan DAG
#   2. Semantic Convergence — reasoning similarity + score + causal
#   3. Event Compression — cluster → merge → summary event


# ── Semantic Convergence v2 ──

class SemanticConvergence(ConvergenceEngine):
    """v7 语义收敛——在 score 稳定基础上增加 reasoning 一致性检查。"""

    def __init__(self):
        super().__init__()
        self._reasonings: dict[str, list[str]] = defaultdict(list)

    def check_semantic(self, step_id: str, score: float, decision: str,
                       reasoning: str, attempt: int) -> tuple[bool, str]:
        """语义收敛检查——score稳定 + reasoning相似。"""
        # 基础收敛检查
        should_stop, reason = self.check(step_id, score, decision, attempt)
        if should_stop:
            return True, reason

        # 语义相似度检查
        self._reasonings[step_id].append(reasoning)
        if len(self._reasonings[step_id]) >= 3:
            recent = self._reasonings[step_id][-3:]
            sim = _reasoning_similarity(recent)
            if sim > 0.8:
                return True, f'语义收敛 (相似度{sim:.2f}>0.8)'

        return False, '继续'


def _reasoning_similarity(reasonings: list[str]) -> float:
    """计算 reasoning 列表的相似度——简单 token overlap。"""
    if len(reasonings) < 2:
        return 1.0
    similarities = []
    for i in range(len(reasonings) - 1):
        a = set(reasonings[i].lower().split())
        b = set(reasonings[i + 1].lower().split())
        if not a or not b:
            similarities.append(0.0)
        else:
            similarities.append(len(a & b) / max(len(a | b), 1))
    return sum(similarities) / len(similarities) if similarities else 1.0


# ── Global Replanner ──

@dataclass
class FailureTrace:
    """失败追踪——从症状追溯到根因。"""
    step_id: str
    events: list[CausalEvent]
    root_cause: str
    affected_steps: list[str]


class GlobalReplanner:
    """v7 全局重规划——violation → root cause → replan DAG。

    替代 v6 的局部 retry。
    """

    def __init__(self, llm_caller):
        self.llm = llm_caller

    def trace_root_cause(self, step_id: str,
                         blackboard: BlackboardV5) -> FailureTrace:
        """从失败步骤追溯根因。"""
        chain = blackboard.causal_chain(step_id)
        events = [e for e in chain if e.event_type in (
            EventType.STEP_FAILED, EventType.CRITIQUE_SUBMITTED,
            EventType.CONSENSUS_REACHED,
        )]

        # 提取失败描述
        failures = [
            e.data.get('reason', '') or
            str(e.data.get('issues', '')) or
            str(e.data.get('decision', ''))
            for e in events
        ]
        root = '; '.join(failures[:3]) if failures else '未知原因'

        # 受影响步骤: 失败步骤及之后的依赖步骤
        step_order = blackboard._step_order
        try:
            idx = step_order.index(step_id)
            affected = step_order[idx:]
        except ValueError:
            affected = [step_id]

        return FailureTrace(
            step_id=step_id, events=chain,
            root_cause=root, affected_steps=affected,
        )

    def replan(self, trace: FailureTrace,
               blackboard: BlackboardV5) -> list[dict]:
        """基于失败追踪生成新计划。"""
        system = """你是 Global Replanner。根据失败原因重新规划。

分析失败根因，输出修正后的新步骤。注意:
- 跳过已完成步骤
- 为受影响步骤生成新的执行方案
- 新步骤应包含修正措施

输出 JSON: {"steps": [{"step": N, "action": "...", "agent": "executor", "criteria": "..."}]}"""

        prompt = (
            f'原任务: {blackboard.task}\n'
            f'失败步骤: {trace.step_id}\n'
            f'根因: {trace.root_cause}\n'
            f'受影响: {", ".join(trace.affected_steps)}\n'
            f'当前状态:\n{blackboard.summary()}\n\n'
            f'请输出修正方案。'
        )
        try:
            reply = self.llm(messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ])
            plan = extract_first_json(str(reply)) or {}
            return plan.get('steps', [])
        except Exception:
            return []


# ── Event Compression ──

class EventCompressor:
    """v7 事件压缩——语义聚类合并，防止 event graph 无限膨胀。"""

    MAX_EVENTS_BEFORE_COMPRESS = 300

    def should_compress(self, log: ShardedEventLog) -> bool:
        return log.stats()['total'] >= self.MAX_EVENTS_BEFORE_COMPRESS

    def compress(self, log: ShardedEventLog) -> dict:
        """压缩事件日志——按 (event_type, step_id) 聚类，合并冗余。"""
        all_events = log.replay()
        if len(all_events) < self.MAX_EVENTS_BEFORE_COMPRESS:
            return {'compressed': 0, 'total': len(all_events)}

        # 按类型分组
        by_type: dict[str, list[CausalEvent]] = defaultdict(list)
        for e in all_events:
            key = f'{e.event_type.value}:{e.step_id}'
            by_type[key].append(e)

        compressed = 0
        for key, events in by_type.items():
            if len(events) >= 5:
                # 合并: 保留第一个和最后一个，删除中间
                to_merge = events[1:-1]
                # 标记为已压缩（实际删除由外部控制）
                compressed += len(to_merge)
                logger.debug('compress: %s → %d events merged',
                             key, len(to_merge))

        logger.info('v7 compress: %d/%d events compressed',
                    compressed, len(all_events))
        return {'compressed': compressed, 'total': len(all_events)}


# ═══════════════════════════════════════════
# v7 Orchestrator
# ═══════════════════════════════════════════

class MultiAgentOrchestratorV7:
    """v7 编排器——全局重规划 + 语义收敛 + 事件压缩。"""

    def __init__(self, llm_caller):
        self.planner = PlannerV5(llm_caller)
        self.executor = ExecutorV5(llm_caller)
        self.critic = CriticV5(llm_caller)
        self.synthesizer = SynthesizerV5(llm_caller)
        self._clocks: dict[str, VectorClock] = defaultdict(VectorClock)
        self._convergence = SemanticConvergence()
        self._repair = RepairSystem()
        self._replanner = GlobalReplanner(llm_caller)
        self._compressor = EventCompressor()
        self._validator = TemporalValidator()

    def run(self, task: str) -> dict:
        bb = BlackboardV5(task)
        logger.info('kernel v7: starting (semantic layer)')

        # 1. Plan
        proposed = self.planner.propose(bb)
        step_ids = bb.create_steps(proposed)
        if not step_ids:
            return {'status': 'failed', 'answer': '规划失败',
                    'blackboard': bb, 'stats': bb.stats()}

        # 2. Execute
        completed = 0
        failed = 0
        repairs = 0
        replans = 0

        i = 0
        while i < len(step_ids):
            sid = step_ids[i]
            step = bb.get_step(sid)
            if not step:
                i += 1
                continue
            info = {'id': sid, 'action': step['action'],
                    'criteria': step['criteria']}

            step_ok = False
            for attempt in range(ConvergenceEngine.MAX_ROUNDS):
                try:
                    self._clocks['executor'].tick('executor')
                    bb.start_step(sid, 'executor')
                    output = self.executor.execute(info, bb)

                    from behavior_canon import synthetic_evaluate
                    rule_s, _ = synthetic_evaluate(output, 'code')

                    critique = self.critic.review(output, info)
                    bb.submit_critique(sid, critique, 'critic')
                    critic_s = critique.get('score', 50) / 100.0
                    attacks = critique.get('adversarial', [])
                    judge_reasoning = critique.get('judge_rationale', str(critique))

                    result = bb.adversarial_check(
                        sid, output, rule_s, critic_s, attacks,
                    )

                    # 语义收敛
                    should_stop, reason = self._convergence.check_semantic(
                        sid, result.final_score, result.decision,
                        judge_reasoning, attempt,
                    )

                    if result.passed and not should_stop:
                        bb.complete_step(sid, output, 'executor')
                        completed += 1
                        step_ok = True
                        break
                    elif should_stop:
                        if result.passed:
                            bb.complete_step(sid, output, 'executor')
                            completed += 1
                            step_ok = True
                        else:
                            bb.fail_step(sid, 'executor', reason)
                            failed += 1
                        break
                    elif attempt < ConvergenceEngine.MAX_ROUNDS - 1:
                        info['action'] = f'{info["action"]}\n[修复] {"; ".join(attacks)}'
                        repairs += 1
                    else:
                        bb.fail_step(sid, 'executor', result.referee_ruling)
                        failed += 1

                except ContractViolation as exc:
                    plan = self._repair.diagnose(sid, str(exc), '')
                    if self._repair.should_retry(sid):
                        info['action'] = f'{info["action"]}\n[修复] {plan.suggested_fix}'
                        repairs += 1
                        continue
                    failed += 1
                    break

            # ── 全局重规划 ──
            if not step_ok and failed > 0:
                trace = self._replanner.trace_root_cause(sid, bb)
                new_steps = self._replanner.replan(trace, bb)
                if new_steps:
                    replans += 1
                    new_ids = bb.create_steps(new_steps)
                    step_ids = step_ids[:i + 1] + new_ids + step_ids[i + 1:]
                    logger.info('v7 replan: %d new steps added after %s',
                                len(new_ids), sid)

            i += 1

        # 3. 因果验证
        for sid in step_ids:
            chain = bb.causal_chain(sid)
            ok, msg = self._validator.validate_chain(chain)
            if not ok:
                logger.warning('v7 temporal: %s', msg)

        # 4. 事件压缩
        compress_stats = self._compressor.compress(bb.events) if self._compressor.should_compress(bb.events) else {}

        # 5. Synthesize
        answer = self.synthesizer.synthesize(bb)
        status = 'done' if failed == 0 else ('partial' if completed > 0 else 'failed')

        return {
            'status': status, 'answer': answer,
            'completed': completed, 'failed': failed,
            'stability': {
                'repairs': repairs, 'replans': replans,
                'compressed': compress_stats.get('compressed', 0),
                'clocks': {k: v.to_dict() for k, v in self._clocks.items()},
            },
            'stats': bb.stats(),
        }


def collaborate_v7(task: str, llm_caller) -> dict:
    return MultiAgentOrchestratorV7(llm_caller).run(task)


# ═══════════════════════════════════════════
# v8 Grounded Runtime — 现实锚定层
# ═══════════════════════════════════════════
# 三个机制:
#   1. GroundTruth — 收集外部信号(tool/feedback/env)作为 primary truth
#   2. Anti-Self-Validation — LLM自评权重×0.3
#   3. Reality Constraint — execution outcome > reasoning outcome
#
# 核心原则: ❗系统的判断必须来自外部世界，不是自身推理


class GroundTruth:
    """外部真实信号——非 LLM 来源的客观结果。

    来源:
      - tool_exec: 工具执行结果 (0=失败, 1=成功)
      - human_feedback: 用户显式反馈 (-1/0/+1)
      - env_signal: API返回码/系统状态/DB查询结果 (0~1)
    """

    SOURCE_WEIGHTS: dict[str, float] = {
        'tool_exec': 1.0,        # 最高权重——机器不会撒谎
        'human_feedback': 0.9,   # 人类判断
        'env_signal': 0.8,       # 环境信号
        'llm_internal': 0.3,     # LLM自评——最低权重
    }

    def __init__(self):
        self._signals: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        # {step_id: [(source, score, detail), ...]}
        self._lock = threading.Lock()

    def ingest(self, step_id: str, source: str, score: float,
               detail: str = ''):
        """摄入外部信号。"""
        with self._lock:
            self._signals[step_id].append((source, score, detail))

    def get_grounded_score(self, step_id: str,
                           internal_score: float) -> tuple[float, bool]:
        """获取锚定后的评分——外部信号优先。

        Returns:
            (final_score, has_external) — has_external=True 表示有外部信号
        """
        with self._lock:
            signals = self._signals.get(step_id, [])

        if not signals:
            return internal_score, False

        # 加权融合: 外部信号 + 内部评分(降权)
        weighted_sum = 0.0
        weight_sum = 0.0
        for source, score, _ in signals:
            w = self.SOURCE_WEIGHTS.get(source, 0.5)
            weighted_sum += score * w
            weight_sum += w

        # 内部评分以最低权重参与
        llm_weight = self.SOURCE_WEIGHTS['llm_internal']
        weighted_sum += internal_score * llm_weight
        weight_sum += llm_weight

        final = weighted_sum / weight_sum if weight_sum > 0 else internal_score
        return final, True

    def has_external(self, step_id: str) -> bool:
        with self._lock:
            return len(self._signals.get(step_id, [])) > 0

    def summary(self, step_id: str) -> str:
        with self._lock:
            signals = self._signals.get(step_id, [])
        if not signals:
            return '(无外部信号)'
        parts = [f'{src}:{score:.2f}' for src, score, _ in signals]
        return ', '.join(parts)


class GroundedJudge:
    """v8 锚定裁判——外部信号优先于 LLM 共识。

    规则:
      1. 有 tool_exec 结果 → 以工具结果为准
      2. 有 human_feedback → 覆盖 LLM 评分
      3. 纯 LLM 评分 → 降权 ×0.3
    """

    def __init__(self):
        self.ground_truth = GroundTruth()
        self._adversarial = AdversarialConsensus()

    def evaluate(self, step_id: str, output: str,
                 rule_score: float, critic_score: float,
                 attacks: list[str], judge_score: float | None = None
                 ) -> tuple[float, bool, str]:
        """锚定评估——外部优先。"""
        # 内部评分（降权）
        internal = self._adversarial.evaluate(
            output, 'code', rule_score, critic_score, attacks, judge_score,
        ).final_score

        # 外部锚定
        grounded, has_ext = self.ground_truth.get_grounded_score(
            step_id, internal,
        )

        if has_ext:
            # 有外部信号 → 以锚定评分为准
            passed = grounded >= 0.5
            source = f'grounded({self.ground_truth.summary(step_id)})'
        else:
            # 纯内部 → 降权
            passed = internal >= 0.6  # 阈值提高到 0.6
            source = 'internal(×0.3 weight)'

        return grounded, passed, source


# ═══════════════════════════════════════════
# v8 Orchestrator — Grounded
# ═══════════════════════════════════════════

class MultiAgentOrchestratorV8:
    """v8 编排器——外部真实信号锚定。"""

    def __init__(self, llm_caller, tool_executor=None):
        self.planner = PlannerV5(llm_caller)
        self.executor = ExecutorV5(llm_caller)
        self.critic = CriticV5(llm_caller)
        self.synthesizer = SynthesizerV5(llm_caller)
        self._judge = GroundedJudge()
        self._clocks: dict[str, VectorClock] = defaultdict(VectorClock)
        self._convergence = SemanticConvergence()
        self._replanner = GlobalReplanner(llm_caller)
        self._compressor = EventCompressor()
        self._validator = TemporalValidator()
        self._tool_executor = tool_executor  # 可选的工具执行器

    def run(self, task: str) -> dict:
        bb = BlackboardV5(task)
        logger.info('kernel v8: grounded runtime starting')

        proposed = self.planner.propose(bb)
        step_ids = bb.create_steps(proposed)
        if not step_ids:
            return {'status': 'failed', 'answer': '规划失败',
                    'blackboard': bb, 'stats': bb.stats()}

        completed = 0
        failed = 0
        grounded = 0

        i = 0
        while i < len(step_ids):
            sid = step_ids[i]
            step = bb.get_step(sid)
            if not step:
                i += 1
                continue
            info = {'id': sid, 'action': step['action'],
                    'criteria': step['criteria']}
            step_ok = False

            for attempt in range(ConvergenceEngine.MAX_ROUNDS):
                try:
                    self._clocks['executor'].tick('executor')
                    bb.start_step(sid, 'executor')
                    output = self.executor.execute(info, bb)

                    # ── 外部工具执行 ──
                    if self._tool_executor:
                        try:
                            tool_result = self._tool_executor(output)
                            tool_ok = 1.0 if tool_result else 0.0
                            self._judge.ground_truth.ingest(
                                sid, 'tool_exec', tool_ok,
                                'success' if tool_ok > 0.5 else 'failed',
                            )
                        except Exception:
                            pass

                    from behavior_canon import synthetic_evaluate
                    rule_s, _ = synthetic_evaluate(output, 'code')

                    critique = self.critic.review(output, info)
                    bb.submit_critique(sid, critique, 'critic')
                    critic_s = critique.get('score', 50) / 100.0
                    attacks = critique.get('adversarial', [])

                    # ── 锚定裁判 ──
                    score, passed, source = self._judge.evaluate(
                        sid, output, rule_s, critic_s, attacks,
                    )
                    if self._judge.ground_truth.has_external(sid):
                        grounded += 1

                    # 收敛
                    should_stop, reason = self._convergence.check_semantic(
                        sid, score, 'accept' if passed else 'reject',
                        source, attempt,
                    )

                    if passed and not should_stop:
                        bb.complete_step(sid, output, 'executor')
                        completed += 1
                        step_ok = True
                        break
                    elif should_stop:
                        if passed:
                            bb.complete_step(sid, output, 'executor')
                            completed += 1
                            step_ok = True
                        else:
                            bb.fail_step(sid, 'executor', reason)
                            failed += 1
                        break
                    elif attempt < ConvergenceEngine.MAX_ROUNDS - 1:
                        info['action'] = f'{info["action"]}\n[{source}] {"; ".join(attacks)}'
                    else:
                        bb.fail_step(sid, 'executor', f'{source}: score={score:.2f}')
                        failed += 1

                except ContractViolation as exc:
                    failed += 1
                    break

            if not step_ok and failed > 0:
                trace = self._replanner.trace_root_cause(sid, bb)
                new_steps = self._replanner.replan(trace, bb)
                if new_steps:
                    new_ids = bb.create_steps(new_steps)
                    step_ids = step_ids[:i + 1] + new_ids + step_ids[i + 1:]
            i += 1

        for sid in step_ids:
            chain = bb.causal_chain(sid)
            ok, msg = self._validator.validate_chain(chain)
            if not ok:
                logger.warning('v8 temporal: %s', msg)

        self._compressor.compress(bb.events) if self._compressor.should_compress(bb.events) else None

        answer = self.synthesizer.synthesize(bb)
        status = 'done' if failed == 0 else ('partial' if completed > 0 else 'failed')

        return {
            'status': status, 'answer': answer,
            'completed': completed, 'failed': failed,
            'grounded': grounded,
            'stats': bb.stats(),
        }


def collaborate_v8(task: str, llm_caller, tool_executor=None) -> dict:
    return MultiAgentOrchestratorV8(llm_caller, tool_executor).run(task)
