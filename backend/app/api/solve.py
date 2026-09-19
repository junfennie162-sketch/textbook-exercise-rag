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


@router.post("/solve", summary="单题解析（SSE 流式）")
async def solve(req: SolveRequest) -> StreamingResponse:
    question = req.question_text.strip()

    async def event_generator():
        if guard.is_incomplete_by_rule(question):
            blocked = guard.build_error_response("incomplete", "题干过短或缺少必要条件")
            yield _sse({"type": "blocked", **blocked})
            yield _sse({"type": "done", "status": "blocked"})
            return

        result = retriever.retrieve_with_fallback(question)
        if result["fallback"]:
            blocked = guard.build_error_response("no_evidence", result["message"])
            yield _sse({"type": "blocked", **blocked})
            yield _sse({"type": "done", "status": "blocked"})
            return

        yield _sse({"type": "sources", "sources": result["source_map"]})

        answer_parts: list[str] = []
        async for piece in stream_analysis(question, result["context"]):
            answer_parts.append(piece)
            yield _sse({"type": "chunk", "content": piece})

        answer = citation_service.validate_and_fix_citations(
            "".join(answer_parts), result["source_map"])
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
            # 记录生成模式（离线模板 / 真实大模型），历史记录页据此标注
            "mode": "mock" if get_settings().llm_mock else "live",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        yield _sse({"type": "done", "status": "ok", "solution_id": solution_id,
                    "step_check": step_check})

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
