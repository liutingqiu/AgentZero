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
from multi_agent.events import EventType, StreamPartition

logger = get_logger('zero.kernel')


# ═══════════════════════════════════════════
# Causal Event Graph
# ═══════════════════════════════════════════


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

