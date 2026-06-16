"""零 · 集中配置

所有路径 / API 地址 / 密钥 / 默认参数集中在这里。
解决：原来多处散写 BASE、sys.path.insert、keyring 在导入期执行等问题。
"""

import os
import sys
import logging
import threading


# ── 路径 ──────────────────────────────────────────────────────────────
ZERO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ZERO_ROOT, 'data')
SANDBOX_DIR = os.path.join(DATA_DIR, 'sandbox')
MEMORY_DB = os.path.join(DATA_DIR, 'memory.sqlite')
KANBAN_DB = os.path.join(DATA_DIR, 'kanban.db')
BEHAVIOR_FP = os.path.join(DATA_DIR, 'behavior_fingerprint.json')
SESSION_STATE = os.path.join(DATA_DIR, 'session_state.json')

for _d in (DATA_DIR, SANDBOX_DIR):
    os.makedirs(_d, exist_ok=True)

# 确保 zero 本身在 sys.path 最前，覆盖同名模块冲突
if ZERO_ROOT not in sys.path:
    sys.path.insert(0, ZERO_ROOT)

# agent-system 路径（若存在则追加，不存在不报错）
_AGENT_SYS = os.path.join(os.path.dirname(ZERO_ROOT), 'agent-system')
if os.path.isdir(_AGENT_SYS) and _AGENT_SYS not in sys.path:
    sys.path.insert(1, _AGENT_SYS)


# ── 日志 ──────────────────────────────────────────────────────────────
_LOG_INIT_LOCK = threading.Lock()
_LOG_INITIALIZED = False


def get_logger(name='zero'):
    """获取带时间戳的 logger。初始化一次。"""
    global _LOG_INITIALIZED
    with _LOG_INIT_LOCK:
        if not _LOG_INITIALIZED:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%H:%M:%S',
            )
            _LOG_INITIALIZED = True
    return logging.getLogger(name)


# ── 密钥（惰性获取，避免导入期失败） ────────────────────────────────
def _get_secret(service: str, entry: str, env_key: str) -> str:
    """按「环境变量 → keyring」顺序取密钥。两者都失败时返回空串。"""
    val = os.environ.get(env_key, '').strip()
    if val:
        return val
    try:
        import keyring  # noqa: WPS433
        return keyring.get_password(service, entry) or ''
    except Exception:
        # Windows 无 GUI session / 无 keyring backend 时会抛异常
        return ''


def get_agnes_key() -> str:
    return _get_secret('AGNES', 'KEY', 'AGNES_API_KEY')


def get_api_url() -> str:
    """DeepSeek/其他模型 API 地址。优先环境变量，否则回退 secure_config 模块。"""
    url = os.environ.get('LLM_API_URL', '').strip()
    if url:
        return url
    try:
        from secure_config import get_api_url as _fallback  # noqa: WPS433
        return _fallback()
    except Exception:
        return 'https://api.deepseek.com/v1/chat/completions'


def get_api_key() -> str:
    key = os.environ.get('LLM_API_KEY', '').strip()
    if key:
        return key
    try:
        from secure_config import get_api_key as _fallback  # noqa: WPS433
        return _fallback()
    except Exception:
        return ''


# ── HTTP 服务 ─────────────────────────────────────────────────────────
HTTP_HOST = os.environ.get('ZERO_HOST', '127.0.0.1')
HTTP_PORT = int(os.environ.get('ZERO_PORT', '5052'))
UNLOCK_DURATION_SECONDS = int(
    os.environ.get('ZERO_UNLOCK_SECONDS', '7200'),
)  # 2 小时

# Agnes API 固定地址（多文件重复，集中到一处）
AGNES_API_URL = 'https://apihub.agnes-ai.com/v1/chat/completions'
AGNES_IMAGE_URL = 'https://apihub.agnes-ai.com/v1/images/generations'
