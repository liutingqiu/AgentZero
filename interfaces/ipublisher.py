"""社交平台发布接口

实现此接口接入各社交平台。
"""

from typing import Protocol, TypedDict


class PostResult(TypedDict):
    platform: str
    success: bool
    post_url: str | None
    error: str | None


class IPublisher(Protocol):
    """发布器接口。Zero 通过它向社交平台发布内容。"""

    def post(self, platform: str, content: str,
             media_paths: list[str] | None = None) -> PostResult:
        """发布内容到指定平台。"""
        ...

    def list_platforms(self) -> list[str]:
        """返回当前可用的平台列表。"""
        ...


class NullPublisher:
    """默认无操作发布器。用户未配置社交账号时使用。"""

    def post(self, platform: str, content: str,
             media_paths: list[str] | None = None) -> PostResult:
        return {
            'platform': platform,
            'success': False,
            'post_url': None,
            'error': f'未配置发布器（platform={platform}）',
        }

    def list_platforms(self) -> list[str]:
        return []


# 全局实例（由 seed.py 在启动时替换）
publisher: IPublisher = NullPublisher()
