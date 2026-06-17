"""测试统一结果协议 utils/result.py"""

from utils.result import Result, ErrorInfo, ErrorCode, ok, err


class TestResult:
    def test_ok(self):
        r = ok(data={'reply': 'hello'})
        assert r.ok is True
        assert r.data == {'reply': 'hello'}
        assert r.error is None

    def test_ok_with_none(self):
        r = ok()
        assert r.ok is True
        assert r.data is None

    def test_err(self):
        r = err(code='TIMEOUT', message='模型超时', retryable=True)
        assert r.ok is False
        assert r.error.code == 'TIMEOUT'
        assert r.error.message == '模型超时'
        assert r.error.retryable is True

    def test_err_default_message(self):
        r = err(code='AUTH')
        assert r.error.message == 'AUTH'

    def test_unwrap_ok(self):
        r = ok(data=42)
        assert r.unwrap() == 42

    def test_unwrap_err_raises(self):
        import pytest
        r = err('INTERNAL', '出错')
        with pytest.raises(RuntimeError, match='Result.unwrap\(\) on error'):
            r.unwrap()

    def test_to_dict_ok(self):
        r = ok(data='hello')
        assert r.to_dict() == {'ok': True, 'data': 'hello'}

    def test_to_dict_err(self):
        r = err('NETWORK', '网络错误', retryable=True)
        d = r.to_dict()
        assert d == {
            'ok': False,
            'error': {'code': 'NETWORK', 'message': '网络错误', 'retryable': True},
        }

    def test_to_dict_ok_no_data(self):
        r = ok()
        assert r.to_dict() == {'ok': True}

    def test_error_code_constants(self):
        assert ErrorCode.TIMEOUT == 'TIMEOUT'
        assert ErrorCode.AUTH == 'AUTH'
        assert ErrorCode.INTERNAL == 'INTERNAL'
        assert ErrorCode.JAILBREAK == 'JAILBREAK'


class TestErrorInfo:
    def test_defaults(self):
        e = ErrorInfo(code='X', message='test')
        assert e.retryable is False
        assert e.fallback is None

    def test_full(self):
        e = ErrorInfo(code='X', message='test', retryable=True, fallback='换模型')
        assert e.retryable is True
        assert e.fallback == '换模型'
