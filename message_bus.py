"""零 · MessageBus（发布/订阅 + 请求响应）

修复要点：
  - 发布事件用有界队列，发布风暴不会吃爆内存
  - 处理器异常只记录，不吞进程级异常（KeyboardInterrupt/SystemExit 由上层处理）
  - 单例用 threading.Lock 双重检查，线程安全
  - 健康检查加未处理事件计数 + 队列积压数
"""

import threading
import time
import uuid
from datetime import datetime
from queue import Queue, Full

from config import get_logger

logger = get_logger('zero.bus')

# ── 全局配置 ──────────────────────────────────────────────────────────
_MAX_QUEUE_SIZE = 2048   # 最多积压事件数
_MAX_WORKERS = 4          # 工作线程数


# ── 任务状态机事件类型 ────────────────────────────────────────────────
TASK_EVENTS = [
    'task.created',        # 任务创建
    'task.assigned',       # 分配给 Agent
    'task.waiting',        # 等待依赖
    'task.started',        # 开始执行
    'task.progress',       # 执行中
    'task.completed',      # 成功完成
    'task.failed',         # 执行失败
    'task.timeout',        # 超时
    'task.cancelled',      # 被取消
    'task.reviewing',      # Reviewer 验证中
    'task.review_passed',  # 验证通过
    'task.review_failed',  # 验证不通过
    'task.retrying',       # 重试中
    'task.rewritten',      # 任务被重新拆解
    'task.rollback',       # 回滚
]


# ── Event ────────────────────────────────────────────────────────────
class Event:
    """统一事件格式。"""

    def __init__(self, event_type, source, data, priority='normal'):
        self.id = f'evt_{uuid.uuid4().hex[:12]}'
        self.type = event_type
        self.source = source
        self.data = data
        self.priority = priority
        self.time = datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'source': self.source,
            'data': self.data,
            'time': self.time,
            'priority': self.priority,
        }

    def __repr__(self):
        return f'Event({self.type} from {self.source}, {self.priority})'


# ── MessageBus ────────────────────────────────────────────────────────
class MessageBus:
    """发布/订阅总线。事件入有界队列，工作线程异步分发。"""

    def __init__(self, max_queue=_MAX_QUEUE_SIZE, max_workers=_MAX_WORKERS):
        self._subscribers: dict[str, list] = {}
        self._lock = threading.Lock()
        self._queue: Queue = Queue(maxsize=max_queue)
        self._event_count = 0
        self._dropped_count = 0
        self._error_count = 0
        self._unhandled_count = 0
        self._started_at = datetime.now().isoformat()
        self._healthy = True

        # 请求响应表
        self._pending_requests: dict[str, threading.Event] = {}
        self._request_results: dict[str, object] = {}

        # 启动工作线程
        self._threads = []
        for i in range(max_workers):
            t = threading.Thread(
                target=self._worker,
                name=f'bus-worker-{i}',
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    # ── 工作循环 ──────────────────────────────────────────────
    def _worker(self):
        while True:
            item = self._queue.get()  # block forever until new event
            if item is None:          # 哨兵：停止信号
                self._queue.task_done()
                break
            try:
                self._dispatch(item)
            except Exception as exc:  # noqa: BLE001
                self._error_count += 1
                logger.warning('dispatch %s failed: %s',
                               item.get('type', '?'), exc)
            finally:
                self._queue.task_done()

    def _dispatch(self, event_dict):
        """把一个事件派发给所有订阅者。"""
        event_type = event_dict.get('type', '')

        # 在锁内拿 handler 列表快照，避免遍历期间被修改
        with self._lock:
            handlers = list(self._subscribers.get(event_type, []))

        if not handlers:
            self._unhandled_count += 1
            return

        for handler in handlers:
            try:
                handler(event_dict)
            except Exception as exc:  # noqa: BLE001
                self._error_count += 1
                logger.warning('handler for %s error: %s', event_type, exc)

    # ── 发布/订阅 ────────────────────────────────────────────
    def publish(self, event_dict):
        """发布事件。队列满时丢弃低优先级事件，记录告警。"""
        if isinstance(event_dict, Event):
            event = event_dict
            event_dict = event.to_dict()
        else:
            event_type = event_dict.get('type', '')
            if not event_type:
                raise ValueError("Event missing 'type' field")
            event = Event(
                event_type,
                event_dict.get('source', 'unknown'),
                event_dict.get('data', {}),
                event_dict.get('priority', 'normal'),
            )
            event_dict = event.to_dict()

        priority = event_dict.get('priority', 'normal')

        try:
            self._queue.put_nowait(event_dict)
            with self._lock:
                self._event_count += 1
        except Full:
            # 队列满：critical 仍然强行放，其余丢弃
            if priority == 'critical':
                try:
                    self._queue.put(event_dict, timeout=1)
                    with self._lock:
                        self._event_count += 1
                except Full:
                    self._dropped_count += 1
                    logger.warning('critical event dropped (queue full): %s',
                                   event_dict.get('type'))
            else:
                self._dropped_count += 1
                if self._dropped_count % 50 == 0:
                    logger.warning(
                        '%d events dropped (queue full, size=%d)',
                        self._dropped_count, self._queue.qsize(),
                    )
        return event_dict

    def subscribe(self, event_type, handler):
        with self._lock:
            lst = self._subscribers.setdefault(event_type, [])
            if handler not in lst:
                lst.append(handler)

    def unsubscribe(self, event_type, handler):
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                except ValueError:
                    pass

    # ── 同步请求/响应 ───────────────────────────────────────
    def request(self, target, action, data=None, timeout=10):
        """向特定模块发同步请求，等待回复。"""
        req_id = f'req_{uuid.uuid4().hex[:8]}'
        event = threading.Event()
        with self._lock:
            self._pending_requests[req_id] = event

        self.publish({
            'type': f'request:{target}',
            'source': 'message_bus',
            'data': {'request_id': req_id, 'action': action,
                     'data': data or {}},
        })

        if event.wait(timeout):
            with self._lock:
                result = self._request_results.pop(req_id, None)
                self._pending_requests.pop(req_id, None)
            return result or {'status': 'error', 'error': 'empty response'}
        # 超时
        with self._lock:
            self._pending_requests.pop(req_id, None)
        return {'status': 'timeout',
                'error': f'{action} 超时({timeout}s)'}

    def respond(self, request_id, result):
        with self._lock:
            self._request_results[request_id] = result
            ev = self._pending_requests.get(request_id)
        if ev:
            ev.set()

    # ── 健康检查 ────────────────────────────────────────────
    def health_check(self):
        with self._lock:
            subscriber_count = sum(len(h) for h in self._subscribers.values())
            pending = len(self._pending_requests)
            events = self._event_count
            errors = self._error_count
            unhandled = self._unhandled_count
            dropped = self._dropped_count

        status = {
            'healthy': self._healthy,
            'uptime_seconds': round(
                time.time() - datetime.fromisoformat(
                    self._started_at).timestamp(), 1,
            ),
            'events_total': events,
            'errors_total': errors,
            'unhandled_events': unhandled,
            'dropped_events': dropped,
            'subscriber_count': subscriber_count,
            'event_types': list(self._subscribers.keys()),
            'pending_requests': pending,
            'queue_size': self._queue.qsize(),
        }
        if events and errors / events > 0.1:
            self._healthy = False
            status['warning'] = f'错误率 {errors / events:.1%}'
        return status

    def fallback_mode(self):
        """总线降级——广播 critical 事件。"""
        self._healthy = False
        self.publish({
            'type': 'system',
            'source': 'message_bus',
            'data': {'action': 'fallback_mode'},
            'priority': 'critical',
        })

    # ── 生命周期/状态 ───────────────────────────────────────
    def start(self):
        self._healthy = True
        self._started_at = datetime.now().isoformat()
        return True

    def stop(self):
        self._healthy = False
        # 发送哨兵信号让工作线程退出
        for _ in self._threads:
            self._queue.put(None)
        for t in self._threads:
            t.join(timeout=3)
        return True

    def status(self):
        return self.health_check()


# ── 任务状态机 ────────────────────────────────────────────────────────
class TaskStateMachine:
    """追踪每个任务的生命周期。"""

    VALID_TRANSITIONS = {
        None: ['task.created'],
        'task.created': ['task.assigned', 'task.cancelled'],
        'task.assigned': ['task.started', 'task.waiting', 'task.cancelled'],
        'task.waiting': ['task.started', 'task.cancelled'],
        'task.started': ['task.progress', 'task.completed', 'task.failed',
                         'task.timeout', 'task.cancelled'],
        'task.progress': ['task.progress', 'task.completed', 'task.failed',
                          'task.timeout', 'task.cancelled'],
        'task.failed': ['task.retrying', 'task.rewritten', 'task.rollback'],
        'task.timeout': ['task.retrying', 'task.cancelled'],
        'task.cancelled': [],
        'task.retrying': ['task.started'],
        'task.rewritten': ['task.created'],
        'task.rollback': ['task.created'],
        'task.completed': ['task.reviewing'],
        'task.reviewing': ['task.review_passed', 'task.review_failed'],
        'task.review_passed': [],
        'task.review_failed': ['task.retrying', 'task.rewritten'],
    }

    def __init__(self, bus):
        self.bus = bus
        self._states: dict[str, str] = {}
        self._lock = threading.Lock()

    def transition(self, task_id, new_state):
        with self._lock:
            current = self._states.get(task_id)
            allowed = self.VALID_TRANSITIONS.get(current, [])
            if current is None and new_state != 'task.created':
                return False
            if new_state not in allowed:
                logger.info(
                    'task %s invalid transition %s -> %s ignored',
                    task_id, current, new_state,
                )
                return False
            self._states[task_id] = new_state
        self.bus.publish({
            'type': new_state,
            'source': 'task_state_machine',
            'data': {'task_id': task_id, 'from': current, 'to': new_state},
            'priority': 'normal',
        })
        return True

    def get_state(self, task_id):
        with self._lock:
            return self._states.get(task_id)

    def get_all(self):
        with self._lock:
            return dict(self._states)


# ── 全局单例（线程安全） ──────────────────────────────────────────────
_bus_instance: MessageBus | None = None
_bus_lock = threading.Lock()


def get_bus():
    global _bus_instance
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:
                _bus_instance = MessageBus()
    return _bus_instance
