"""零 · 统一结果协议
=====================
壳子内所有模块的返回值统一用 Result 信封。

用法:
    from utils.result import Result, ErrorInfo, ok, err

    # 成功
    return ok(data={'reply': '你好'})

    # 失败
    return err(
        code='TIMEOUT',
        message='模型调用超时(30s)',
        retryable=True,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── 错误码枚举 ───────────────────────────────────────────────────────
class ErrorCode:
    TIMEOUT = 'TIMEOUT'
    AUTH = 'AUTH'
    NETWORK = 'NETWORK'
    MODEL_UNAVAILABLE = 'MODEL_UNAVAILABLE'
    MODEL_EMPTY_RESPONSE = 'MODEL_EMPTY_RESPONSE'
    TOOL_FAILED = 'TOOL_FAILED'
    TOOL_NOT_FOUND = 'TOOL_NOT_FOUND'
    TOOL_TIMEOUT = 'TOOL_TIMEOUT'
    SHELL_REJECTED = 'SHELL_REJECTED'
    FILE_NOT_FOUND = 'FILE_NOT_FOUND'
    PATH_TRAVERSAL = 'PATH_TRAVERSAL'
    INVALID_INPUT = 'INVALID_INPUT'
    VALIDATION_FAILED = 'VALIDATION_FAILED'
    JAILBREAK = 'JAILBREAK'
    PERMISSION_DENIED = 'PERMISSION_DENIED'
    INTERNAL = 'INTERNAL'


# ── 数据类 ────────────────────────────────────────────────────────────


@dataclass
class ErrorInfo:
    """结构化错误信息。"""
    code: str           # ErrorCode 枚举值
    message: str        # 人类可读
    retryable: bool = False
    fallback: str | None = None   # 降级方案描述


@dataclass
class Result:
    """统一返回值信封。

    成功: Result(ok=True, data={...})
    失败: Result(ok=False, error=ErrorInfo(...))
    """
    ok: bool
    data: Any = None
    error: ErrorInfo | None = None

    def unwrap(self):
        """取 data；失败抛异常。仅用于内部确定性路径。"""
        if not self.ok:
            raise RuntimeError(f'Result.unwrap() on error: {self.error}')
        return self.data

    def to_dict(self) -> dict:
        """转为可序列化 dict（供 HTTP 响应 / 日志）。"""
        d: dict = {'ok': self.ok}
        if self.data is not None:
            d['data'] = self.data
        if self.error:
            d['error'] = {
                'code': self.error.code,
                'message': self.error.message,
                'retryable': self.error.retryable,
            }
        return d


# ── 快捷构造 ──────────────────────────────────────────────────────────


def ok(data: Any = None) -> Result:
    """构造成功结果。"""
    return Result(ok=True, data=data)


def err(code: str, message: str = '',
        retryable: bool = False, fallback: str | None = None) -> Result:
    """构造失败结果。"""
    return Result(
        ok=False,
        error=ErrorInfo(
            code=code,
            message=message or code,
            retryable=retryable,
            fallback=fallback,
        ),
    )
