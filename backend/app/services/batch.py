"""4.1 批量解析生成与任务管理（asyncio + 内存状态机）。"""
import asyncio
import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services import citation as citation_service
from app.services import retriever, verifier
from app.services.guard import is_incomplete_by_rule
from app.services.llm_service import stream_analysis
from app.store import documents as doc_store


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QuestionTask(BaseModel):
    question_id: int
    status: TaskStatus = TaskStatus.PENDING
    solution_id: str | None = None
    blocked_type: str | None = None
    result: str | None = None
    error: str | None = None


class BatchJob(BaseModel):
    batch_id: str
    status: TaskStatus = TaskStatus.PENDING
    tasks: dict[int, QuestionTask] = Field(default_factory=dict)
    questions: dict[int, str] = Field(default_factory=dict)
    cancelled: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


def summarize(job: BatchJob) -> dict:
    counter: dict[str, int] = {}
    for task in job.tasks.values():
        counter[task.status.value] = counter.get(task.status.value, 0) + 1
    done = sum(counter.get(s, 0) for s in ("success", "failed", "cancelled"))
    return {"total": len(job.tasks), "done": done, "detail": counter}


class BatchManager:
    def __init__(self):
        self.jobs: dict[str, BatchJob] = {}
        self._store = None

    def create_job(self, questions: list[str]) -> BatchJob:
        job = BatchJob(
            batch_id=uuid.uuid4().hex,
            tasks={i: QuestionTask(question_id=i) for i in range(len(questions))},
            questions={i: text for i, text in enumerate(questions)},
        )
        self.jobs[job.batch_id] = job
        self._evict_finished_jobs()
        # 落库任务记录（任务状态机仍在内存中运行，数据库保存结果供历史查询）
        doc_store.save_batch_job(job.batch_id, len(questions),
                                 job.created_at.isoformat(timespec="seconds"))
        doc_store.save_batch_tasks(job.batch_id, [
            {"question_id": i, "question": text, "status": "pending"}
            for i, text in enumerate(questions)
        ])
        return job

    def running_count(self) -> int:
        """正在排队或执行中的任务数（用于限制同时运行的批量任务）。"""
        return sum(1 for job in self.jobs.values()
                   if job.status in (TaskStatus.PENDING, TaskStatus.RUNNING))

    def _evict_finished_jobs(self, keep: int = 20) -> None:
        """只保留最近若干已完成任务，避免长时间运行后内存无界增长。"""
        if len(self.jobs) <= keep:
            return
        for batch_id, job in list(self.jobs.items()):
            if len(self.jobs) <= keep:
                break
            if job.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
                self.jobs.pop(batch_id, None)

    async def run_job(self, batch_id: str) -> None:
        """并发执行任务（Semaphore 限流）：单题失败不影响其他题，可随时中断。

        外层 try/finally 兜底：即使初始化向量库或汇总环节抛异常，任务也必须落到
        终态（failed），否则 RUNNING 状态会永久占用 batch_max_jobs 名额。
        """
        job = self.jobs.get(batch_id)
        if job is None:
            return
        job.status = TaskStatus.RUNNING
        try:
            if self._store is None:
                self._store = retriever.get_default_store()

            semaphore = asyncio.Semaphore(max(1, get_settings().batch_concurrency))

            async def run_task(task: QuestionTask) -> None:
                async with semaphore:
                    if job.cancelled:
                        task.status = TaskStatus.CANCELLED
                        self._persist_task(batch_id, task)
                        return
                    task.status = TaskStatus.RUNNING
                    try:
                        solution_id, blocked_type = await self._solve_one(
                            job.questions[task.question_id])
                        task.solution_id = solution_id
                        task.blocked_type = blocked_type
                        task.status = TaskStatus.SUCCESS
                    except Exception as exc:  # 单题失败不影响其他题
                        task.status = TaskStatus.FAILED
                        task.error = str(exc)
                    self._persist_task(batch_id, task)

            await asyncio.gather(*(run_task(task) for task in job.tasks.values()))

            if job.cancelled:
                job.status = TaskStatus.CANCELLED
            elif any(task.status is TaskStatus.SUCCESS for task in job.tasks.values()):
                job.status = TaskStatus.SUCCESS
            else:
                job.status = TaskStatus.FAILED  # 全部失败：据实标注，不谎报成功
        except Exception:
            job.status = TaskStatus.FAILED
        finally:
            # 无论成功失败，都向数据库写入终态（此前 RUNNING 任务一旦异常就永久卡住）
            doc_store.finish_batch_job(batch_id, job.status.value,
                                       datetime.now().isoformat(timespec="seconds"))

    @staticmethod
    def _persist_task(batch_id: str, task: QuestionTask) -> None:
        doc_store.update_batch_task(
            batch_id, task.question_id, task.status.value,
            solution_id=task.solution_id, blocked_type=task.blocked_type,
            error=task.error,
        )

    async def _solve_one(self, question: str) -> tuple[str, str | None]:
        """单题完整链路：校验 -> 检索 -> 生成 -> 校验引用 -> 步骤验算 -> 落库。

        与单题接口（api/solve.py）保持同一套口径：批量结果同样携带 step_check，
        否则历史记录与导出里批量解析会缺失验算信息。
        """
        if is_incomplete_by_rule(question):
            solution_id = self._save(question, status="blocked",
                                     answer_text="", sources={}, blocked="incomplete")
            return solution_id, "incomplete"

        result = retriever.retrieve_with_fallback(question, store=self._store)
        if result["fallback"]:
            solution_id = self._save(question, status="blocked",
                                     answer_text="", sources={}, blocked="no_evidence")
            return solution_id, "no_evidence"

        answer = "".join([piece async for piece in stream_analysis(question, result["context"])])
        answer = citation_service.validate_and_fix_citations(answer, result["source_map"])
        answer = citation_service.ensure_source_section(answer, result["source_map"])
        step_check = verifier.verify_steps(answer)
        solution_id = self._save(question, status="ok", answer_text=answer,
                                 sources=result["source_map"], blocked=None,
                                 step_check=step_check)
        return solution_id, None

    @staticmethod
    def _save(question: str, status: str, answer_text: str, sources: dict,
              blocked: str | None, step_check: dict | None = None) -> str:
        solution_id = uuid.uuid4().hex[:16]
        doc_store.save_solution({
            "solution_id": solution_id,
            "question_text": question,
            "status": status,
            "blocked_type": blocked,
            "answer_text": answer_text,
            "sources": sources,
            "step_check": step_check if step_check is not None else verifier.verify_steps(""),
            "mode": get_settings().llm_mode(),
            "model": get_settings().llm_active_model(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        return solution_id

    def cancel_job(self, batch_id: str) -> None:
        self.jobs[batch_id].cancelled = True


_manager: BatchManager | None = None


def get_batch_manager() -> BatchManager:
    global _manager
    if _manager is None:
        _manager = BatchManager()
    return _manager
