from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="后端运行状态")
    message: str = Field(description="前后端连通提示")
    llm_mock: bool = Field(default=False, description="是否处于离线模板模式（未接入大模型）")
