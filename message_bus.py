"""零 · 消息总线 (MessageBus)
================================
所有模块通信的唯一通道。发布/订阅模式。
+ 健康检查 + 应急独立模式

审查: DeepSeek 初版 → GPT-4o 提7个问题 → DeepSeek 全部修复

用法:
  bus = get_bus()  # 全局单例，线程安全
  bus.subscribe('user_message', handler_func)
  bus.publish({'type': 'user_message', 'source': 'http', 'data': '你好'})
"""

import time, threading, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime


# ── 任务状态机事件类型（v3: 中控台架构）──
TASK_EVENTS = [
    'task.created',        # 任务创建
    'task.assigned',       # 分配给Agent
    'task.waiting',        # 等待依赖（GPT+Agnes: DAG场景必需）
    'task.started',        # 开始执行
    'task.progress',       # 执行中（可选进度）
    'task.completed',      # 成功完成
    'task.failed',         # 执行失败
    'task.timeout',        # 超时
    'task.cancelled',      # 被取消
    'task.reviewing',      # Reviewer 验证中
    'task.review_passed',  # 验证通过（终态）
    'task.review_failed',  # 验证不通过→回炉
    'task.retrying',       # 重试中
    'task.rewritten',      # 任务被重新拆解
    'task.rollback',       # 回滚中（DAG场景）
]

class Event:
    """统一事件格式。
    
    v2: ID 改为 uuid4（GPT-4o: 微秒时间戳并发可能重复）
    """
    def __init__(self, event_type, source, data, priority='normal'):
        self.id = f'evt_{uuid.uuid4().hex[:12]}'
        self.type = event_type
        self.source = source
        self.data = data
        self.priority = priority
        self.time = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'id': self.id, 'type': self.type, 'source': self.source,
            'data': self.data, 'time': self.time, 'priority': self.priority
        }
    
    def __repr__(self):
        return f'Event({self.type} from {self.source}, {self.priority})'


class MessageBus:
    """统一消息总线。
    
    v2 修复:
      - Event ID 用 uuid4 防重复
      - publish 校验 type 不为空
      - subscribe 防重复注册
      - 统计未处理事件
      - fallback_mode 双向通知
    """
    
    def __init__(self):
        self._subscribers = {}       # {event_type: [handler1, handler2, ...]}
        self._pending_requests = {}  # {request_id: threading.Event}
        self._request_results = {}   # {request_id: result}
        self._lock = threading.Lock()
        self._healthy = True
        self._event_count = 0
        self._error_count = 0
        self._unhandled_count = 0    # v2: 无订阅者的事件计数
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='bus')
        self._started_at = datetime.now().isoformat()
    
    # ── 发布/订阅 ──
    
    def publish(self, event_dict):
        """发布事件。支持 dict 或 Event 对象。
        
        v2: 校验 type 不为空（GPT-4o: 空事件导致后续处理异常）
             handler 列表在锁内 .copy()，防止遍历时被修改
        """
        if isinstance(event_dict, Event):
            event = event_dict
            event_dict = event.to_dict()
        else:
            event_type = event_dict.get('type', '')
            if not event_type:  # v2: 拒绝空 type
                raise ValueError("Event missing 'type' field")
            event = Event(
                event_type,
                event_dict.get('source', 'unknown'),
                event_dict.get('data', {}),
                event_dict.get('priority', 'normal')
            )
            event_dict = event.to_dict()
        
        with self._lock:
            # .copy() 防遍历时被 subscribe/unsubscribe 修改
            handlers = self._subscribers.get(event.type, []).copy()
            self._event_count += 1
            if not handlers:
                self._unhandled_count += 1
        
        # v2: 线程池异步执行 handler（GPT-4o: 同步阻塞会影响其他模块）
        for handler in handlers:
            self._executor.submit(self._invoke_handler, handler, event_dict)
        
        return event_dict
    
    def _invoke_handler(self, handler, event_dict):
        """在线程池中执行单个 handler"""
        try:
            handler(event_dict)
        except Exception as e:
            self._error_count += 1
            print(f'[MessageBus] 处理器异常: {e}')
    
    def subscribe(self, event_type, handler):
        """订阅事件类型。
        
        v2: 防重复注册（GPT-4o: 同一 handler 可能多次被注册）
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if handler not in self._subscribers[event_type]:  # v2: 防重复
                self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type, handler):
        """取消订阅"""
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                except ValueError:
                    pass
    
    # ── 同步请求 ──
    
    def request(self, target, action, data=None, timeout=10):
        """向特定模块发同步请求（等待回复）
        
        注: 单机个人 Agent 场景下同步等待足够。
            被请求方应在自己的线程中处理，不在 publish 回调中阻塞。
        """
        request_id = f'req_{uuid.uuid4().hex[:8]}'
        event = threading.Event()
        
        with self._lock:
            self._pending_requests[request_id] = event
        
        self.publish({
            'type': f'request:{target}',
            'source': 'message_bus',
            'data': {'request_id': request_id, 'action': action, 'data': data or {}}
        })
        
        if event.wait(timeout):
            with self._lock:
                result = self._request_results.pop(request_id, None)
                self._pending_requests.pop(request_id, None)
            return result or {'status': 'error', 'error': 'empty response'}
        else:
            with self._lock:
                self._pending_requests.pop(request_id, None)
            return {'status': 'timeout', 'error': f'{action} 超时({timeout}s)'}
    
    def respond(self, request_id, result):
        """模块回复一个请求"""
        with self._lock:
            self._request_results[request_id] = result
            event = self._pending_requests.get(request_id)
        if event:
            event.set()
    
    # ── 健康检查 ──
    
    def health_check(self):
        """周期性自检，返回总线状态
        
        v2: 加 unhandled_events 统计（GPT-4o: 暴露未被处理的事件）
        """
        with self._lock:
            subscriber_count = sum(len(h) for h in self._subscribers.values())
            event_types = list(self._subscribers.keys())
            pending = len(self._pending_requests)
        
        status = {
            'healthy': self._healthy,
            'uptime_seconds': round(time.time() - 
                datetime.fromisoformat(self._started_at).timestamp(), 1),
            'events_total': self._event_count,
            'errors_total': self._error_count,
            'unhandled_events': self._unhandled_count,
            'subscriber_count': subscriber_count,
            'event_types': event_types,
            'pending_requests': pending,
        }
        
        if self._event_count > 0:
            error_rate = self._error_count / self._event_count
            if error_rate > 0.1:
                self._healthy = False
                status['warning'] = f'错误率 {error_rate:.1%}'
        
        return status
    
    def fallback_mode(self):
        """总线异常 → 广播 + 标记不健康。
        
        各模块收到 system/fallback_mode 事件后应自行降级。
        """
        self._healthy = False
        self.publish({
            'type': 'system',
            'source': 'message_bus',
            'data': {'action': 'fallback_mode'},
            'priority': 'critical'
        })
    
    # ── 生命周期 ──
    
    def start(self):
        self._healthy = True
        self._started_at = datetime.now().isoformat()
        return True
    
    def stop(self):
        self._healthy = False
        return True
    
    def status(self):
        return self.health_check()


# ── 全局单例（v2: 线程安全）──
_bus_instance = None
_bus_lock = threading.Lock()

class TaskStateMachine:
    """任务状态机——追踪每个任务的生命周期（v3）"""
    
    VALID_TRANSITIONS = {
        None:                  ['task.created'],
        'task.created':        ['task.assigned', 'task.cancelled'],
        'task.assigned':       ['task.started', 'task.waiting', 'task.cancelled'],
        'task.waiting':        ['task.started', 'task.cancelled'],
        'task.started':        ['task.progress', 'task.completed', 'task.failed', 'task.timeout', 'task.cancelled'],
        'task.progress':       ['task.progress', 'task.completed', 'task.failed', 'task.timeout', 'task.cancelled'],
        'task.failed':         ['task.retrying', 'task.rewritten', 'task.rollback'],
        'task.timeout':        ['task.retrying', 'task.cancelled'],
        'task.cancelled':      [],  # 终态
        'task.retrying':       ['task.started'],
        'task.rewritten':      ['task.created'],
        'task.rollback':       ['task.created'],
        'task.completed':      ['task.reviewing'],
        'task.reviewing':      ['task.review_passed', 'task.review_failed'],
        'task.review_passed':  [],  # 终态
        'task.review_failed':  ['task.retrying', 'task.rewritten'],
    }
    
    def __init__(self, bus):
        self.bus = bus
        self._states = {}  # {task_id: current_state}
    
    def transition(self, task_id, new_state):
        current = self._states.get(task_id)
        allowed = self.VALID_TRANSITIONS.get(current, [])
        if current is None and new_state != 'task.created':
            return False  # 初始状态只能是 created
        if new_state not in allowed:
            return False
        self._states[task_id] = new_state
        self.bus.publish({
            'type': new_state,
            'source': 'task_state_machine',
            'data': {'task_id': task_id, 'from': current, 'to': new_state},
            'priority': 'normal'
        })
        return True
    
    def get_state(self, task_id):
        return self._states.get(task_id)
    
    def get_all(self):
        return dict(self._states)


def get_bus():
    """获取全局 MessageBus 实例（线程安全）"""
    global _bus_instance
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:  # 双重检查
                _bus_instance = MessageBus()
    return _bus_instance
