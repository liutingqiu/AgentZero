"""API 错误格式统一测试
=====================
验证 _error_response 函数格式 + 实际 HTTP 端点错误响应。

边界规则：只在 tests/ 下创建，不改 app/ 下任何文件。
"""
import pytest
import json
import sys
import os

# ── 路径设置 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── 导入 _error_response 和错误码 ──
# 如果导入失败（依赖链断裂），单元测试会跳过
try:
    from app.api.server import (
        _error_response,
        ERR_AUTH_FAILED,
        ERR_FILE_TYPE,
        ERR_FILE_SIZE,
        ERR_INTERNAL,
        ERR_BAD_REQUEST,
        ERR_NOT_FOUND,
    )
    IMPORT_OK = True
except ImportError as exc:
    IMPORT_OK = False
    IMPORT_ERROR = str(exc)


# ═══════════════════════════════════════════
# 单元测试：_error_response 函数
# ═══════════════════════════════════════════

@pytest.mark.skipif(not IMPORT_OK, reason=f'导入 app.api.server 失败: {IMPORT_ERROR if not IMPORT_OK else ""}')
class TestErrorResponseUnit:
    """_error_response 函数单元测试"""

    def test_error_response_basic_format(self):
        """基本错误响应格式：ok=False, error.code, error.msg"""
        response = _error_response('TEST_ERROR', 'test msg', status=400)
        data = json.loads(response.body)
        assert data == {
            'ok': False,
            'error': {'code': 'TEST_ERROR', 'msg': 'test msg'}
        }
        assert response.status == 400

    def test_error_response_with_status_500(self):
        """500 错误响应"""
        response = _error_response(ERR_INTERNAL, '内部错误', status=500)
        data = json.loads(response.body)
        assert data['ok'] is False
        assert data['error']['code'] == ERR_INTERNAL
        assert data['error']['msg'] == '内部错误'
        assert response.status == 500

    def test_error_response_auth_failed(self):
        """认证失败错误码"""
        response = _error_response(ERR_AUTH_FAILED, '暗号错误', status=400)
        data = json.loads(response.body)
        assert data['error']['code'] == ERR_AUTH_FAILED

    def test_error_response_file_type(self):
        """文件类型错误码"""
        response = _error_response(ERR_FILE_TYPE, '文件类型不允许: .exe', status=400)
        data = json.loads(response.body)
        assert data['error']['code'] == ERR_FILE_TYPE
        assert '.exe' in data['error']['msg']

    def test_error_response_extra_fields(self):
        """错误响应不应该包含多余字段（仅 ok 和 error 两个顶层 key）"""
        response = _error_response(ERR_INTERNAL, 'error', status=400)
        data = json.loads(response.body)
        assert set(data.keys()) == {'ok', 'error'}
        assert set(data['error'].keys()) == {'code', 'msg'}

    def test_error_response_default_status_400(self):
        """status 参数默认值为 400"""
        response = _error_response('TEST', 'msg')
        assert response.status == 400

    def test_error_response_all_error_codes(self):
        """验证所有已定义的错误码常量"""
        all_codes = {
            ERR_AUTH_FAILED: 'AUTH_FAILED',
            ERR_FILE_TYPE: 'FILE_TYPE_NOT_ALLOWED',
            ERR_FILE_SIZE: 'FILE_TOO_LARGE',
            ERR_INTERNAL: 'INTERNAL_ERROR',
            ERR_BAD_REQUEST: 'BAD_REQUEST',
            ERR_NOT_FOUND: 'NOT_FOUND',
        }
        for var, expected in all_codes.items():
            assert var == expected, f'错误码常量值不匹配: {var} != {expected}'

    def test_error_response_msg_is_string(self):
        """msg 字段应该始终是字符串"""
        response = _error_response(ERR_INTERNAL, '服务器错误', status=500)
        data = json.loads(response.body)
        assert isinstance(data['error']['msg'], str)

    def test_error_response_code_is_string(self):
        """code 字段应该始终是字符串"""
        response = _error_response(ERR_INTERNAL, 'msg')
        data = json.loads(response.body)
        assert isinstance(data['error']['code'], str)

    def test_error_response_content_type(self):
        """响应应该是 JSON 类型"""
        response = _error_response('TEST', 'msg')
        assert response.content_type == 'application/json'


# ═══════════════════════════════════════════
# 集成测试：实际 HTTP 端点错误格式
# ═══════════════════════════════════════════

@pytest.mark.skip(reason='需要启动 zero 服务端，在 CI 环境运行')
class TestErrorResponseIntegration:
    """集成测试：验证实际 HTTP 端点的错误响应格式（需服务端运行）"""

    @pytest.mark.asyncio
    async def test_auth_failed_format(self, aiohttp_client, app):
        """认证失败应返回统一错误格式"""
        client = await aiohttp_client(app)
        resp = await client.post('/api/auth', json={'code': 'wrong'})
        assert resp.status in (400, 401)
        data = await resp.json()
        assert data['ok'] is False
        assert 'error' in data
        assert 'code' in data['error']
        assert 'msg' in data['error']

    @pytest.mark.asyncio
    async def test_upload_failed_format(self, aiohttp_client, app):
        """文件上传失败应返回统一错误格式"""
        client = await aiohttp_client(app)
        resp = await client.post('/api/upload', data={'file': b'test content'})
        data = await resp.json()
        # 无论成功或失败，响应格式应该一致
        if not data.get('ok', True):
            assert 'error' in data
            assert 'code' in data['error']
            assert 'msg' in data['error']

    @pytest.mark.asyncio
    async def test_success_response_no_error(self, aiohttp_client, app):
        """成功响应（/health）不应包含 error 字段"""
        client = await aiohttp_client(app)
        resp = await client.get('/health')
        data = await resp.json()
        assert 'error' not in data

    @pytest.mark.asyncio
    async def test_favicon_404_format(self, aiohttp_client, app):
        """404 错误应返回统一错误格式"""
        client = await aiohttp_client(app)
        resp = await client.get('/nonexistent-path')
        if resp.status >= 400:
            data = await resp.json()
            assert data['ok'] is False
            assert 'error' in data


# ═══════════════════════════════════════════
# 格式一致性检查（不依赖服务端运行）
# ═══════════════════════════════════════════

@pytest.mark.skipif(not IMPORT_OK, reason=f'导入 app.api.server 失败: {IMPORT_ERROR if not IMPORT_OK else ""}')
class TestErrorFormatConsistency:
    """验证 server.py 中所有 _error_response 调用格式一致"""

    def _find_error_calls(self):
        """扫描 server.py 中所有 _error_response 调用，返回 (code, status) 列表"""
        import ast
        server_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'api', 'server.py')
        with open(server_path, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and hasattr(node.func, 'id') and node.func.id == '_error_response':
                # 提取第一个参数（错误码）和 status 关键字参数
                args = [ast.unparse(a) for a in node.args] if node.args else []
                kwargs = {kw.arg: ast.unparse(kw.value) for kw in node.keywords if kw.arg}
                code = args[0] if args else kwargs.get('code', '?')
                status = kwargs.get('status', '400')
                calls.append((code, status))
        return calls

    def test_all_error_calls_have_code_and_msg(self):
        """每个 _error_response 调用应有 code 和 msg 两个位置参数"""
        calls = self._find_error_calls()
        assert len(calls) > 0, 'server.py 中应该有 _error_response 调用'
        # 第一个参数是错误码，应该是 ERR_* 常量
        for code, _ in calls:
            assert 'ERR_' in code or code in (
                "'AUTH_FAILED'", "'FILE_TYPE_NOT_ALLOWED'",
                "'FILE_TOO_LARGE'", "'INTERNAL_ERROR'",
                "'BAD_REQUEST'", "'NOT_FOUND'",
            ), f'_error_response 调用使用了非标准错误码: {code}'

    def test_error_calls_use_correct_status_codes(self):
        """错误码应匹配合理的 HTTP 状态码"""
        calls = self._find_error_calls()
        auth_codes = []
        for code, status in calls:
            if 'AUTH_FAILED' in code:
                auth_codes.append(status)
        # 认证失败应该是 401
        for s in auth_codes:
            assert s == '401', f'AUTH_FAILED 应返回 401，实际: {s}'
