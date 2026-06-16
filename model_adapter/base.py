"""零 · 模型适配器基类
======================
所有模型适配器的抽象接口。壳子只认这个接口，不关心后端是 API / 本地 / 云端。

用法:
    from model_adapter.base import ModelAdapter

    class MyAdapter(ModelAdapter):
        def chat(self, messages, **kwargs) -> Result: ...
        def capabilities(self) -> dict[str, float]: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from utils.result import Result


@dataclass
class AdapterMeta:
    """适配器元信息。"""
    name: str               # 显示名，如 "DeepSeek V3"
    adapter_id: str         # 唯一标识，如 "deepseek_v3"
    provider: str           # 厂商，如 "deepseek" | "openai" | "ollama"
    is_local: bool = False  # 本地模型不消耗 API 配额
    is_free: bool = False   # 免费 API（如 Agnes）


class ModelAdapter(ABC):
    """模型适配器抽象基类。

    每个适配器实现三个方法:
      - chat: 文本对话
      - capabilities: 返回能力权重表（静态基准）
      - image_generate: 可选，生图能力
    """

    def __init__(self, meta: AdapterMeta):
        self.meta = meta

    # ── 必须实现 ──

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> Result:
        """发送消息，返回 Result(data=回复文本)。

        Args:
            messages: [{'role': 'system'|'user'|'assistant', 'content': '...'}]
            **kwargs: 透传参数（temperature, max_tokens 等）

        Returns:
            Result: ok=True 时 data 为文本回复；失败时 error 含错误码
        """
        ...

    @abstractmethod
    def capabilities(self) -> dict[str, float]:
        """返回该模型在各能力维度上的静态基准权重 (0.0~1.0)。

        维度名称:
          code_generation, code_review, debugging, reasoning,
          chat, translation, summarization, image_generation,
          image_understanding, search, file_ops, browser_control

        权重来源: 公开 benchmark（HumanEval, MMLU, MT-Bench 等）。
        运行时由 ProficiencyTracker 动态修正。
        """
        ...

    # ── 可选 ──

    def image_generate(self, prompt: str, **kwargs) -> Result:
        """生图（可选，默认不支持）。"""
        from utils.result import err, ErrorCode
        return err(ErrorCode.MODEL_UNAVAILABLE,
                   f'{self.meta.name} 不支持生图')

    def cost_per_1k_tokens(self) -> float:
        """每 1K token 的估算费用（人民币）。"""
        return 0.0

    def is_available(self) -> bool:
        """检查适配器是否可用（API key 是否配置等）。"""
        return True

    # ── 便利方法 ──

    def to_agent_dict(self) -> dict:
        """转为 agent_registry 兼容的注册字典。"""
        return {
            'adapter_id': self.meta.adapter_id,
            'name': self.meta.name,
            'capabilities': set(self.capabilities().keys()),
            'cost': self.cost_per_1k_tokens(),
            'is_free': self.meta.is_free,
            'is_local': self.meta.is_local,
            'proficiencies': self.capabilities(),
        }
