"""Ollama 适配器
=================
本地 Ollama 模型适配器（Llama3, Qwen, Mistral 等）。

用法:
    确保 Ollama 运行在 http://localhost:11434
    在 zero_config.json 中配置:
    {
      "models": [
        {"provider": "ollama", "model": "llama3.1:8b", "name": "Llama 3.1 8B"}
      ]
    }
"""

import json
import urllib.request

from config import get_logger
from model_adapter.base import AdapterMeta, ModelAdapter
from utils.result import Result, ErrorCode, ok, err

logger = get_logger('zero.adapter.ollama')


# Llama3 70B 静态基准（来源: HumanEval 81.7%, MMLU 86.1%, MT-Bench 8.84）
# 小模型按比例下调
_BENCHMARK_8B = {
    'code_generation': 0.68,
    'code_review': 0.62,
    'debugging': 0.60,
    'reasoning': 0.66,
    'chat': 0.72,
    'translation': 0.65,
    'summarization': 0.70,
    'image_generation': 0.0,
    'image_understanding': 0.0,
    'search': 0.0,
    'file_ops': 0.0,
    'browser_control': 0.0,
}

_BENCHMARK_70B = {
    'code_generation': 0.82,
    'code_review': 0.78,
    'debugging': 0.76,
    'reasoning': 0.83,
    'chat': 0.81,
    'translation': 0.78,
    'summarization': 0.80,
    'image_generation': 0.0,
    'image_understanding': 0.0,
    'search': 0.0,
    'file_ops': 0.0,
    'browser_control': 0.0,
}


class OllamaAdapter(ModelAdapter):
    """Ollama 本地模型适配器。"""

    def __init__(self, model: str = 'llama3.1:8b',
                 base_url: str = 'http://localhost:11434',
                 name: str = ''):
        adapter_id = f'ollama_{model.replace(":", "_").replace(".", "_")}'
        super().__init__(AdapterMeta(
            name=name or f'Ollama {model}',
            adapter_id=adapter_id,
            provider='ollama',
            is_local=True,
            is_free=True,
        ))
        self._model = model
        self._base_url = base_url.rstrip('/')
        self._api_url = f'{self._base_url}/api/chat'

        # 根据模型大小选基准权重
        if '70b' in model.lower() or '72b' in model.lower():
            self._benchmark = _BENCHMARK_70B
        else:
            self._benchmark = _BENCHMARK_8B

    def is_available(self) -> bool:
        """检测 Ollama 服务是否可达。"""
        try:
            req = urllib.request.Request(
                f'{self._base_url}/api/tags',
                headers={'User-Agent': 'Zero/1.0'},
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False

    def chat(self, messages: list[dict], **kwargs) -> Result:
        try:
            payload = json.dumps({
                'model': self._model,
                'messages': messages,
                'stream': False,
                'options': {
                    'temperature': kwargs.get('temperature', 0.7),
                    'num_predict': kwargs.get('max_tokens', 2000),
                },
            }).encode('utf-8')

            req = urllib.request.Request(
                self._api_url,
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req,
                                         timeout=kwargs.get('timeout', 60)) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            reply = data.get('message', {}).get('content', '')
            if reply:
                return ok(reply)
            return err(ErrorCode.MODEL_EMPTY_RESPONSE,
                       f'Ollama {self._model} 返回空内容')

        except urllib.error.URLError:
            return err(ErrorCode.NETWORK,
                       f'Ollama 服务不可达 ({self._base_url})',
                       fallback='确保 ollama serve 正在运行')
        except Exception as exc:
            logger.warning('Ollama chat failed: %s', exc)
            return err(ErrorCode.MODEL_UNAVAILABLE,
                       f'Ollama {self._model}: {exc}',
                       retryable=True)

    def capabilities(self) -> dict[str, float]:
        return dict(self._benchmark)

    def cost_per_1k_tokens(self) -> float:
        return 0.0  # 本地模型，零边际成本
