"""DeepSeek 适配器
==================
通过 APIHubMix / 官方 API 调用 DeepSeek V3。
"""

import json
import urllib.request

from config import get_api_key, get_api_url, get_logger
from model_adapter.base import AdapterMeta, ModelAdapter
from utils.result import Result, ErrorCode, ok, err

logger = get_logger('zero.adapter.deepseek')

# DeepSeek 静态基准权重（来源: HumanEval 82.6%, MMLU 84.0%, MT-Bench 8.21, LiveCodeBench 等）
_BENCHMARK = {
    'code_generation': 0.87,
    'code_review': 0.82,
    'debugging': 0.84,
    'reasoning': 0.85,
    'chat': 0.78,
    'translation': 0.75,
    'summarization': 0.76,
    'image_generation': 0.0,
    'image_understanding': 0.0,
    'search': 0.0,
    'file_ops': 0.0,
    'browser_control': 0.0,
}


class DeepSeekAdapter(ModelAdapter):
    """DeepSeek V3 适配器。"""

    def __init__(self, api_key: str = '', api_url: str = ''):
        super().__init__(AdapterMeta(
            name='DeepSeek V3 (Reasonix)',
            adapter_id='deepseek_v3',
            provider='deepseek',
        ))
        self._api_key = api_key or get_api_key()
        self._api_url = api_url or get_api_url()

    def is_available(self) -> bool:
        return bool(self._api_key)

    def chat(self, messages: list[dict], **kwargs) -> Result:
        if not self._api_key:
            return err(ErrorCode.AUTH, 'DeepSeek API Key 未配置',
                       fallback='设环境变量 LLM_API_KEY 或 keyring')

        try:
            payload = json.dumps({
                'model': kwargs.get('model', 'deepseek-chat'),
                'messages': messages,
                'max_tokens': kwargs.get('max_tokens', 2000),
                'temperature': kwargs.get('temperature', 0.7),
            }).encode('utf-8')

            req = urllib.request.Request(
                self._api_url,
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self._api_key}',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=kwargs.get('timeout', 30)) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            reply = data['choices'][0]['message']['content']
            if reply:
                return ok(reply)
            return err(ErrorCode.MODEL_EMPTY_RESPONSE, 'DeepSeek 返回空内容')

        except Exception as exc:
            logger.warning('DeepSeek chat failed: %s', exc)
            return err(ErrorCode.MODEL_UNAVAILABLE, f'DeepSeek: {exc}',
                       retryable=True)

    def capabilities(self) -> dict[str, float]:
        return dict(_BENCHMARK)

    def cost_per_1k_tokens(self) -> float:
        return 0.001  # ¥0.001/1K tokens
