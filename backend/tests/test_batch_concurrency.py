"""批量任务并发执行测试：Semaphore 限流、中断语义与任务记录落库。"""
import asyncio

import pytest

from app.core.config import Settings
from app.services.batch import BatchManager, TaskStatus
from app.store.db import connect, init_db


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, batch_concurrency=3)
    monkeypatch.setattr("app.store.db.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.batch.get_settings", lambda: settings)
    init_db()
    return settings


def test_job_runs_tasks_concurrently_within_limit(isolated, monkeypatch) -> None:
    manager = BatchManager()
    manager._store = object()                       # 隔离向量库（本测试不检索）
    state = {"active": 0, "peak": 0}

    async def fake_solve(self, question):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return f"sol-{question}", None

    monkeypatch.setattr(BatchManager, "_solve_one", fake_solve)

    job = manager.create_job([f"题目{i}" for i in range(9)])
    asyncio.run(manager.run_job(job.batch_id))

    assert all(task.status == TaskStatus.SUCCESS for task in job.tasks.values())
    assert state["peak"] == 3                       # 并发度受 Semaphore 限制
    assert all(task.solution_id for task in job.tasks.values())


def test_concurrency_one_runs_sequentially(isolated, monkeypatch) -> None:
    settings = Settings(data_dir=isolated.data_dir, batch_concurrency=1)
    monkeypatch.setattr("app.services.batch.get_settings", lambda: settings)

    manager = BatchManager()
    manager._store = object()
    state = {"active": 0, "peak": 0}

    async def fake_solve(self, question):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.02)
        state["active"] -= 1
        return "sol", None

    monkeypatch.setattr(BatchManager, "_solve_one", fake_solve)
    job = manager.create_job(["a", "b", "c", "d"])
    asyncio.run(manager.run_job(job.batch_id))

    assert state["peak"] == 1                       # 并发度可配置为 1（退化为串行）


def test_failed_task_does_not_stop_others(isolated, monkeypatch) -> None:
    manager = BatchManager()
    manager._store = object()

    async def flaky_solve(self, question):
        if "坏题" in question:
            raise RuntimeError("模型超时")
        return "sol", None

    monkeypatch.setattr(BatchManager, "_solve_one", flaky_solve)
    job = manager.create_job(["好题一", "坏题", "好题二"])
    asyncio.run(manager.run_job(job.batch_id))

    statuses = {task.question_id: task.status for task in job.tasks.values()}
    assert statuses[0] == TaskStatus.SUCCESS
    assert statuses[1] == TaskStatus.FAILED
    assert statuses[2] == TaskStatus.SUCCESS
    assert job.tasks[1].error == "模型超时"


def test_cancelled_job_marks_all_tasks_cancelled(isolated, monkeypatch) -> None:
    manager = BatchManager()
    manager._store = object()

    async def fake_solve(self, question):            # pragma: no cover - 不应被调用
        raise AssertionError("已中断的任务不应继续解题")

    monkeypatch.setattr(BatchManager, "_solve_one", fake_solve)
    job = manager.create_job(["a", "b", "c"])
    manager.cancel_job(job.batch_id)
    asyncio.run(manager.run_job(job.batch_id))

    assert all(task.status == TaskStatus.CANCELLED for task in job.tasks.values())
    assert job.status == TaskStatus.CANCELLED


def test_job_and_tasks_persisted(isolated, monkeypatch) -> None:
    manager = BatchManager()
    manager._store = object()

    async def fake_solve(self, question):
        return "sol-1", None

    monkeypatch.setattr(BatchManager, "_solve_one", fake_solve)
    job = manager.create_job(["题一", "题二"])
    asyncio.run(manager.run_job(job.batch_id))

    with connect() as conn:
        job_row = conn.execute("SELECT * FROM batch_jobs WHERE batch_id = ?",
                              (job.batch_id,)).fetchone()
        task_rows = conn.execute("SELECT * FROM batch_tasks WHERE batch_id = ? "
                                 "ORDER BY question_id", (job.batch_id,)).fetchall()
    assert job_row["total"] == 2 and job_row["status"] == "success" and job_row["finished_at"]
    assert [row["status"] for row in task_rows] == ["success", "success"]
    assert task_rows[0]["solution_id"] == "sol-1"


def test_running_count_and_job_history_cap(isolated) -> None:
    """running_count 只统计未结束任务；已结束任务记录只保留最近若干条。"""
    manager = BatchManager()
    job = manager.create_job(["a"])
    assert manager.running_count() == 1            # 新建任务处于 pending
    job.status = TaskStatus.SUCCESS
    assert manager.running_count() == 0

    for index in range(25):
        extra = manager.create_job([f"题{index}"])
        extra.status = TaskStatus.SUCCESS
    assert len(manager.jobs) <= 20                 # 记录不会无界增长


def test_create_batch_rejects_too_many_questions(isolated, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.api import batch as batch_api
    from app.main import app

    manager = BatchManager()
    monkeypatch.setattr(batch_api, "get_batch_manager", lambda: manager)
    client = TestClient(app)

    response = client.post("/api/batch/parse", json={"questions": ["题"] * 101})
    assert response.status_code == 400
    assert "最多" in response.json()["detail"]
    assert manager.jobs == {}                      # 被拒绝时不创建任务


def test_create_batch_rejects_when_too_many_running(isolated, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.api import batch as batch_api
    from app.main import app

    manager = BatchManager()
    for index in range(3):                         # 3 个任务处于排队中
        manager.create_job([f"已有题{index}"])
    monkeypatch.setattr(batch_api, "get_batch_manager", lambda: manager)
    client = TestClient(app)

    response = client.post("/api/batch/parse", json={"questions": ["新题"]})
    assert response.status_code == 429
    assert "上限" in response.json()["detail"]
