"""模型与参数设置接口：规格下发 / 保存（热生效）/ 恢复默认。

安全约定：
- GET 不回显 Key 明文（只留尾 4 位）；PUT 收到掩码或空值表示"不修改"；
- 只接受规格表（runtime_settings.SETTINGS_SPEC）声明的字段，数值按 min/max 截断；
- 保存后 get_settings.cache_clear() → 全项目热生效（无需重启后端）。
"""
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core import runtime_settings as rt
from app.core.config import get_settings

router = APIRouter(prefix="/api/settings", tags=["模型设置"])


def _current_value(key: str) -> Any:
    cfg = get_settings()
    if key == rt.KEY_FIELD:
        return rt.mask_key(cfg.llm_api_key)
    return getattr(cfg, key)


def _snapshot() -> dict:
    cfg = get_settings()
    return {
        "spec": rt.SETTINGS_SPEC,
        "values": {item["key"]: _current_value(item["key"]) for item in rt.SETTINGS_SPEC},
        "overridden": sorted(rt.load_overrides().keys()),
        "mode": cfg.llm_mode(),
        "provider": cfg.llm_provider,
        "model": cfg.llm_active_model(),
        "mock": cfg.llm_mock,
        "file": str(rt.runtime_path()),
    }


class SettingsUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict, description="待保存的参数键值对")


@router.get("", summary="可调参数规格与当前值（Key 掩码回显，含覆盖来源）")
async def read_settings() -> dict:
    return _snapshot()


@router.put("", summary="保存参数（白名单 + 截断，保存即热生效）")
async def update_settings(payload: SettingsUpdate) -> dict:
    accepted, rejected = rt.apply_overrides(payload.values)
    get_settings.cache_clear()   # 关键一步：让所有 get_settings() 调用方立刻拿到新值
    snapshot = _snapshot()
    return {
        "saved": sorted(accepted.keys()),
        "rejected": rejected,
        "hot_applied": True,
        **{key: snapshot[key] for key in ("mode", "provider", "model", "overridden")},
    }


@router.post("/reset", summary="恢复默认（清除全部覆盖值，回到 .env / 默认配置）")
async def reset_settings() -> dict:
    rt.reset_overrides()
    get_settings.cache_clear()
    snapshot = _snapshot()
    return {"reset": True, **{key: snapshot[key] for key in ("mode", "provider", "model", "values", "overridden")}}
