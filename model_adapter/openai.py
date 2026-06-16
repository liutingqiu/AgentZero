"""OpenAI 适配器
=================
GPT-4o / GPT-4o-mini 适配器。

支持任何 OpenAI 兼容 API（含 APIHubMix 中转）。
"""

import json
import urllib.request

from config import get_logger
from model_adapter.base import AdapterMeta, ModelAdapter
from utils.result import Result, ErrorCode, ok, err

logger = get_logger('zero.adapter.openai')

# GPT-4o 静态基准权重（来源: HumanEval 90.2%, MMLU 88.7%, MT-Bench 9.19）
_BENCHMARK = {
    'code_generation': 0.90,
    'code_review': 0.88,
    'debugging': 0.87,
    'reasoning': 0.92,
    'chat': 0.88,
    'translation': 0.86,
    'summarization': 0.85,
    'image_generation': 0.0,
    'image_understanding': 0.85,
    'search': 0.0,
    'file_ops': 0.0,
    'browser_control': 0.0,
}


class OpenAIAdapter(ModelAdapter):
    """OpenAI / GPT-4o 适配器。"""

    def __init__(self, api_key: str = '', api_url: str = '',
                 model: str = 'gpt-4o'):
        super().__init__(AdapterMeta(
            name=f'OpenAI {model}',
            adapter_id=f'openai_{model.replace("-", "_")}',
            provider='openai',
        ))
        self._api_key = api_key
        self._api_url = api_url or 'https://api.openai.com/v1/chat/completions'
        self._model = model

    def is_available(self) -> bool:
        return bool(self._api_key)

    def chat(self, messages: list[dict], **kwargs) -> Result:
        if not self._api_key:
            return err(ErrorCode.AUTH,
                       'OpenAI API Key 未配置（设环境变量 OPENAI_API_KEY）',
                       fallback='在 zero_config.json 中配置 openai.api_key')

        try:
            payload = json.dumps({
                'model': kwargs.get('model', self._model),
                'messages': messages,
                'max_tokens': kwargs.get('max_tokens', 2000),
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
            return err(ErrorCode.MODEL_EMPTY_RESPONSE, 'OpenAI 返回空内容')

        except Exception as exc:
            logger.warning('OpenAI chat failed: %s', exc)
            return err(ErrorCode.MODEL_UNAVAILABLE, f'OpenAI: {exc}',
                       retryable=True)

    def capabilities(self) -> dict[str, float]:
        return dict(_BENCHMARK)

    def cost_per_1k_tokens(self) -> float:
        if 'mini' in self._model:
            return 0.001   # GPT-4o-mini ~¥0.001/1K
        return 0.07        # GPT-4o ~¥0.07/1K
