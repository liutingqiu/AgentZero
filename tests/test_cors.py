"""CORS 白名单单元测试
====================
测试 _cors_headers 函数的白名单检查逻辑。

覆盖场景：
- 合法 Origin 返回对应 CORS 头
- 非法 Origin 不返回 CORS 头
- 无 Origin 请求头不返回 CORS 头
- 无 request 参数时使用 * 兜底
- localhost 也在白名单中
- 标准 Allow-Methods / Allow-Headers 始终存在
"""

import pytest
from unittest import mock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.api.server import _cors_headers


class TestCorsHeaders:
    """CORS 白名单功能测试"""

    def test_allowed_origin(self):
        """合法的 Origin 应该返回对应的 Access-Control-Allow-Origin"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'http://127.0.0.1:5052'
        headers = _cors_headers(request)
        assert headers.get('Access-Control-Allow-Origin') == 'http://127.0.0.1:5052'

    def test_blocked_origin(self):
        """非法的 Origin 不应该返回 Access-Control-Allow-Origin"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'https://evil.com'
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Origin' not in headers

    def test_no_origin_header(self):
        """请求头中无 Origin 时，不设置 Access-Control-Allow-Origin

        request.headers.get('Origin', '') 返回 ''，
        空字符串不在白名单中，因此不设置该头。
        """
        request = mock.MagicMock()
        request.headers.get.return_value = ''
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Origin' not in headers

    def test_no_request_fallback(self):
        """无 request 参数时使用 * 兜底

        路由 handler 中 _cors_headers() 无参调用时，
        request is None，走 else 分支设置 * 通配符。
        """
        headers = _cors_headers()  # request 默认为 None
        assert headers.get('Access-Control-Allow-Origin') == '*'

    def test_localhost_allowed(self):
        """localhost 也在白名单中"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'http://localhost:5052'
        headers = _cors_headers(request)
        assert headers.get('Access-Control-Allow-Origin') == 'http://localhost:5052'

    def test_standard_headers_present(self):
        """应该始终返回标准的 Allow-Methods 和 Allow-Headers"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'http://127.0.0.1:5052'
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Methods' in headers
        assert 'Access-Control-Allow-Headers' in headers

    def test_standard_headers_even_when_blocked(self):
        """即使 Origin 被拒绝，Allow-Methods 和 Allow-Headers 仍应存在"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'https://evil.com'
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Methods' in headers
        assert 'Access-Control-Allow-Headers' in headers

    def test_none_request_fallback_has_standard_headers(self):
        """* 兜底时 Allow-Methods 和 Allow-Headers 也应存在"""
        headers = _cors_headers()
        assert headers.get('Access-Control-Allow-Origin') == '*'
        assert 'Access-Control-Allow-Methods' in headers
        assert 'Access-Control-Allow-Headers' in headers

    # ── 边界用例 ──

    def test_different_port_blocked(self):
        """不同端口（5053）不在白名单中，应被拒绝"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'http://127.0.0.1:5053'
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Origin' not in headers

    def test_near_miss_origin_blocked(self):
        """与白名单非常接近但不完全匹配的 Origin 应被拒绝"""
        near_misses = [
            'http://127.0.0.1:5052/',         # 尾部斜杠
            'https://127.0.0.1:5052',         # https 而非 http
            'http://127.0.0.2:5052',          # 不同 IP
            'HTTP://127.0.0.1:5052',          # 大写（严格匹配）
            'http://localhost:5053',          # localhost 但端口不对
        ]
        for origin in near_misses:
            request = mock.MagicMock()
            request.headers.get.return_value = origin
            headers = _cors_headers(request)
            assert 'Access-Control-Allow-Origin' not in headers, \
                f'Origin "{origin}" 不应通过白名单检查'

    def test_none_origin_value_blocked(self):
        """Origin 为 None（某些浏览器对隐私敏感请求发送 null）时应被拒绝"""
        request = mock.MagicMock()
        request.headers.get.return_value = None
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Origin' not in headers
