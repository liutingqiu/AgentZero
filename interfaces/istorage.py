"""存储后端接口

实现此接口接入替代 SQLite 的存储后端（PostgreSQL、文件系统等）。
"""

from typing import Protocol


class IStorage(Protocol):
    """存储后端接口。Zero 通过它读写持久化数据。"""

    def get(self, key: str) -> str | None:
        """读取键值。"""
        ...

    def set(self, key: str, value: str) -> None:
        """写入键值。"""
        ...

    def delete(self, key: str) -> bool:
        """删除键值。返回是否成功。"""
        ...

    def list_keys(self, prefix: str = '') -> list[str]:
        """列出指定前缀的所有键。"""
        ...


class NullStorage:
    """默认无操作存储。使用内存字典，不持久化。"""

    def __init__(self):
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def list_keys(self, prefix: str = '') -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]


# 全局实例（由插件加载器在启动时替换）
storage: IStorage = NullStorage()
