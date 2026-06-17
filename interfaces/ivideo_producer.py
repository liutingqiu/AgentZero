"""视频生产接口

实现此接口接入 MoneyPrinterTurbo / NewsFactory 等视频管线。
"""

from typing import Protocol, TypedDict


class VideoResult(TypedDict):
    success: bool
    video_path: str | None
    error: str | None


class IVideoProducer(Protocol):
    """视频生产者接口。"""

    def produce(self, script: str, config: dict | None = None) -> VideoResult:
        """根据脚本生成视频。"""
        ...


class NullVideoProducer:
    """默认无操作视频生产者。"""

    def produce(self, script: str,
                config: dict | None = None) -> VideoResult:
        return {
            'success': False,
            'video_path': None,
            'error': '未配置视频生产者',
        }


# 全局实例
video_producer: IVideoProducer = NullVideoProducer()
