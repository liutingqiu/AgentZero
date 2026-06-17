"""技能引擎接口

实现此接口接入 muapi Skills / 其他 AI 技能系统。
"""

from typing import Any, Protocol


class SkillResult(TypedDict):
    success: bool
    output: str | None
    error: str | None


class ISkillEngine(Protocol):
    """技能引擎接口。"""

    def list_skills(self) -> list[dict[str, str]]:
        """列出所有可用技能。返回 [{'name': ..., 'description': ...}]"""
        ...

    def execute(self, skill_name: str,
                params: dict[str, Any] | None = None) -> SkillResult:
        """执行指定技能。"""
        ...


class NullSkillEngine:
    """默认无操作技能引擎。"""

    def list_skills(self) -> list[dict[str, str]]:
        return []

    def execute(self, skill_name: str,
                params: dict[str, Any] | None = None) -> SkillResult:
        return {
            'success': False,
            'output': None,
            'error': f'未配置技能引擎（skill={skill_name}）',
        }


# 全局实例
skill_engine: ISkillEngine = NullSkillEngine()
