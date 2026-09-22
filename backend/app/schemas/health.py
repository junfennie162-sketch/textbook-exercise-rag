from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="后端运行状态")
    message: str = Field(description="前后端连通提示")
    llm_mock: bool = Field(default=False, description="是否处于离线模板模式（未接入大模型）")
    llm_mode: str = Field(default="cloud", description="当前生成模式：mock 离线模板 / ollama 本地模型 / cloud 云端 API")
    llm_provider: str = Field(default="cloud", description="配置的模型通道：cloud 云端 / ollama 本地")
    llm_model: str = Field(default="", description="当前实际使用的模型名（云端或 Ollama）")
