"""自定义工具接口

实现此接口向 Zero 注册额外的工具。
"""

from typing import Any, Protocol

from utils.result import Result


class ICustomTool(Protocol):
    """自定义工具接口。"""

    name: str
    description: str

    def execute(self, args: dict[str, Any]) -> Result:
        """执行工具逻辑，返回统一 Result。"""
        ...


# 全局工具注册扩展
_extra_tools: dict[str, ICustomTool] = {}


def register_tool(tool: ICustomTool) -> None:
    """注册一个自定义工具到全局扩展。"""
    _extra_tools[tool.name] = tool


def get_extra_tools() -> dict[str, ICustomTool]:
    """获取所有已注册的自定义工具。"""
    return dict(_extra_tools)
