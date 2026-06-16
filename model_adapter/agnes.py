"""Agnes 适配器
================
Agnes AI 免费 API 适配器（文本 + 图像）。

文本: agnes-2.0-flash（免费，轻量）
图像: agnes-image-2.1-flash（免费生图）
"""

import json
import urllib.request

from config import AGNES_API_URL, AGNES_IMAGE_URL, get_agnes_key, get_logger
from model_adapter.base import AdapterMeta, ModelAdapter
from utils.result import Result, ErrorCode, ok, err

logger = get_logger('zero.adapter.agnes')

# Agnes 2.0 Flash 静态基准（来源: 实测 + 社区反馈）
_BENCHMARK = {
    'code_generation': 0.72,
    'code_review': 0.68,
    'debugging': 0.65,
    'reasoning': 0.70,
    'chat': 0.76,
    'translation': 0.74,
    'summarization': 0.75,
    'image_generation': 0.70,
    'image_understanding': 0.0,
    'search': 0.0,
    'file_ops': 0.0,
    'browser_control': 0.0,
}


class AgnesAdapter(ModelAdapter):
    """Agnes AI 适配器。"""

    def __init__(self, api_key: str = ''):
        super().__init__(AdapterMeta(
            name='Agnes 2.0 Flash',
            adapter_id='agnes_flash',
            provider='agnes',
            is_free=True,
        ))
        self._api_key = api_key or get_agnes_key()
        self._text_url = AGNES_API_URL
        self._image_url = AGNES_IMAGE_URL

    def is_available(self) -> bool:
        return bool(self._api_key)

    def chat(self, messages: list[dict], **kwargs) -> Result:
        if not self._api_key:
            return err(ErrorCode.AUTH, 'Agnes API Key 未配置',
                       fallback='设环境变量 AGNES_API_KEY 或 keyring')

        try:
            payload = json.dumps({
                'model': kwargs.get('model', 'agnes-2.0-flash'),
                'messages': messages,
                'max_tokens': kwargs.get('max_tokens', 2000),
            }).encode('utf-8')

            req = urllib.request.Request(
                self._text_url,
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
            return err(ErrorCode.MODEL_EMPTY_RESPONSE, 'Agnes 返回空内容')

        except Exception as exc:
            logger.warning('Agnes chat failed: %s', exc)
            return err(ErrorCode.MODEL_UNAVAILABLE, f'Agnes: {exc}',
                       retryable=True)

    def image_generate(self, prompt: str, **kwargs) -> Result:
        """调用 Agnes Image API 生图。"""
        if not self._api_key:
            return err(ErrorCode.AUTH, 'Agnes API Key 未配置')

        try:
            payload = json.dumps({
                'model': kwargs.get('model', 'agnes-image-2.1-flash'),
                'prompt': prompt,
                'n': kwargs.get('n', 1),
                'size': kwargs.get('size', '1024x1024'),
            }).encode('utf-8')

            req = urllib.request.Request(
                self._image_url,
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self._api_key}',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=kwargs.get('timeout', 90)) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            img_url = data['data'][0].get('url', '')
            if img_url:
                return ok({'url': img_url, 'prompt': prompt})
            return err(ErrorCode.MODEL_EMPTY_RESPONSE, 'Agnes 生图未返回 URL')

        except Exception as exc:
            logger.warning('Agnes image gen failed: %s', exc)
            return err(ErrorCode.MODEL_UNAVAILABLE, f'Agnes 生图: {exc}',
                       retryable=True)

    def capabilities(self) -> dict[str, float]:
        return dict(_BENCHMARK)

    def cost_per_1k_tokens(self) -> float:
        return 0.0  # 免费
