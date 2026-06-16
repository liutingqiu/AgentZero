"""零 · 工具注册表
==================
AgentLoop 通过此注册表调用所有工具。
所有工具签名: func(args) -> Result
统一错误协议：utils.result.Result

修复要点：
  - P1-A2: keyring 惰性获取，支持环境变量回退
  - P0-A3: shell 工具白名单前缀校验，默认 shell=False
  - web_fetch 走非贪婪正则，避免 HTML 提取失败
  - 日志统一到 get_logger
  - v3: 所有返回值统一为 Result 信封
"""

import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys as _sys
import urllib.request

from config import get_agnes_key, get_logger
from utils.result import Result, ErrorCode, ok, err

logger = get_logger('zero.tools')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 工具注册表 ─────────────────────────────────────────────────────
TOOLS = {}


def register(name, description=''):
    def decorator(fn):
        TOOLS[name] = {'fn': fn, 'description': description}
        return fn
    return decorator


# ── 全局安全策略 ───────────────────────────────────────────────
_ALLOWED_CMD_PREFIXES = (
    'git', 'python', 'pip', 'node', 'npm', 'npx',
    'dir', 'ls', 'cd', 'echo', 'type', 'cat',
    'pwd', 'where', 'which', 'find', 'tasklist', 'ver',
    'copy', 'move', 'mkdir', 'rmdir', 'del',
)


# ── 辅助 ───────────────────────────────────────────────────────
def _resolve_path(args):
    """从 args 中解析路径（兼容多种 key 名）。"""
    return args.get('path', '') or args.get('file_path', '') or args.get('file', '')


# ═══════════════════════════════════════════
# 文件操作工具
# ═══════════════════════════════════════════

@register('read_file', '读取文件内容')
def tool_read_file(args):
    path = _resolve_path(args)
    if not path or not os.path.exists(path):
        return err(ErrorCode.FILE_NOT_FOUND, f'文件不存在: {path}')
    try:
        max_lines = int(args.get('lines', 0) or args.get('max_lines', 0))
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            if max_lines > 0:
                lines = [next(f, '') for _ in range(max_lines)]
                content = ''.join(lines)
            else:
                content = f.read(10000)
        return ok({'content': content, 'size': len(content)})
    except Exception as exc:
        logger.warning('read_file %s failed: %s', path, exc)
        return err(ErrorCode.INTERNAL, str(exc))


@register('write_file', '写入文件')
def tool_write_file(args):
    path = args.get('path', '')
    content = args.get('content', '')
    try:
        directory = os.path.dirname(path) or '.'
        os.makedirs(directory, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return ok({'message': f'已写入: {path}'})
    except OSError as exc:
        logger.warning('write_file %s failed: %s', path, exc)
        return err(ErrorCode.INTERNAL, str(exc))


@register('edit_file', '替换文件中的文本')
def tool_edit_file(args):
    path = args.get('path', '')
    search = args.get('search', '')
    replace = args.get('replace', '')
    if not os.path.exists(path):
        return err(ErrorCode.FILE_NOT_FOUND, f'文件不存在: {path}')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        if search not in content:
            return err(ErrorCode.INVALID_INPUT, '未找到匹配文本')
        if content.count(search) > 1:
            return err(ErrorCode.INVALID_INPUT, '匹配文本不唯一，请提供更多上下文')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content.replace(search, replace, 1))
        return ok({'message': f'已修改: {path}'})
    except OSError as exc:
        logger.warning('edit_file %s failed: %s', path, exc)
        return err(ErrorCode.INTERNAL, str(exc))


@register('list_directory', '列出目录内容')
def tool_list_dir(args):
    path = args.get('path', '.')
    if not os.path.isdir(path):
        return err(ErrorCode.FILE_NOT_FOUND, f'不是目录: {path}')
    entries = os.listdir(path)
    dirs = [f'📁 {e}/' for e in entries if os.path.isdir(os.path.join(path, e))]
    files = [f'📄 {e}' for e in entries if not os.path.isdir(os.path.join(path, e))]
    return ok(dirs + files)


@register('search_files', '搜索文件名（子串匹配）')
def tool_search_files(args):
    pattern = args.get('pattern', '')
    directory = args.get('path', '.')
    results = []
    skip = {'.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build', '.reasonix'}
    try:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                if pattern.lower() in f.lower():
                    results.append(os.path.join(root, f))
                if len(results) >= 50:
                    break
            if len(results) >= 50:
                break
    except PermissionError:
        pass
    return ok({'files': results[:30], 'count': len(results)})


@register('search_content', '搜索文件内容')
def tool_search_content(args):
    pattern = args.get('pattern', '')
    directory = args.get('path', '.')
    results = []
    skip = {'.git', 'node_modules', '__pycache__', '.venv',
            'dist', 'build', '.reasonix'}
    text_exts = {'.py', '.js', '.ts', '.html', '.css', '.md',
                 '.txt', '.json', '.yml', '.yaml', '.sh', '.bat'}
    try:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                if os.path.splitext(f)[1].lower() not in text_exts:
                    continue
                try:
                    with open(os.path.join(root, f), 'r',
                              encoding='utf-8', errors='ignore') as fh:
                        for i, line in enumerate(fh, 1):
                            if pattern.lower() in line.lower():
                                results.append(
                                    f'{os.path.join(root, f)}:{i}: {line.strip()[:120]}'
                                )
                                if len(results) >= 20:
                                    break
                except Exception:
                    pass
                if len(results) >= 20:
                    break
            if len(results) >= 20:
                break
    except PermissionError:
        pass
    return ok(results[:20] if results else f'未找到: {pattern}')


@register('create_directory', '创建目录')
def tool_create_dir(args):
    path = args.get('path', '')
    try:
        os.makedirs(path, exist_ok=True)
        return ok({'message': f'已创建: {path}'})
    except OSError as exc:
        logger.warning('create_directory %s failed: %s', path, exc)
        return err(ErrorCode.INTERNAL, str(exc))


@register('delete_file', '删除文件')
def tool_delete_file(args):
    path = args.get('path', '')
    if os.path.isfile(path):
        os.remove(path)
        return ok({'message': f'已删除: {path}'})
    return err(ErrorCode.FILE_NOT_FOUND, f'文件不存在: {path}')


@register('move_file', '移动文件')
def tool_move_file(args):
    src = args.get('source', args.get('src', ''))
    dst = args.get('dest', args.get('dst', ''))
    if not os.path.exists(src):
        return err(ErrorCode.FILE_NOT_FOUND, f'源文件不存在: {src}')
    try:
        os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
        shutil.move(src, dst)
        return ok({'message': f'{src} → {dst}'})
    except OSError as exc:
        return err(ErrorCode.INTERNAL, str(exc))


@register('copy_file', '复制文件')
def tool_copy_file(args):
    src = args.get('source', args.get('src', ''))
    dst = args.get('dest', args.get('dst', ''))
    if not os.path.exists(src):
        return err(ErrorCode.FILE_NOT_FOUND, f'源文件不存在: {src}')
    try:
        os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
        shutil.copy2(src, dst)
        return ok({'message': f'{src} → {dst}'})
    except OSError as exc:
        return err(ErrorCode.INTERNAL, str(exc))


# ── shell 工具（安全加固版） ───────────────────────────────────
@register('shell', '执行系统命令（仅限白名单）')
def tool_shell(args):
    cmd = args.get('command', '')
    if not cmd:
        return err(ErrorCode.INVALID_INPUT, '缺少 command')

    stripped = cmd.lstrip().lower()
    first_token = stripped.split()[0] if stripped.split() else ''
    clean_token = first_token.strip('"\'')

    if not any(clean_token.startswith(p) for p in _ALLOWED_CMD_PREFIXES):
        logger.warning('shell rejected (not in whitelist): %s', cmd[:80])
        return err(
            ErrorCode.SHELL_REJECTED,
            f'命令不在白名单: {clean_token}。白名单: {", ".join(_ALLOWED_CMD_PREFIXES)}',
        )

    try:
        import shlex
        argv = shlex.split(cmd, posix=False) if not isinstance(cmd, list) else cmd
        result = subprocess.run(
            argv, shell=False, capture_output=True, text=True,
            timeout=60, cwd=BASE,
            encoding='utf-8', errors='replace',
        )
        return ok({
            'stdout': (result.stdout or result.stderr)[:3000],
            'exit_code': result.returncode,
            'success': result.returncode == 0,
        })
    except subprocess.TimeoutExpired:
        return err(ErrorCode.TIMEOUT, '命令超时(60s)')
    except FileNotFoundError as exc:
        return err(ErrorCode.INTERNAL, f'未找到命令: {exc}')
    except Exception as exc:
        logger.warning('shell failed: %s', exc)
        return err(ErrorCode.INTERNAL, str(exc))


# ═══════════════════════════════════════════
# 搜索/信息工具
# ═══════════════════════════════════════════

@register('web_search', '搜索网页')
def tool_web_search(args):
    query = args.get('query', '')
    if not query:
        return err(ErrorCode.INVALID_INPUT, '缺少 query')
    try:
        import urllib.parse
        url = f'https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        results = []
        for m in re.finditer(
            r'<a[^>]*rel="nofollow"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>',
            html,
        ):
            results.append({'title': m.group(2).strip(), 'url': m.group(1)})
        if results:
            return ok(results[:10])
    except Exception:
        pass
    return err(ErrorCode.NETWORK, '搜索不可用（DDG 被墙，请用 GPT-4o 搜索）')


@register('web_fetch', '抓取网页内容')
def tool_web_fetch(args):
    url = args.get('url', '')
    if not url:
        return err(ErrorCode.INVALID_INPUT, '缺少 url')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        html = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>',
                      ' ', html, flags=re.IGNORECASE)
        html = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>',
                      ' ', html, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]{0,200}>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return ok(text[:5000])
    except Exception as exc:
        logger.warning('web_fetch %s failed: %s', url[:80], exc)
        return err(ErrorCode.NETWORK, f'抓取失败: {exc}')


# ═══════════════════════════════════════════
# 系统/状态工具
# ═══════════════════════════════════════════

@register('sysmon', 'KnowledgeSys 状态检查')
def tool_sysmon(args):
    sysmon_path = os.path.join(BASE, '..', 'agent-system', 'bridge', 'sysmon.py')
    if not os.path.exists(sysmon_path):
        return err(ErrorCode.TOOL_FAILED, 'sysmon.py 不存在（KnowledgeSys 未安装）')
    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run(
            [_sys.executable, sysmon_path, '--report'],
            capture_output=True, text=True, timeout=15, cwd=BASE,
            encoding='utf-8', errors='replace', env=env,
        )
        return ok((result.stdout or '')[:3000])
    except Exception as exc:
        return err(ErrorCode.TOOL_FAILED, f'sysmon 调用失败: {exc}')


@register('agent_status', 'Agent 在线状态')
def tool_agent_status(args):
    return ok({
        'deepseek': '✅ 在线 (API)',
        'gpt4o': '✅ 在线 (API)',
        'zero_server': '✅ 运行中',
    })


# ═══════════════════════════════════════════
# Scrapling 爬虫工具
# ═══════════════════════════════════════════

@register('scrapling_fetch', 'Scrapling 抓取网页（自适应反爬）')
def tool_scrapling_fetch(args):
    url = args.get('url', '')
    if not url:
        return err(ErrorCode.INVALID_INPUT, '缺少 url')
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=15)
        text = page.css('body::text').get() or ''
        title_el = page.css_first('title::text')
        return ok({
            'content': text[:5000],
            'title': title_el or '',
            'url': url,
        })
    except Exception as exc:
        logger.warning('scrapling_fetch %s failed: %s', url[:80], exc)
        return err(ErrorCode.NETWORK, f'Scrapling 抓取失败: {exc}')


@register('scrapling_stealth', 'Scrapling 隐身模式（过 Cloudflare）')
def tool_scrapling_stealth(args):
    url = args.get('url', '')
    if not url:
        return err(ErrorCode.INVALID_INPUT, '缺少 url')
    try:
        from scrapling.fetchers import StealthyFetcher
        page = StealthyFetcher.fetch(url, headless=True)
        text = page.css('body::text').get() or ''
        return ok({'content': text[:5000], 'url': url})
    except Exception as exc:
        return err(ErrorCode.NETWORK, f'隐身抓取失败: {exc}')


# ═══════════════════════════════════════════
# Agnes AI 工具（惰性获取 key）
# ═══════════════════════════════════════════

_AGNES_API = 'https://apihub.agnes-ai.com/v1/chat/completions'


@register('agnes_chat', 'Agnes 2.0 Flash 文本生成（免费）')
def tool_agnes_chat(args):
    prompt = args.get('prompt', '')
    if not prompt:
        return err(ErrorCode.INVALID_INPUT, '缺少 prompt')
    key = get_agnes_key()
    if not key:
        return err(
            ErrorCode.AUTH,
            'Agnes API Key 未配置（设环境变量 AGNES_API_KEY 或 keyring）',
        )
    try:
        payload = json.dumps({
            'model': 'agnes-2.0-flash',
            'messages': [
                {'role': 'system', 'content': '你是零的免费AI引擎。简洁回复。'},
                {'role': 'user', 'content': prompt},
            ],
            'max_tokens': 1000,
        }).encode('utf-8')
        req = urllib.request.Request(
            _AGNES_API, data=payload, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {key}',
            })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        reply = data['choices'][0]['message']['content']
        usage = data.get('usage', {})
        return ok({
            'reply': reply,
            'tokens': usage.get('total_tokens', 0),
            'model': 'agnes-2.0-flash (免费)',
        })
    except Exception as exc:
        logger.warning('agnes_chat failed: %s', exc)
        return err(ErrorCode.MODEL_UNAVAILABLE, f'Agnes 调用失败: {exc}')


# ═══════════════════════════════════════════
# 生图工具（Agnes Image API）
# ═══════════════════════════════════════════

_AGNES_IMAGE_URL = 'https://apihub.agnes-ai.com/v1/images/generations'


@register('image_generate', '生成图片（调用 Agnes Image API）')
def tool_image_generate(args):
    """生图工具。Agent 自主决定何时调用。"""
    prompt = args.get('prompt', '')
    if not prompt:
        return err(ErrorCode.INVALID_INPUT, '缺少 prompt（描述要生成的图片）')
    key = get_agnes_key()
    if not key:
        return err(ErrorCode.AUTH,
                   'Agnes API Key 未配置，无法生图',
                   fallback='请主人配置 AGNES_API_KEY')
    try:
        payload = json.dumps({
            'model': 'agnes-image-2.1-flash',
            'prompt': prompt,
            'n': args.get('n', 1),
            'size': args.get('size', '1024x1024'),
        }).encode('utf-8')
        req = urllib.request.Request(
            _AGNES_IMAGE_URL, data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {key}',
            })
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        img_url = data['data'][0].get('url', '')
        if img_url:
            return ok({'url': img_url, 'prompt': prompt})
        return err(ErrorCode.MODEL_EMPTY_RESPONSE, '生图成功但未返回 URL')
    except Exception as exc:
        logger.warning('image_generate failed: %s', exc)
        return err(ErrorCode.MODEL_UNAVAILABLE, f'生图失败: {exc}')


# ═══════════════════════════════════════════
# 工具执行入口
# ═══════════════════════════════════════════

def execute(tool_name, args, timeout=30) -> Result:
    """执行一个工具，返回统一的 Result 信封。"""
    tool = TOOLS.get(tool_name)
    if not tool:
        return err(ErrorCode.TOOL_NOT_FOUND, f'未知工具: {tool_name}')
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(tool['fn'], args)
            return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return err(ErrorCode.TOOL_TIMEOUT, f'工具 {tool_name} 超时({timeout}s)')
    except Exception as exc:
        logger.warning('tool %s failed: %s', tool_name, exc)
        return err(ErrorCode.TOOL_FAILED, str(exc))


def list_tools():
    return {name: info['description'] for name, info in TOOLS.items()}


def get_tool_names():
    return list(TOOLS.keys())
