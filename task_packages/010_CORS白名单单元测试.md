# 任务 010：CORS 白名单单元测试

> **身份**：你只负责这个任务包。不要查看或修改本任务包未指定的任何文件。
> 你是一个没有大局观的 AI，只能编写测试文件。涉及修改生产代码或全局架构决策你会产生幻觉，必须拒绝执行并向上级报告。

---

## 边界规则（不可违反）

1. 只在 `tests/` 目录下创建新文件 `tests/test_cors.py`。
2. 不改 `app/`、`interface/`、`config.py` 下的任何文件。
3. 不修改现有的测试文件。
4. 如果有任何不确定的地方，问清楚再动手，不要猜测。

---

## 前置准备

读取以下文件：
- `app/api/server.py`（重点关注 `_cors_headers` 函数，约第 43-63 行）
- `tests/test_e2e.py`（了解现有测试的写法风格）

---

## 需求

为 CORS 白名单功能编写单元测试，覆盖正常情况和边界情况。

### 测试内容

**测试 1：合法的 Origin 返回正确的 CORS 头**

```python
@pytest.mark.asyncio
async def test_cors_allowed_origin():
    """合法的 Origin 应该返回对应的 Access-Control-Allow-Origin"""
    # 构造一个带有 Origin 头的 OPTIONS 请求
    request = mock.MagicMock()
    request.headers.get.return_value = 'http://127.0.0.1:5052'

    headers = _cors_headers(request)
    assert headers.get('Access-Control-Allow-Origin') == 'http://127.0.0.1:5052'
```

**测试 2：非法的 Origin 不返回 CORS 头**

```python
@pytest.mark.asyncio
async def test_cors_blocked_origin():
    """非法的 Origin 不应该返回 Access-Control-Allow-Origin"""
    request = mock.MagicMock()
    request.headers.get.return_value = 'https://evil.com'

    headers = _cors_headers(request)
    assert 'Access-Control-Allow-Origin' not in headers
```

**测试 3：无 Origin 头时使用兜底**

```python
@pytest.mark.asyncio
async def test_cors_no_origin():
    """无 Origin 头时应该使用兜底 *"""
    request = mock.MagicMock()
    request.headers.get.return_value = None

    headers = _cors_headers(request)
    # 无 request 时保留 * 兜底
    assert headers.get('Access-Control-Allow-Origin') == '*'
```

**测试 4：localhost 也在白名单中**

```python
@pytest.mark.asyncio
async def test_cors_localhost_allowed():
    """localhost 也在白名单中"""
    request = mock.MagicMock()
    request.headers.get.return_value = 'http://localhost:5052'

    headers = _cors_headers(request)
    assert headers.get('Access-Control-Allow-Origin') == 'http://localhost:5052'
```

**测试 5：CORS 头中包含 Allow-Methods 和 Allow-Headers**

```python
@pytest.mark.asyncio
async def test_cors_standard_headers_present():
    """应该返回标准的 Allow-Methods 和 Allow-Headers"""
    request = mock.MagicMock()
    request.headers.get.return_value = 'http://127.0.0.1:5052'

    headers = _cors_headers(request)
    assert 'Access-Control-Allow-Methods' in headers
    assert 'Access-Control-Allow-Headers' in headers
```

---

## 完整测试文件结构

```python
"""CORS 白名单单元测试"""
import pytest
from unittest import mock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.api.server import _cors_headers


class TestCorsHeaders:
    """CORS 白名单功能测试"""

    def test_allowed_origin(self):
        """合法的 Origin 应该返回对应的 CORS 头"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'http://127.0.0.1:5052'
        headers = _cors_headers(request)
        assert headers.get('Access-Control-Allow-Origin') == 'http://127.0.0.1:5052'

    def test_blocked_origin(self):
        """非法的 Origin 不应该返回 CORS 头"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'https://evil.com'
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Origin' not in headers

    def test_no_origin(self):
        """无 Origin 头时使用兜底"""
        request = mock.MagicMock()
        request.headers.get.return_value = None
        headers = _cors_headers(request)
        # 无 request 时保留 * 兜底
        assert headers.get('Access-Control-Allow-Origin') == '*'

    def test_localhost_allowed(self):
        """localhost 也在白名单中"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'http://localhost:5052'
        headers = _cors_headers(request)
        assert headers.get('Access-Control-Allow-Origin') == 'http://localhost:5052'

    def test_standard_headers_present(self):
        """应该返回标准的 Allow-Methods 和 Allow-Headers"""
        request = mock.MagicMock()
        request.headers.get.return_value = 'http://127.0.0.1:5052'
        headers = _cors_headers(request)
        assert 'Access-Control-Allow-Methods' in headers
        assert 'Access-Control-Allow-Headers' in headers
```

---

## 验收标准

1. `pytest tests/test_cors.py -v` 全部 5 个测试通过
2. 测试覆盖：合法 Origin、非法 Origin、无 Origin、localhost、标准头存在

---

## 如何验证

```bash
# 运行测试
cd E:/project/tools/zero
python -m pytest tests/test_cors.py -v

# 预期输出
# test_cors.py::TestCorsHeaders::test_allowed_origin PASSED
# test_cors.py::TestCorsHeaders::test_blocked_origin PASSED
# test_cors.py::TestCorsHeaders::test_no_origin PASSED
# test_cors.py::TestCorsHeaders::test_localhost_allowed PASSED
# test_cors.py::TestCorsHeaders::test_standard_headers_present PASSED
```

---

## 遇到问题时的决策树

1. `_cors_headers` 函数签名与预期不同 → 读取实际代码，按实际签名写 mock
2. `_cors_headers` 不在 `app.api.server` 模块中 → 在代码中搜索其位置
3. 测试导入报错（依赖问题） → 添加 `sys.path.insert` 或设置 `PYTHONPATH`
4. 不确定 mock 的写法 → 使用 `from unittest import mock` 标准库