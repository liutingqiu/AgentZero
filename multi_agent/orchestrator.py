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
from multi_agent.agents import PlannerV5, ExecutorV5, CriticV5, SynthesizerV5
from multi_agent.blackboard import BlackboardV5



# ═══════════════════════════════════════════
# Causal Event Graph
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

