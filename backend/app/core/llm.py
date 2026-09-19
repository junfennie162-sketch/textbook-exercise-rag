"""LLM 客户端工厂（Anthropic 兼容端点，如智谱 GLM）。"""
from anthropic import AsyncAnthropic

from app.core.config import Settings, get_settings


def create_llm_client(settings: Settings | None = None) -> AsyncAnthropic:
    cfg = settings or get_settings()
    return AsyncAnthropic(
        base_url=cfg.llm_base_url,
        api_key=cfg.llm_api_key,
    )
