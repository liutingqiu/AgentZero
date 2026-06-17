"""零 · Agent 注册表
===================
按能力(capability)匹配Agent。

修复要点：
  - match() 评分：从 -1000 free_bonus 改为加权线性组合；
    免费只作为破平，避免低可靠性的免费 Agent 被滥用
  - 日志：统一 get_logger
"""

import threading

from config import get_logger, MODEL_NAMES

logger = get_logger('zero.registry')


# ── 权重追踪器 ───────────────────────────────────────────────────────
class ProficiencyTracker:
    """跟踪每个 Agent 在每个能力维度上的实际表现。

    静态基准 + 动态评分（滑动平均） → 运行时权重。
    """

    DEFAULT_WINDOW = 20  # 滑动窗口大小

    def __init__(self):
        # {agent_id: {capability: {'total': N, 'passed': N, 'score_sum': float}}}
        self._records: dict[str, dict[str, dict]] = {}
        # 静态基准权重（来自 benchmark）
        self._static: dict[str, dict[str, float]] = {}

    def set_static(self, agent_id: str, weights: dict[str, float]):
        """设置静态基准权重（来自 benchmark / 模型厂商）。"""
        self._static[agent_id] = dict(weights)

    def record(self, agent_id: str, capability: str, passed: bool,
               score: float = 0.0):
        """记录一次执行结果。"""
        if agent_id not in self._records:
            self._records[agent_id] = {}
        caps = self._records[agent_id]
        if capability not in caps:
            caps[capability] = {'total': 0, 'passed': 0, 'score_sum': 0.0}

        rec = caps[capability]
        rec['total'] += 1
        if passed:
            rec['passed'] += 1
        rec['score_sum'] += score

        # 滑动窗口：超过 DEFAULT_WINDOW 时丢弃最旧数据
        if rec['total'] > self.DEFAULT_WINDOW:
            # 简单衰减：保留 80% 的历史权重
            rec['passed'] = int(rec['passed'] * 0.8)
            rec['total'] = int(rec['total'] * 0.8)
            rec['score_sum'] *= 0.8

    def get_weight(self, agent_id: str, capability: str) -> float:
        """返回该 Agent 在该能力上的动态权重 (0.0~1.0)。

        策略: 有足够样本 → 动态权重 60% + 静态基准 40%
              样本不足  → 纯静态基准
        """
        static = self._static.get(agent_id, {}).get(capability, 0.5)

        caps = self._records.get(agent_id, {})
        rec = caps.get(capability)
        if not rec or rec['total'] < 3:
            return static  # 样本不足，纯静态

        # 动态评分：通过率 + 平均分
        pass_rate = rec['passed'] / max(rec['total'], 1)
        avg_score = (rec['score_sum'] / max(rec['total'], 1)) / 100.0
        dynamic = pass_rate * 0.5 + avg_score * 0.5

        # 混合：动态 60% + 静态 40%（样本越多，动态越可靠）
        blend = min(0.6, rec['total'] / 20 * 0.6)
        return dynamic * blend + static * (1 - blend)

    def to_dict(self) -> dict:
        """导出所有权重（供前端展示）。"""
        result = {}
        for agent_id, caps in self._records.items():
            result[agent_id] = {}
            for cap, rec in caps.items():
                result[agent_id][cap] = {
                    'total': rec['total'],
                    'pass_rate': round(
                        rec['passed'] / max(rec['total'], 1), 2,
                    ),
                    'weight': round(self.get_weight(agent_id, cap), 2),
                }
        return result


class AgentRegistry:
    """Agent 注册与能力匹配。动态评分 + 熔断 + 重试上限 + 真实 executor。

    executor 签名： fn(prompt: str, caps: list[str], extra: dict) -> str
    返回纯文本回复，失败时抛异常。
    """

    MAX_RETRIES = 3  # 每个任务最多重试次数

    def __init__(self):
        self._agents = {}
        self._retries = {}
        self._lock = threading.Lock()
        self.tracker = ProficiencyTracker()

    def register(self, agent_id, name, capabilities,
                 cost=0, latency_ms=0, reliability=0.9,
                 endpoint=None, preferred_tasks=None,
                 executor=None):
        """注册一个 Agent。"""
        with self._lock:
            self._agents[agent_id] = {
                'id': agent_id,
                'name': name,
                'capabilities': set(capabilities),
                'cost': cost,
                'latency_ms': latency_ms,
                'reliability': reliability,
                'endpoint': endpoint,
                'preferred_tasks': preferred_tasks or [],
                'online': True,
                'executor': executor,
                'success_count': 0,
                'fail_count': 0,
                'consecutive_fails': 0,
            }

    def run(self, agent_id, prompt, capabilities=None, extra=None):
        """执行一个 Agent。失败时自动标记并抛出。

        Returns:
            str: Agent 的纯文本回复
        """
        with self._lock:
            a = self._agents.get(agent_id)
        if not a:
            raise ValueError(f'未知 Agent: {agent_id}')
        if not a['online']:
            raise RuntimeError(f'Agent {agent_id} 已熔断下线')
        executor = a.get('executor')
        if not executor:
            raise RuntimeError(f'Agent {agent_id} 没有可用 executor（仅注册了元数据）')
        try:
            reply = executor(prompt, capabilities or [], extra or {})
            self.record_result(agent_id, True)
            return reply
        except Exception as exc:  # noqa: BLE001
            self.record_result(agent_id, False)
            logger.warning('Agent %s 执行失败: %s', agent_id, exc)
            raise

    def unregister(self, agent_id):
        with self._lock:
            self._agents.pop(agent_id, None)

    def record_result(self, agent_id, success, capability=None, score=0.0):
        """记录执行结果，更新动态评分 + 熔断 + 权重追踪。"""
        with self._lock:
            if agent_id not in self._agents:
                return
            a = self._agents[agent_id]
            if success:
                a['success_count'] += 1
                a['consecutive_fails'] = 0
            else:
                a['fail_count'] += 1
                a['consecutive_fails'] = a.get('consecutive_fails', 0) + 1
            total = a['success_count'] + a['fail_count']
            if total > 0:
                a['reliability'] = a['success_count'] / total
            if a['consecutive_fails'] >= 3:
                a['online'] = False
                logger.info('Agent %s 熔断下线（连续 3 次失败）', agent_id)

        # 更新权重追踪器（capability 粒度）
        if capability:
            self.tracker.record(agent_id, capability, success, score)

    def set_online(self, agent_id, online=True):
        with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id]['online'] = online

    def _retry_count(self, task_id):
        return self._retries.get(task_id, 0)

    def _inc_retry(self, task_id):
        self._retries[task_id] = self._retries.get(task_id, 0) + 1
        return self._retries[task_id]

    def match(self, required_capabilities, prefer_free=True, task_id=None):
        """按能力匹配最佳 Agent。"""
        if task_id and self._retry_count(task_id) >= self.MAX_RETRIES:
            return None

        required = set(required_capabilities)

        with self._lock:
            candidates = [
                a for a in self._agents.values()
                if a['online'] and required.issubset(a['capabilities'])
            ]

        if not candidates:
            return None

        # 评分（越低越好）：加权 Proficiency + reliability + latency + cost
        def score(a):
            # 1. 能力权重：每个所需能力的 tracker 权重之和 / 能力数（越高越好 → 取负）
            prof_sum = 0.0
            for cap in required:
                prof_sum += self.tracker.get_weight(a['id'], cap)
            prof_avg = prof_sum / max(len(required), 1)
            # 2. 综合评分（加权）
            base = (-prof_avg * 600  # 能力权重最重要
                    + -a['reliability'] * 300
                    + a['latency_ms'] * 0.05
                    + a['cost'] * 50)
            # 免费作为破平器
            if prefer_free and a['cost'] == 0:
                base -= 50
            return base

        best = min(candidates, key=score)
        logger.debug('match caps=%s -> chose %s (%s)',
                     required_capabilities, best['id'], best['name'])
        return best

    def list_all(self):
        with self._lock:
            return [
                {'id': a['id'], 'name': a['name'],
                 'capabilities': list(a['capabilities']),
                 'online': a['online'], 'cost': a['cost']}
                for a in self._agents.values()
            ]

    def find_by_capability(self, capability):
        with self._lock:
            return [
                a for a in self._agents.values()
                if capability in a['capabilities'] and a['online']
            ]

    def status(self):
        return {
            'agents': len(self._agents),
            'online': sum(1 for a in self._agents.values() if a['online']),
        }


# ── 预注册 Agent ─────────────────────────────────────────────────────

def seed_defaults(registry, llm_caller=None, image_caller=None):
    """注册默认 Agent。

    关键升级：给核心 Agent 绑定真实 executor，而不是只有元数据。

    Args:
        registry: AgentRegistry 实例
        llm_caller: 签名 fn(system_prompt: str, user_prompt: str,
                    prefer_free=True, task_type='text') -> str
                    调用文本模型的统一入口；传 None 时该 Agent 仅有元数据。
        image_caller: 签名 fn(prompt: str) -> str(图片URL或描述)
    """

    # Agnes Text —— 免费模型，主聊天
    from config import OWNER_NAME as _owner_name

    def _agnes_text_exec(prompt, caps, extra):
        if not llm_caller:
            raise RuntimeError('未配置 LLM caller（请检查 AGNES_API_KEY）')
        sys_prompt = extra.get('system', '') or (
            f'你是零，一款面向{_owner_name}（主人）的智能助手。'
            '中文回复，简洁但信息完整。'
            '使用 Markdown 格式组织长回答，代码用 ``` 包裹。'
        )
        reply = llm_caller(messages=[
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': prompt},
        ], prefer_free=True, task_type='text', agent_id='agnes_text')
        if not reply or reply.startswith('['):
            raise RuntimeError(f'Agnes 返回无效: {reply}')
        return reply

    # DeepSeek Reasonix —— 更适合复杂推理/代码
    def _reasonix_exec(prompt, caps, extra):
        if not llm_caller:
            raise RuntimeError('未配置 LLM caller')
        sys_prompt = extra.get('system', '') or (
            '你是 Reasonix，擅长代码生成、调试和复杂推理。'
            f'当前用户是{_owner_name}。'
            '中文回复。代码必须完整可运行，必要时给出分步解释。'
        )
        # prefer_free=False 让 call_llm 走 DeepSeek 通道
        reply = llm_caller(messages=[
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': prompt},
        ], prefer_free=False, task_type='reasoning', agent_id='reasonix')
        if not reply or reply.startswith('['):
            raise RuntimeError(f'Reasonix 返回无效: {reply}')
        return reply

    # Agnes Image —— 生图（通过 image_generate 工具）
    def _agnes_image_exec(prompt, caps, extra):
        try:
            from action.tools import execute as _tool_exec
            result = _tool_exec('image_generate', {'prompt': prompt})
            if result.ok:
                data = result.data if isinstance(result.data, dict) else {}
                img_url = data.get('url', '')
                if img_url:
                    return f'🖼️ 已生成图片:\n{img_url}'
                return '生图完成但未获取到 URL'
            err_msg = result.error.message if result.error else '未知错误'
            raise RuntimeError(f'生图失败: {err_msg}')
        except Exception as exc:
            raise RuntimeError(f'Agnes Image 错误: {exc}')

    # Tavily Search —— web 搜索（复用 tool_execute）
    def _tavily_exec(prompt, caps, extra):
        try:
            from action.tools import execute as _tool_exec
            result = _tool_exec('web_search', {'query': prompt})
            if result.ok:
                data = result.data
                return str(data if isinstance(data, str) else data)[:3000]
            err_msg = result.error.message if result.error else '未知原因'
            return f'搜索失败: {err_msg}'
        except Exception as exc:
            raise RuntimeError(f'search tool error: {exc}')

    # --- 注册 ---
    registry.register(
        'agnes_text', 'Agnes 2.0 Flash',
        capabilities=['chat', 'reasoning', 'code_generation',
                       'translation', 'summarization'],
        cost=0, latency_ms=1200, reliability=0.82,
        endpoint=f'agnes_api://{MODEL_NAMES["agnes_text"]}',
        executor=_agnes_text_exec,
    )

    registry.register(
        'reasonix', 'Reasonix (DeepSeek)',
        capabilities=['code_generation', 'code_review', 'debugging',
                       'file_ops', 'search', 'reasoning', 'chat'],
        cost=0.01, latency_ms=2200, reliability=0.9,
        endpoint='deepseek_api',
        executor=_reasonix_exec,
    )

    registry.register(
        'agnes_image', 'Agnes Image 2.1',
        capabilities=['image_generation', 'image_editing'],
        cost=0, latency_ms=5000, reliability=0.72,
        endpoint=f'agnes_api://{MODEL_NAMES["agnes_image"]}',
        executor=_agnes_image_exec,
    )

    registry.register(
        'tavily', 'Tavily Search',
        capabilities=['search', 'web_research'],
        cost=0, latency_ms=800, reliability=0.95,
        endpoint='tavily_api',
        executor=_tavily_exec,
    )

    # 占位：龙虾暂未接入真实后端，保留元数据
    registry.register(
        'longxia', '龙虾 (OpenClaw)',
        capabilities=['visual_design', 'browser_control', 'canvas',
                       'image_generation', 'voice', 'phone_control',
                       'chat', 'search'],
        cost=0, latency_ms=3000, reliability=0.0,
        endpoint='openclaw agent --agent main --message "{task}" --json',
        preferred_tasks=['design', 'image', 'voice', 'browser'],
        executor=None,
    )

    # ── 注册静态基准权重（来自公开 benchmark） ──
    registry.tracker.set_static('agnes_text', {
        'code_generation': 0.72, 'code_review': 0.68, 'debugging': 0.65,
        'reasoning': 0.70, 'chat': 0.76, 'translation': 0.74,
        'summarization': 0.75, 'search': 0.0,
    })
    registry.tracker.set_static('reasonix', {
        'code_generation': 0.87, 'code_review': 0.82, 'debugging': 0.84,
        'reasoning': 0.85, 'chat': 0.78, 'translation': 0.75,
        'summarization': 0.76, 'search': 0.0, 'file_ops': 0.70,
    })
    registry.tracker.set_static('agnes_image', {
        'image_generation': 0.70, 'image_editing': 0.60,
    })
    registry.tracker.set_static('tavily', {
        'search': 0.95, 'web_research': 0.92,
    })
