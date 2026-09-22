"""4.1 批量解析接口：立即返回 batch_id，后台异步执行，支持进度查询与中断。"""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.batch import get_batch_manager, summarize

router = APIRouter(prefix="/api/batch", tags=["批量任务"])

# 保持后台任务的强引用：asyncio 只对任务持弱引用，不保存的话任务可能被 GC 提前回收
_running_tasks: set[asyncio.Task] = set()


class BatchRequest(BaseModel):
    questions: list[str]


@router.post("/parse", summary="创建批量解析任务")
async def create_batch(req: BatchRequest) -> dict:
    questions = [q.strip() for q in req.questions if q.strip()]
    if not questions:
        raise HTTPException(status_code=400, detail="题目列表不能为空")

    cfg = get_settings()
    if len(questions) > cfg.batch_max_questions:
        raise HTTPException(
            status_code=400,
            detail=f"单次批量最多 {cfg.batch_max_questions} 道题（当前 {len(questions)} 道），请拆分后再提交",
        )

    manager = get_batch_manager()
    if manager.running_count() >= cfg.batch_max_jobs:
        raise HTTPException(
            status_code=429,
            detail=f"同时运行的批量任务已达上限（{cfg.batch_max_jobs} 个），请等待任务结束或先中断",
        )

    job = manager.create_job(questions)
    task = asyncio.create_task(manager.run_job(job.batch_id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return {"batch_id": job.batch_id, "total": len(questions)}


@router.get("/{batch_id}", summary="查询批量任务进度")
async def batch_status(batch_id: str) -> dict:
    manager = get_batch_manager()
    job = manager.jobs.get(batch_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "batch_id": batch_id,
        "status": job.status.value,
        "progress": summarize(job),
        "cancelled": job.cancelled,
        "tasks": [
            {
                "question_id": t.question_id,
                "status": t.status.value,
                "solution_id": t.solution_id,
                "blocked_type": t.blocked_type,
                "error": t.error,
                "question": job.questions[t.question_id],
            }
            for t in job.tasks.values()
        ],
    }


@router.post("/{batch_id}/cancel", summary="中断批量任务")
async def batch_cancel(batch_id: str) -> dict:
    manager = get_batch_manager()
    if batch_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="任务不存在")
    manager.cancel_job(batch_id)
    return {"ok": True}


