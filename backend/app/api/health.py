from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse


router = APIRouter(prefix="/api", tags=["工程状态"])


@router.get("/health", response_model=HealthResponse, summary="检查后端运行状态")
def get_health() -> HealthResponse:
    cfg = get_settings()
    return HealthResponse(
        status="UP",
        message="前后端连接正常",
        llm_mock=cfg.llm_mock,
        llm_mode=cfg.llm_mode(),
        llm_provider=cfg.llm_provider,
        llm_model=cfg.llm_active_model(),
    )
