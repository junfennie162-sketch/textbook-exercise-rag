"""LLM 连通性探测与本地模型拉取。

- GET /api/llm/status：按当前配置的通道（云端 / Ollama）实测「列模型」请求。
  排查两类常见问题：Ollama 没启动；模型没拉取 / 名称写错。不产生对话费用。
- POST /api/llm/pull：调用本地 Ollama 原生接口拉取模型，实时转发进度（NDJSON 流）。
  模型名做白名单校验，避免把任意串拼进请求。
"""
import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.llm import resolve_llm_endpoint
from app.services import ollama_env

router = APIRouter(prefix="/api", tags=["工程状态"])

_PROBE_TIMEOUT_SECONDS = 8.0
_MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")


@router.get("/llm/status", summary="探测当前 LLM 通道连通性（列模型，不产生对话费用）")
async def llm_status() -> dict:
    cfg = get_settings()
    mode = cfg.llm_mode()
    if mode == "mock":
        return {
            "mode": "mock",
            "ok": True,
            "model": None,
            "message": "离线模板模式：不访问任何外部服务，无需探测",
            "models": [],
        }

    endpoint = resolve_llm_endpoint(cfg)
    client = AsyncOpenAI(
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    try:
        page = await client.models.list()
        # Ollama 在「一个模型都还没装好」时返回 data:null，这里统一按空列表处理
        model_ids = sorted({item.id for item in (page.data or [])})
    except Exception as exc:  # 连不上 / 鉴权失败 / 超时，均转成可读提示
        hint = (ollama_env.ollama_failure_hint(cfg.ollama_model)
                if endpoint.provider == "ollama"
                else "请检查 LLM_BASE_URL / LLM_API_KEY 是否正确、网络是否可达")
        return {
            "mode": mode,
            "ok": False,
            "provider": endpoint.provider,
            "base_url": endpoint.base_url,
            "model": endpoint.model,
            "ollama_installed": ollama_env.ollama_installed(),
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "hint": hint,
            "models": [],
        }
    finally:
        await client.close()

    model_present = endpoint.model in model_ids
    message = "连接正常" if model_present else (
        f"连接正常，但端点上未见模型「{endpoint.model}」，请拉取/核对模型名")
    return {
        "mode": mode,
        "ok": True,
        "provider": endpoint.provider,
        "base_url": endpoint.base_url,
        "model": endpoint.model,
        "model_present": model_present,
        "ollama_installed": ollama_env.ollama_installed(),
        "ollama_running": True if endpoint.provider == "ollama" else None,
        "message": message,
        "models": model_ids[:30],
    }


# ==================== 本地 Ollama 模型拉取（进度流） ====================

class PullRequest(BaseModel):
    model: str = Field(..., description="Ollama 模型名，如 qwen2.5:3b")


def _ollama_native_base() -> str:
    """把 OpenAI 兼容地址（…:11434/v1）还原为 Ollama 原生地址（…:11434）。"""
    cfg = get_settings()
    base = (cfg.ollama_base_url or "").rstrip("/")
    for suffix in ("/v1", "/api"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base


@router.post("/llm/pull", summary="拉取本地 Ollama 模型（NDJSON 进度流，仅本机操作）")
async def pull_ollama_model(req: PullRequest) -> StreamingResponse:
    """转发 Ollama 原生 /api/pull 的进度流：{type: progress|done|error, status, percent}。

    前端据此展示下载进度；模型名做白名单校验（字母/数字/._:/-），不合法直接 400。
    """
    model = req.model.strip()
    if not _MODEL_NAME_PATTERN.match(model):
        raise HTTPException(status_code=400,
                            detail="模型名不合法（仅允许字母、数字与 . _ : / -，长度 1~80）")
    base = _ollama_native_base()

    async def event_stream():
        import httpx  # 局部导入：httpx 随 openai 依赖提供，避免顶层硬依赖
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", f"{base}/api/pull",
                                         json={"model": model, "stream": True}) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "ignore")[:200]
                        yield json.dumps({"type": "error", "model": model,
                                          "message": f"Ollama 返回 {response.status_code}：{body}"},
                                         ensure_ascii=False) + "\n"
                        return
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        total = event.get("total") or 0
                        payload = {"type": "progress", "model": model,
                                   "status": event.get("status", ""),
                                   "completed": event.get("completed"),
                                   "total": total or None}
                        if total:
                            payload["percent"] = round(
                                (event.get("completed") or 0) / total * 100, 1)
                        yield json.dumps(payload, ensure_ascii=False) + "\n"
                        if event.get("status") == "success":
                            break
            yield json.dumps({"type": "done", "model": model, "ok": True},
                             ensure_ascii=False) + "\n"
        except Exception as exc:  # 连不上 Ollama / 中断：给可读原因与排查方向
            yield json.dumps({
                "type": "error", "model": model,
                "message": f"{type(exc).__name__}: {exc}"[:200],
                "hint": ollama_env.ollama_failure_hint(model),
            }, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
