"""3.2 单题解析 SSE 流式生成 + 4.2 边界前置校验 + 3.3 引用标注 + 4.4 步骤验算。"""
import json
import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.services import citation as citation_service
from app.services import guard, retriever, verifier
from app.services.llm_service import stream_analysis
from app.store import documents as doc_store

router = APIRouter(prefix="/api", tags=["解析生成"])


class SolveRequest(BaseModel):
    question_text: str


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _error_events(exc: Exception, hint: str) -> list[str]:
    """把异常转成 SSE 错误事件对：error（可读原因+排查方向）→ done(error)。

    检索与生成两条链路共用，保证任何一环失败都不会静默断流。
    """
    return [
        _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"[:300], "hint": hint}),
        _sse({"type": "done", "status": "error"}),
    ]


_RETRIEVAL_HINT = ("检索失败：请确认嵌入模型缓存（backend/models_cache）与向量库（backend/chroma_db）"
                   "可用；若是全新环境，请先上传教材并等待首次模型加载完成。")
_LLM_HINT = ("请检查模型通道（顶栏徽标可探测连通性）：云端可能是余额不足或 Key 失效，"
             "本地可能是 Ollama 未启动或模型未拉取。")


@router.post("/solve", summary="单题解析（SSE 流式）")
async def solve(req: SolveRequest) -> StreamingResponse:
    question = req.question_text.strip()

    async def event_generator():
        if guard.is_incomplete_by_rule(question):
            blocked = guard.build_error_response("incomplete", "题干过短或缺少必要条件")
            yield _sse({"type": "blocked", **blocked})
            yield _sse({"type": "done", "status": "blocked"})
            return

        # 检索也可能失败（模型缓存缺失 / 向量库损坏）：同样以 error 事件收尾，不静默断流
        try:
            result = retriever.retrieve_with_fallback(question)
        except Exception as exc:
            for event in _error_events(exc, _RETRIEVAL_HINT):
                yield event
            return
        if result["fallback"]:
            blocked = guard.build_error_response("no_evidence", result["message"])
            yield _sse({"type": "blocked", **blocked})
            yield _sse({"type": "done", "status": "blocked"})
            return

        yield _sse({"type": "sources", "sources": result["source_map"]})

        answer_parts: list[str] = []
        try:
            async for piece in stream_analysis(question, result["context"]):
                answer_parts.append(piece)
                yield _sse({"type": "chunk", "content": piece})
        except Exception as exc:
            # 模型调用失败（云端余额不足 / Ollama 未启动 / 断网超时等）：
            # 以 error 事件明确告知前端，而不是让 SSE 流静默断掉卡住界面
            for event in _error_events(exc, _LLM_HINT):
                yield event
            return

        answer = citation_service.validate_and_fix_citations(
            "".join(answer_parts), result["source_map"])
        answer = citation_service.ensure_source_section(answer, result["source_map"])
        step_check = verifier.verify_steps(answer)
        solution_id = uuid.uuid4().hex[:16]
        doc_store.save_solution({
            "solution_id": solution_id,
            "question_text": question,
            "status": "ok",
            "blocked_type": None,
            "answer_text": answer,
            "sources": result["source_map"],
            "step_check": step_check,
            # 记录生成模式（离线模板 / 本地 Ollama / 云端 API）与当时使用的模型，历史记录页据此标注
            "mode": get_settings().llm_mode(),
            "model": get_settings().llm_active_model(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        yield _sse({"type": "done", "status": "ok", "solution_id": solution_id,
                    "step_check": step_check})

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
