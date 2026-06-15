"""零 · Agent 注册表
===================
按能力(capability)匹配Agent，不是按名字叫人。

v2: 每个Agent声明自己能做什么，中控按需匹配。
"""

import threading


class AgentRegistry:
    """Agent 注册与能力匹配。v2: 动态评分 + 熔断 + 重试上限"""
    
    MAX_RETRIES = 3  # 每个任务最多重试次数（Agnes: 防止重试风暴）
    """Agent 注册与能力匹配。
    
    每个 Agent 声明自己的 capabilities、成本、延迟、可靠性。
    中控通过 match(task_requirements) 找到最合适的 Agent。
    """
    
    def __init__(self):
        self._agents = {}   # {agent_id: AgentInfo}
        self._retries = {}  # {task_id: count} 重试计数
        self._lock = threading.Lock()
    
    def register(self, agent_id, name, capabilities, 
                 cost=0, latency_ms=0, reliability=0.9,
                 endpoint=None, preferred_tasks=None,
                 executor=None):
        """注册一个 Agent
        
        Args:
            agent_id: 唯一标识
            name: 显示名
            capabilities: 能力标签列表，如 ['code_generation', 'file_ops']
            cost: 每次调用成本（0=免费）
            latency_ms: 平均延迟
            reliability: 可靠性 0-1
            endpoint: 调用地址（HTTP URL 或 CLI 命令模板）
            preferred_tasks: 偏好的任务类型
        """
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
                'executor': executor,  # v2: Agent自带执行方法（解耦_call_agent）
            }
    
    def unregister(self, agent_id):
        with self._lock:
            self._agents.pop(agent_id, None)
    
    def record_result(self, agent_id, success):
        """记录执行结果，更新动态评分（GPT+Agnes建议）"""
        with self._lock:
            if agent_id in self._agents:
                a = self._agents[agent_id]
                a.setdefault('success_count', 0)
                a.setdefault('fail_count', 0)
                a.setdefault('consecutive_fails', 0)
                if success:
                    a['success_count'] += 1
                    a['consecutive_fails'] = 0
                else:
                    a['fail_count'] += 1
                    a['consecutive_fails'] = a.get('consecutive_fails', 0) + 1
                # 动态可靠性
                total = a['success_count'] + a['fail_count']
                a['reliability'] = a['success_count'] / total if total > 0 else a['reliability']
                # 熔断：连续失败3次 → 下线
                if a['consecutive_fails'] >= 3:
                    a['online'] = False
    
    def set_online(self, agent_id, online=True):
        with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id]['online'] = online
    
    def _retry_count(self, task_id):
        """获取任务重试次数"""
        return self._retries.get(task_id, 0)
    
    def _inc_retry(self, task_id):
        self._retries[task_id] = self._retries.get(task_id, 0) + 1
        return self._retries[task_id]
    
    def match(self, required_capabilities, prefer_free=True, task_id=None):
        """按能力匹配最佳 Agent。v2: 加重试上限检查
        
        Args:
            required_capabilities: 需要的能力标签
            prefer_free: 优先免费
            task_id: 任务ID（用于重试计数）
        
        Returns:
            agent_info dict or None
        """
        # 重试上限检查
        if task_id and self._retry_count(task_id) >= self.MAX_RETRIES:
            return None
        
        required = set(required_capabilities)
        candidates = []
        
        with self._lock:
            for agent_id, agent in self._agents.items():
                if not agent['online']:
                    continue
                # 能力匹配：Agent 必须具备所有要求的能力
                if required.issubset(agent['capabilities']):
                    candidates.append(agent)
        
        if not candidates:
            return None
        
        # 排序：免费优先 → 高可靠性 → 低延迟
        def score(a):
            free_bonus = -1000 if (prefer_free and a['cost'] == 0) else 0
            return free_bonus - a['reliability'] * 100 + a['latency_ms'] * 0.1
        
        candidates.sort(key=score)
        return candidates[0]
    
    def list_all(self):
        """列出所有 Agent"""
        with self._lock:
            return [
                {'id': a['id'], 'name': a['name'], 
                 'capabilities': list(a['capabilities']),
                 'online': a['online'], 'cost': a['cost']}
                for a in self._agents.values()
            ]
    
    def find_by_capability(self, capability):
        """找具备某项能力的所有 Agent"""
        with self._lock:
            return [
                a for a in self._agents.values()
                if capability in a['capabilities'] and a['online']
            ]
    
    def status(self):
        return {'agents': len(self._agents),
                'online': sum(1 for a in self._agents.values() if a['online'])}


# ── 预注册 Agent ──

def seed_defaults(registry):
    """注册默认 Agent"""
    registry.register(
        'reasonix', 'Reasonix (DeepSeek)',
        capabilities=['code_generation', 'code_review', 'debugging', 
                       'file_ops', 'search', 'reasoning', 'chat'],
        cost=0.01, latency_ms=2000, reliability=0.9,
        endpoint='http_reasonix_api',
    )
    
    registry.register(
        'longxia', '龙虾 (OpenClaw)',
        capabilities=['visual_design', 'browser_control', 'canvas',
                       'image_generation', 'voice', 'phone_control',
                       'chat', 'search'],
        cost=0, latency_ms=3000, reliability=0.85,
        endpoint='openclaw agent --agent main --message "{task}" --json',
        preferred_tasks=['design', 'image', 'voice', 'browser'],
    )
    
    registry.register(
        'agnes_text', 'Agnes 2.0 Flash',
        capabilities=['chat', 'reasoning', 'code_generation', 'translation'],
        cost=0, latency_ms=1200, reliability=0.8,
        endpoint='agnes_api://agnes-2.0-flash',
    )
    
    registry.register(
        'agnes_image', 'Agnes Image 2.1',
        capabilities=['image_generation', 'image_editing'],
        cost=0, latency_ms=5000, reliability=0.75,
        endpoint='agnes_api://agnes-image-2.1-flash',
    )
    
    registry.register(
        'tavily', 'Tavily Search',
        capabilities=['search', 'web_research'],
        cost=0, latency_ms=800, reliability=0.95,
        endpoint='tavily_api',
        executor=lambda desc, caps: __import__('action.tools', fromlist=['execute']).execute('web_search', {'query': desc}) or {'success': True, 'output': '搜索完成'}
    )
