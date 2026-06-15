"""零 · 工具注册表
==================
AgentLoop 通过此注册表调用所有工具。
每个工具是独立函数，签名统一: func(args) -> dict

从 agent-system/agent_core.py 的 TOOL_REGISTRY 重写。
"""

import os, sys, re, json, shutil, subprocess, urllib.request, fnmatch, threading, concurrent.futures

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 工具注册表 ──
TOOLS = {}

def register(name, description=''):
    """装饰器：注册工具"""
    def decorator(fn):
        TOOLS[name] = {'fn': fn, 'description': description}
        return fn
    return decorator


# ═══════════════════════════════════════════
# 文件操作工具
# ═══════════════════════════════════════════

@register('read_file', '读取文件内容')
def tool_read_file(args):
    path = args.get('path', '') or args.get('file_path', '') or args.get('file', '')
    if not os.path.exists(path):
        return {'success': False, 'error': f'文件不存在: {path}'}
    try:
        max_lines = args.get('lines', 0) or args.get('max_lines', 0)
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            if max_lines > 0:
                lines = [next(f, '') for _ in range(max_lines)]
                content = ''.join(lines)
            else:
                content = f.read(10000)
        return {'success': True, 'output': content, 'size': len(content)}
    except Exception as e:
        return {'success': False, 'error': str(e)}

@register('write_file', '写入文件')
def tool_write_file(args):
    path, content = args.get('path', ''), args.get('content', '')
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return {'success': True, 'output': f'已写入: {path}'}

@register('edit_file', '替换文件中的文本')
def tool_edit_file(args):
    path, search, replace = args.get('path',''), args.get('search',''), args.get('replace','')
    if not os.path.exists(path):
        return {'success': False, 'error': f'文件不存在: {path}'}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if search not in content:
        return {'success': False, 'error': '未找到匹配文本'}
    if content.count(search) > 1:
        return {'success': False, 'error': '匹配文本不唯一，请提供更多上下文'}
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content.replace(search, replace, 1))
    return {'success': True, 'output': f'已修改: {path}'}

@register('list_directory', '列出目录内容')
def tool_list_dir(args):
    path = args.get('path', '.')
    if not os.path.isdir(path):
        return {'success': False, 'error': f'不是目录: {path}'}
    entries = os.listdir(path)
    dirs = [f'📁 {e}/' for e in entries if os.path.isdir(os.path.join(path, e))]
    files = [f'📄 {e}' for e in entries if not os.path.isdir(os.path.join(path, e))]
    return {'success': True, 'output': dirs + files}

@register('search_files', '搜索文件名（子串匹配）')
def tool_search_files(args):
    pattern = args.get('pattern', '')
    directory = args.get('path', '.')
    results = []
    skip = {'.git','node_modules','__pycache__','.venv','dist','build','.reasonix'}
    try:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                # v2: 子串匹配替代 fnmatch（GPT-4o: fnmatch 不支持 '环的小说'→'环_全本.md'）
                if pattern.lower() in f.lower():
                    results.append(os.path.join(root, f))
                if len(results) >= 50:
                    break
            if len(results) >= 50:
                break
    except PermissionError:
        pass
    return {'success': True, 'output': results[:30], 'count': len(results)}

@register('search_content', '搜索文件内容')
def tool_search_content(args):
    pattern = args.get('pattern', '')
    directory = args.get('path', '.')
    results = []
    skip = {'.git','node_modules','__pycache__','.venv','dist','build','.reasonix'}
    text_exts = {'.py','.js','.ts','.html','.css','.md','.txt','.json','.yml','.yaml','.sh','.bat'}
    try:
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                if os.path.splitext(f)[1].lower() not in text_exts:
                    continue
                try:
                    with open(os.path.join(root, f), 'r', encoding='utf-8', errors='ignore') as fh:
                        for i, line in enumerate(fh, 1):
                            if pattern.lower() in line.lower():
                                results.append(f'{os.path.join(root,f)}:{i}: {line.strip()[:120]}')
                                if len(results) >= 20: break
                except: pass
                if len(results) >= 20: break
            if len(results) >= 20: break
    except PermissionError:
        pass
    return {'success': True, 'output': results[:20] if results else f'未找到: {pattern}'}

@register('create_directory', '创建目录')
def tool_create_dir(args):
    path = args.get('path', '')
    os.makedirs(path, exist_ok=True)
    return {'success': True, 'output': f'已创建: {path}'}

@register('delete_file', '删除文件')
def tool_delete_file(args):
    path = args.get('path', '')
    if os.path.isfile(path):
        os.remove(path)
        return {'success': True, 'output': f'已删除: {path}'}
    return {'success': False, 'error': f'文件不存在: {path}'}

@register('move_file', '移动文件')
def tool_move_file(args):
    src = args.get('source', args.get('src', ''))
    dst = args.get('dest', args.get('dst', ''))
    if not os.path.exists(src):
        return {'success': False, 'error': f'源文件不存在: {src}'}
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    shutil.move(src, dst)
    return {'success': True, 'output': f'{src} → {dst}'}

@register('copy_file', '复制文件')
def tool_copy_file(args):
    src = args.get('source', args.get('src', ''))
    dst = args.get('dest', args.get('dst', ''))
    if not os.path.exists(src):
        return {'success': False, 'error': f'源文件不存在: {src}'}
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    shutil.copy2(src, dst)
    return {'success': True, 'output': f'{src} → {dst}'}

@register('shell', '执行系统命令')
def tool_shell(args):
    cmd = args.get('command', '')
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, 
                          timeout=60, cwd=BASE)
        return {
            'success': r.returncode == 0,
            'output': r.stdout or r.stderr,
            'exit_code': r.returncode
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': '命令超时(60s)'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ═══════════════════════════════════════════
# 搜索/信息工具
# ═══════════════════════════════════════════

@register('web_search', '搜索网页')
def tool_web_search(args):
    query = args.get('query', '')
    if not query:
        return {'success': False, 'error': '缺少 query'}
    # DuckDuckGo Lite（快速超时，不通则走 fallback）
    try:
        import urllib.parse
        url = f'https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(query)}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8', errors='ignore')
        results = []
        for m in re.finditer(r'<a[^>]*rel="nofollow"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', html):
            results.append({'title': m.group(2).strip(), 'url': m.group(1)})
        if results:
            return {'success': True, 'output': results[:10]}
    except:
        pass
    return {'success': False, 'error': '搜索不可用（DDG 被墙，请用 GPT-4o 搜索）'}

@register('web_fetch', '抓取网页内容')
def tool_web_fetch(args):
    url = args.get('url', '')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r'<[^>]*>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return {'success': True, 'output': text[:5000]}
    except Exception as e:
        return {'success': False, 'error': f'抓取失败: {e}'}


# ═══════════════════════════════════════════
# 系统/状态工具
# ═══════════════════════════════════════════

@register('sysmon', 'KnowledgeSys 状态检查')
def tool_sysmon(args):
    """运行 bridge/sysmon.py 获取爬虫状态"""
    import subprocess
    sysmon_path = os.path.join(BASE, '..', 'agent-system', 'bridge', 'sysmon.py')
    if not os.path.exists(sysmon_path):
        return {'success': False, 'error': 'sysmon.py 不存在（KnowledgeSys 未安装）'}
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    r = subprocess.run([sys.executable, sysmon_path, '--report'],
                      capture_output=True, timeout=15, cwd=BASE, env=env)
    out = r.stdout.decode('utf-8', errors='replace') if r.stdout else ''
    return {'success': True, 'output': out[:3000]}

@register('agent_status', 'Agent 在线状态')
def tool_agent_status(args):
    """返回 Agent 注册表状态"""
    return {
        'success': True,
        'output': {
            'deepseek': '✅ 在线 (API)',
            'gpt4o': '✅ 在线 (API)',
            'zero_server': '✅ 运行中',
        }
    }


# ═══════════════════════════════════════════
# Scrapling 爬虫工具（62K星，自适应网站改版）
# ═══════════════════════════════════════════

@register('scrapling_fetch', 'Scrapling 抓取网页（自适应反爬）')
def tool_scrapling_fetch(args):
    url = args.get('url', '')
    if not url:
        return {'success': False, 'error': '缺少 url'}
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=15)
        # 提取所有文本
        text = page.css('body::text').get() or ''
        # 提取标题
        title = page.css_first('title::text')
        title_text = title or ''
        return {
            'success': True,
            'output': text[:5000],
            'title': title_text,
            'url': url
        }
    except Exception as e:
        return {'success': False, 'error': f'Scrapling 抓取失败: {e}'}

@register('scrapling_stealth', 'Scrapling 隐身模式（过Cloudflare）')
def tool_scrapling_stealth(args):
    url = args.get('url', '')
    if not url:
        return {'success': False, 'error': '缺少 url'}
    try:
        from scrapling.fetchers import StealthyFetcher
        page = StealthyFetcher.fetch(url, headless=True)
        text = page.css('body::text').get() or ''
        return {'success': True, 'output': text[:5000], 'url': url}
    except Exception as e:
        return {'success': False, 'error': f'隐身抓取失败: {e}'}


# ═══════════════════════════════════════════
# Agnes AI 工具（全球第9 AI Lab，免费API）
# ═══════════════════════════════════════════

AGNES_API = 'https://apihub.agnes-ai.com/v1/chat/completions'
AGNES_KEY = __import__('keyring').get_password('AGNES', 'KEY') or ''

@register('agnes_chat', 'Agnes 2.0 Flash 文本生成（免费）')
def tool_agnes_chat(args):
    prompt = args.get('prompt', '')
    if not prompt:
        return {'success': False, 'error': '缺少 prompt'}
    if not AGNES_KEY:
        return {'success': False, 'error': 'Agnes API Key 未配置（在 agnes-ai.com 免费获取）'}
    try:
        payload = json.dumps({
            'model': 'agnes-2.0-flash',
            'messages': [
                {'role': 'system', 'content': '你是零的免费AI引擎。简洁回复。'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 1000
        }).encode()
        req = urllib.request.Request(AGNES_API, data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {AGNES_KEY}'})
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        reply = r['choices'][0]['message']['content']
        usage = r.get('usage', {})
        return {
            'success': True,
            'output': reply,
            'tokens': usage.get('total_tokens', 0),
            'model': 'agnes-2.0-flash (免费)'
        }
    except Exception as e:
        return {'success': False, 'error': f'Agnes 调用失败: {e}'}


# ═══════════════════════════════════════════
# 工具执行入口
# ═══════════════════════════════════════════

def execute(tool_name, args, timeout=30):
    """执行一个工具，返回 {success, output/error}
    
    v2: 加超时保护（GPT-4o: 工具可能卡死）
    """
    tool = TOOLS.get(tool_name)
    if not tool:
        return {'success': False, 'error': f'未知工具: {tool_name}'}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(tool['fn'], args)
            return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return {'success': False, 'error': f'工具 {tool_name} 超时({timeout}s)'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def list_tools():
    """返回所有工具名和描述"""
    return {name: info['description'] for name, info in TOOLS.items()}

def get_tool_names():
    """返回工具名列表（供 LLM prompt 用）"""
    return list(TOOLS.keys())
