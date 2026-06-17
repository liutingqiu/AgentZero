"""零 · 前端页面（已拆分至 webapp_static/）

此文件保留 WEBAPP_HTML 作为向后兼容的备用方案。
当前前端由 interface/webapp_static/ 下的独立文件提供。
"""
import os as _os

_STATIC_DIR = _os.path.join(_os.path.dirname(__file__), 'webapp_static')
_INDEX_PATH = _os.path.join(_STATIC_DIR, 'index.html')

try:
    with open(_INDEX_PATH, 'r', encoding='utf-8') as _f:
        WEBAPP_HTML = _f.read()
except (FileNotFoundError, IOError):
    # 如果静态文件不存在，提供一个基本的占位 HTML
    WEBAPP_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>零</title></head>
<body><p>前端资源未加载。请确保 webapp_static/index.html 存在。</p></body>
</html>'''
