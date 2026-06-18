"""零 · 模型适配器层
====================
提供统一的 ModelAdapter 接口 + 自动加载逻辑。

用法:
    from model_adapter import load_adapters, find_adapter

    adapters = load_adapters()
    # adapters = [DeepSeekAdapter, AgnesAdapter, ...]

    adapter = find_adapter(adapters, 'deepseek_v3')
    result = adapter.chat([{'role': 'user', 'content': '你好'}])
"""

from __future__ import annotations

from model_adapter.base import AdapterMeta, ModelAdapter  # noqa: F401
from model_adapter.deepseek import DeepSeekAdapter
from model_adapter.agnes import AgnesAdapter
from model_adapter.openai import OpenAIAdapter
from model_adapter.ollama import OllamaAdapter


def load_adapters(config: dict | None = None) -> list[ModelAdapter]:
    """从配置加载所有可用模型适配器。

    优先级:
      1. zero_config.json 中的 models 列表
      2. 环境变量自动检测（AGNES_API_KEY, LLM_API_KEY 等）
      3. 本地 Ollama 自动发现

    Returns:
        list[ModelAdapter]: 已通过 is_available() 检查的适配器
    """
    config = config or {}
    models_cfg = config.get('models', [])
    adapters: list[ModelAdapter] = []

    if models_cfg:
        # 显式配置优先
        for entry in models_cfg:
            provider = entry.get('provider', '').lower()
            adapter = _build_adapter(provider, entry)
            if adapter and adapter.is_available():
                adapters.append(adapter)
    else:
        # 自动发现
        adapters = _auto_discover(config)

    return adapters


def find_adapter(adapters: list[ModelAdapter],
                 adapter_id: str) -> ModelAdapter | None:
    """按 adapter_id 查找适配器。"""
    for a in adapters:
        if a.meta.adapter_id == adapter_id:
            return a
    return None


def _build_adapter(provider: str, cfg: dict) -> ModelAdapter | None:
    """根据 provider 类型构建适配器。"""
    api_key = cfg.get('api_key', '')
    api_url = cfg.get('api_url', '')
    model = cfg.get('model', '')
    name = cfg.get('name', '')

    if provider == 'deepseek':
        return DeepSeekAdapter(api_key=api_key, api_url=api_url)
    elif provider == 'agnes':
        return AgnesAdapter(api_key=api_key)
    elif provider == 'openai':
        return OpenAIAdapter(api_key=api_key, api_url=api_url,
                             model=model or cfg.get('default_model', 'gpt-4o'))
    elif provider == 'ollama':
        return OllamaAdapter(model=model or 'llama3.1:8b',
                             base_url=cfg.get('base_url',
                                              'http://localhost:11434'),
                             name=name)
    return None


def _auto_discover(config: dict) -> list[ModelAdapter]:
    """自动发现可用模型（环境变量 + 本地 Ollama）。"""
    adapters: list[ModelAdapter] = []

    # 检测 Agnes（免费优先）
    agnes = AgnesAdapter()
    if agnes.is_available():
        adapters.append(agnes)

    # 检测 DeepSeek
    deepseek = DeepSeekAdapter()
    if deepseek.is_available():
        adapters.append(deepseek)

    # 检测 Ollama 本地
    ollama = OllamaAdapter()
    if ollama.is_available():
        adapters.append(ollama)

    # OpenAI 需要显式配置 API key，不自动检测
    openai_key = config.get('openai', {}).get('api_key', '') if config else ''
    if openai_key:
        openai = OpenAIAdapter(api_key=openai_key)
        if openai.is_available():
            adapters.append(openai)

    return adapters


def list_available_models(adapters: list[ModelAdapter]) -> list[dict]:
    """列出所有可用模型的元信息（供前端展示）。"""
    return [
        {
            'id': a.meta.adapter_id,
            'name': a.meta.name,
            'provider': a.meta.provider,
            'is_local': a.meta.is_local,
            'is_free': a.meta.is_free,
            'capabilities': a.capabilities(),
            'cost_per_1k': a.cost_per_1k_tokens(),
        }
        for a in adapters if a.is_available()
    ]
