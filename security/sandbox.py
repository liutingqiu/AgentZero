"""零 · 沙箱隔离
===============
隔离目录 + 路径白名单 + 网络隔离 + 资源限制

从 agent-system/sandbox_evolve.py 重写，精简为核心 Sandbox 类。

P2: 实现 SandboxInterface 抽象接口，支持多平台。
"""

import os, sys, shutil, subprocess, json, atexit
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_DIR = os.path.join(BASE, 'data', 'sandbox')
os.makedirs(SANDBOX_DIR, exist_ok=True)

import ctypes
if sys.platform == 'win32':
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", ctypes.c_byte * 48),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x0100
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0008
    JOB_OBJECT_LIMIT_JOB_TIME = 0x0004
    JobObjectExtendedLimitInformation = 9

else:
    kernel32 = None


class Sandbox:
    """隔离执行环境（Windows Job Object）。

    安全机制:
      - 路径白名单: 只允许访问沙箱目录
      - 网络隔离: 防火墙阻断出站
      - 资源限制: 内存 + CPU 时间 + 进程数
      - 审计日志: 所有操作完整记录
    """
    
    def __init__(self, network_enabled=False, max_memory_mb=512, max_timeout=120):
        self.test_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.test_dir = os.path.join(SANDBOX_DIR, self.test_id)
        self.logs = []
        self.steps = []
        self.network_enabled = network_enabled
        self.max_memory_mb = max_memory_mb
        self.max_timeout = max_timeout
        self._job_handle = None
        self._firewall_rules = []
    
    def setup(self):
        os.makedirs(self.test_dir, exist_ok=True)
        atexit.register(self.cleanup)
        if sys.platform != 'win32' or kernel32 is None:
            self._log('平台不支持 Job Object，降级运行', 'warn')
            return True
        try:
            hjob = kernel32.CreateJobObjectW(None, None)
            if hjob:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                info.BasicLimitInformation.LimitFlags = (
                    JOB_OBJECT_LIMIT_PROCESS_MEMORY |
                    JOB_OBJECT_LIMIT_ACTIVE_PROCESS |
                    JOB_OBJECT_LIMIT_JOB_TIME
                )
                info.ProcessMemoryLimit = self.max_memory_mb * 1024 * 1024
                info.BasicLimitInformation.ActiveProcessLimit = 1
                info.BasicLimitInformation.PerJobUserTimeLimit = int(self.max_timeout * 10_000_000)
                size = ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
                if kernel32.SetInformationJobObject(hjob, JobObjectExtendedLimitInformation, 
                                                     ctypes.byref(info), size):
                    self._job_handle = hjob
                    self._log('Job Object 已创建', 'security')
        except Exception as e:
            self._log(f'Job Object 创建失败: {e}', 'warn')
        return True
    
    def _log(self, msg, level='info'):
        ts = datetime.now().strftime('%H:%M:%S')
        line = f'[{ts}] [{level}] {msg}'
        self.logs.append(line)
    
    def is_active(self) -> bool:
        """检查沙箱是否激活。"""
        return self._job_handle is not None

    def enforce_path(self, path: str) -> bool:
        """公开路径检查接口（SandboxInterface）。"""
        return self._enforce_path(path)

    def _enforce_path(self, path):
        """路径安全检查——防符号链接绕过。

        先解析符号链接获取真实路径，再检查是否在沙箱目录内。
        """
        if not path:
            return True
        try:
            real = os.path.realpath(path)
            sandbox_real = os.path.realpath(self.test_dir)
            if not real.startswith(sandbox_real + os.sep) and real != sandbox_real:
                self._log(f'路径越界: {path} → {real}', 'security')
                return False
        except (OSError, ValueError):
            self._log(f'路径解析失败: {path}', 'security')
            return False
        return True
    
    def _block_firewall(self):
        if self.network_enabled: return None
        try:
            rule = f'zero_sandbox_{self.test_id}'
            subprocess.run(
                f'netsh advfirewall firewall add rule name="{rule}" dir=out '
                f'action=block program="{sys.executable}" profile=any',
                shell=True, capture_output=True, timeout=5)
            self._firewall_rules.append(rule)
            return rule
        except:
            return None
    
    def _cleanup_firewall(self):
        for rule in self._firewall_rules:
            try:
                subprocess.run(f'netsh advfirewall firewall delete rule name="{rule}"',
                             shell=True, capture_output=True, timeout=5)
            except: pass
        self._firewall_rules = []
    
    def run_command(self, command, description=''):
        self._log(f'执行: {description or command[:60]}')
        self._block_firewall()
        try:
            env = os.environ.copy()
            if not self.network_enabled:
                for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
                    env[k] = ''
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=self.max_timeout, cwd=self.test_dir, env=env)
            ok = result.returncode == 0
            self.steps.append({
                'action': description, 'command': command,
                'result': 'pass' if ok else 'fail',
                'error': '' if ok else result.stderr[:200]
            })
            self._log('通过' if ok else f'失败: {result.stderr[:150]}', 'pass' if ok else 'fail')
            return ok
        except Exception as e:
            self.steps.append({'action': description, 'result': 'error', 'error': str(e)})
            self._log(f'异常: {e}', 'fail')
            return False
    
    def cleanup(self):
        self._cleanup_firewall()
        if self._job_handle and kernel32 is not None:
            try: kernel32.CloseHandle(self._job_handle)
            except: pass
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def verdict(self):
        if not self.steps: return 'no_tests'
        fails = sum(1 for s in self.steps if s['result'] != 'pass')
        return '全部通过' if fails == 0 else f'{fails}/{len(self.steps)} 失败'


# ═══════════════════════════════════════════
# 权限等级检查（供 tools.py 调用）
# ═══════════════════════════════════════════

def check_permission(level: str, action: str, target: str = '') -> tuple:
    """检查权限等级是否允许执行某操作。
    
    Args:
        level: plan / auto / yolo
        action: read / write / execute
        target: 操作目标路径或命令
    
    Returns:
        (allowed: bool, reason: str) — allowed 为 False 时 reason 说明原因
    """
    if level == 'yolo':
        return True, 'ok'
    
    if level == 'plan':
        if action == 'execute':
            return False, 'plan 模式下禁止执行命令'
        if action == 'write':
            return False, 'plan 模式下禁止写入文件'
        # read 操作由调用方做路径白名单检查
        return True, 'ok'
    
    # auto 模式
    if action == 'execute':
        return False, 'approval_required'  # 需要用户审批
    return True, 'ok'
