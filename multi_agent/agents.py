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
from multi_agent.contracts import AgentContract, get_contract, enforce_event



# ═══════════════════════════════════════════
# Causal Event Graph
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

