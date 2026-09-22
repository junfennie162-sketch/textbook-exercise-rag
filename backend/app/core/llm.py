"""LLM 客户端工厂：云端 API 与本地 Ollama 双通道，统一 OpenAI 兼容协议。

两种连接模型的方式（由 .env 的 LLM_PROVIDER 切换，参照 rag_law 模板的切换设计）：
- cloud  云端 API：LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
         （智谱 GLM、DeepSeek 等任何 OpenAI 兼容端点，需联网与 Key）
- ollama 本地模型：OLLAMA_BASE_URL / OLLAMA_MODEL
         （默认 http://localhost:11434/v1，零费用、断网可用，Key 仅占位）

两条通道共用同一条 chat.completions 代码路径（services/llm_service.py），
上层只需 create_llm_client() + resolve_llm_endpoint()，对具体后端完全无感。
"""
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class LLMEndpoint:
    """一次生成的目标端点（provider 决定从哪组配置取值）。"""

    provider: str  # cloud | ollama
    base_url: str
    model: str
    api_key: str


def resolve_llm_endpoint(settings: Settings | None = None) -> LLMEndpoint:
    """按当前配置解析目标端点：ollama 走本地配置，其余一律云端配置。"""
    cfg = settings or get_settings()
    if cfg.llm_provider == "ollama":
        return LLMEndpoint(
            provider="ollama",
            base_url=cfg.ollama_base_url,
            model=cfg.ollama_model,
            api_key=cfg.ollama_api_key,
        )
    return LLMEndpoint(
        provider="cloud",
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,
    )


def create_llm_client(settings: Settings | None = None) -> AsyncOpenAI:
    """获取 LLM 客户端（工厂函数）：始终返回 OpenAI 兼容的 AsyncOpenAI。

    Key 为空时填 "EMPTY" 占位：客户端可以正常构造，鉴权错误（401）由服务端
    返回并被 /api/llm/status 转成可读提示，而不是在本地直接抛构造异常。
    """
    endpoint = resolve_llm_endpoint(settings)
    return AsyncOpenAI(base_url=endpoint.base_url, api_key=endpoint.api_key or "EMPTY")
