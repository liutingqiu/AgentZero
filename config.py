"""零 · 集中配置

所有路径 / API 地址 / 密钥 / 默认参数集中在这里。
解决：原来多处散写 BASE、sys.path.insert、keyring 在导入期执行等问题。

个人化配置 -> personal_config.json（被 .gitignore）
"""

import os
import sys
import socket
import logging
import threading
import webbrowser


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

# 额外路径（从环境变量 ZERO_EXTRA_PATHS 读取，分号分隔）
_EXTRA_PATHS = os.environ.get('ZERO_EXTRA_PATHS', '').strip()
if _EXTRA_PATHS:
    for _p in _EXTRA_PATHS.split(';'):
        _p = _p.strip()
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(1, _p)


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
    """LLM API 地址。优先环境变量，否则回退默认值。"""
    url = os.environ.get('LLM_API_URL', '').strip()
    if url:
        return url
    # 旧 secure_config 兼容（已废弃，v2 移除）
    try:
        from secure_config import get_api_url as _fallback  # noqa: WPS433
        return _fallback()
    except Exception:
        return 'https://api.deepseek.com/v1/chat/completions'


def get_api_key() -> str:
    key = os.environ.get('LLM_API_KEY', '').strip()
    if key:
        return key
    # 旧 secure_config 兼容（已废弃，v2 移除）
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

# 端口自增：默认端口被占用时自动尝试下一个
def find_available_port(host=HTTP_HOST, start=HTTP_PORT, max_attempts=10):
    for port in range(start, start + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            continue
    raise RuntimeError(f'无法找到可用端口（{start}~{start + max_attempts}）')


def open_browser(url):
    """延迟 1.5 秒后在默认浏览器打开 URL。"""
    def _open():
        import time
        time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


# Agnes API 地址（通过环境变量可覆盖，不覆盖则用默认值）
AGNES_API_BASE = os.environ.get('AGNES_API_BASE', 'https://apihub.agnes-ai.com') or 'https://apihub.agnes-ai.com'
AGNES_API_URL = f'{AGNES_API_BASE}/v1/chat/completions'
AGNES_IMAGE_URL = f'{AGNES_API_BASE}/v1/images/generations'

# 集中模型名称定义
MODEL_NAMES = {
    'agnes_text':    os.environ.get('ZERO_MODEL_AGNES_TEXT',    'agnes-2.0-flash'),
    'agnes_image':   os.environ.get('ZERO_MODEL_AGNES_IMAGE',   'agnes-image-2.1-flash'),
    'agnes_video':   os.environ.get('ZERO_MODEL_AGNES_VIDEO',   'agnes-video-v2.0'),
    'deepseek':      os.environ.get('ZERO_MODEL_DEEPSEEK',      'deepseek-chat'),
    'gpt4o':         os.environ.get('ZERO_MODEL_GPT4O',         'gpt-4o'),
    'gpt4o_mini':    os.environ.get('ZERO_MODEL_GPT4O_MINI',    'gpt-4o-mini'),
}

# 用户名称（用于 Agent prompt 中的称呼）
OWNER_NAME = os.environ.get('OWNER_NAME', 'User') or 'User'

# 默认 system prompt 身份（可通过环境变量覆盖）
SYSTEM_IDENTITY = os.environ.get(
    'ZERO_SYSTEM_IDENTITY',
    f'你是零，{OWNER_NAME}的智能助手。',
) or f'你是零，{OWNER_NAME}的智能助手。'
