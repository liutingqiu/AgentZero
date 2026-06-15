"""零 · 模块基类
===============
所有模块遵循的接口契约。

v2: + fallback_mode 订阅（GPT-4o: 模块应响应总线降级事件）

用法:
  class MyModule(Module):
      def on_start(self): ...
      def on_stop(self): ...
      def on_fallback(self, event): ...  # 可选，总线异常时降级
"""


class Module:
    """所有模块的基类。
    
    生命周期: start → (运行) → stop
    异常降级: 收到 system/fallback_mode 事件 → on_fallback()
    """
    
    def __init__(self, name, bus):
        self.name = name
        self.bus = bus
        self._running = False
        self._fallback = False
    
    def start(self):
        """启动模块。
        
        先订阅总线降级事件，再调用子类 on_start()。
        on_start 抛异常 → _running 不设 True → 可安全重试。
        """
        if self._running:
            return True
        try:
            # 订阅降级通知
            self.bus.subscribe('system', self._on_system_event)
            self.on_start()
            self._running = True
            self.bus.publish({
                'type': 'system', 'source': self.name,
                'data': {'action': 'module_started'}, 'priority': 'low'
            })
            return True
        except Exception as e:
            print(f'[{self.name}] 启动失败: {e}')
            return False
    
    def stop(self):
        """停止模块。"""
        if not self._running:
            return True
        try:
            self.on_stop()
            self._running = False
            self.bus.publish({
                'type': 'system', 'source': self.name,
                'data': {'action': 'module_stopped'}, 'priority': 'low'
            })
            return True
        except Exception as e:
            print(f'[{self.name}] 停止异常: {e}')
            return False
    
    def status(self):
        """返回模块状态。"""
        base = {
            'name': self.name,
            'running': self._running,
            'fallback': self._fallback,
        }
        try:
            custom = self.on_status()
            if isinstance(custom, dict):
                base.update(custom)
        except Exception as e:
            base['error'] = str(e)
        return base
    
    # ── 内部：系统事件处理 ──
    
    def _on_system_event(self, event):
        """处理系统级事件（总线降级等）"""
        action = event.get('data', {}).get('action', '')
        if action == 'fallback_mode':
            self._fallback = True
            try:
                self.on_fallback(event)
            except Exception as e:
                print(f'[{self.name}] 降级处理异常: {e}')
    
    # ── 子类重写这些 ──
    
    def on_start(self):
        """子类重写：启动逻辑"""
        pass
    
    def on_stop(self):
        """子类重写：停止逻辑"""
        pass
    
    def on_status(self):
        """子类重写：返回自定义状态信息"""
        return {}
    
    def on_fallback(self, event):
        """子类重写：总线异常时的降级行为
        
        默认：什么也不做（模块继续运行，但失去总线通信能力）
        子类可重写为：切换到本地模式、暂停非关键功能等
        """
        pass
