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

