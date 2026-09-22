"""功能优化回归测试。

覆盖本轮修复的关键行为：
- 检索异常也走 SSE error 事件（不再静默断流）
- 引用标注模式宽化与归一化（[来源 1] / 【来源2】 / [参考资料1] / 区间）
- 图片/上题类题干按信息不全拦截
- 批量任务终态据实（全部失败 → failed；初始化异常不死锁）
- 批量解析携带步骤验算（与单题口径一致）
- 扫描版 PDF（无文本块）拒绝入库且不留临时文件
- 评测报告损坏时接口降级而非 500
- π 系数退化输入不抛异常
- 默认向量库进程级单例
"""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.store.db import init_db

client = TestClient(app)


def _parse_sse(text: str) -> list[dict]:
    return [json.loads(line[5:].strip()) for line in text.splitlines()
            if line.startswith("data: ")]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, batch_concurrency=3)
    monkeypatch.setattr("app.store.db.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.batch.get_settings", lambda: settings)
    init_db()
    return settings


# ------------------------------------------------------------ solve 检索异常

def test_solve_stream_reports_retrieval_failure(monkeypatch) -> None:
    """检索层异常（模型缓存缺失/向量库损坏）也要以 error 事件收尾，不静默断流。"""
    from app.services import retriever as retriever_mod

    def boom(*args, **kwargs):
        raise RuntimeError("chroma_db 无法打开")

    monkeypatch.setattr(retriever_mod, "retrieve_with_fallback", boom)

    response = client.post("/api/solve", json={"question_text": "计算 log2 8 的值。"})

    events = _parse_sse(response.text)
    types = [e["type"] for e in events]
    assert types == ["error", "done"]
    assert events[0]["hint"]
    assert "chroma_db" in events[0]["message"]
    assert events[-1]["status"] == "error"


# ------------------------------------------------------------ 引用模式宽化

def test_validate_citations_normalizes_variants() -> None:
    from app.services.citation import build_source_map, validate_and_fix_citations

    items = [
        {"chunk_id": "c1", "text": "定义", "metadata": {"source_file": "教材.pdf"}},
        {"chunk_id": "c2", "text": "公式", "metadata": {"source_file": "教材.pdf"}},
    ]
    source_map = build_source_map(items)
    text = "见[来源 1]、【来源2】与[参考资料1]，另见[来源9]和[来源1-3]。"

    fixed = validate_and_fix_citations(text, source_map)

    assert "[来源1]" in fixed and "[来源2]" in fixed
    assert "[来源1][来源2]" in fixed      # 区间展开为可点击的单编号连写（前端按 [来源N] 解析）
    assert "来源9" not in fixed           # 不存在的来源被移除
    assert "【" not in fixed and "参考资料" not in fixed  # 统一归一化为 [来源N]


def test_validate_citations_removes_all_when_nothing_matches() -> None:
    from app.services.citation import build_source_map, validate_and_fix_citations

    source_map = build_source_map([
        {"chunk_id": "c1", "text": "定义", "metadata": {"source_file": "教材.pdf"}}])
    assert validate_and_fix_citations("依据[来源5]与[参考资料9]。", source_map) == "依据与。"


# ------------------------------------------------------------ 题干边界规则

def test_guard_blocks_figure_and_reference_questions() -> None:
    from app.services.guard import is_incomplete_by_rule

    # 引用题图：系统看不到图片，按信息不全拦截（原实现中"如图"分支永远不可达）
    assert is_incomplete_by_rule("如图，在三角形 ABC 中，AB=3，求 BC 的长。")
    assert is_incomplete_by_rule("见下图，求阴影部分面积。")
    assert is_incomplete_by_rule("用上题结论求解")
    # 完整题目不受影响
    assert not is_incomplete_by_rule("已知 a=3，b=4，求 a+b 的值。")


# ------------------------------------------------------------ 批量终态与验算

def test_batch_all_failed_marks_job_failed(isolated, monkeypatch) -> None:
    from app.services.batch import BatchManager, TaskStatus

    manager = BatchManager()
    manager._store = object()

    async def boom(self, question):
        raise RuntimeError("模型通道不可用")

    monkeypatch.setattr(BatchManager, "_solve_one", boom)

    job = manager.create_job(["题目一", "题目二"])
    asyncio.run(manager.run_job(job.batch_id))

    assert job.status == TaskStatus.FAILED          # 不再谎报 success
    assert all(t.status == TaskStatus.FAILED for t in job.tasks.values())


def test_batch_store_init_failure_does_not_hang_job(isolated, monkeypatch) -> None:
    """向量库初始化抛异常时任务必须落到 failed，否则 RUNNING 会永久占用并发名额。"""
    from app.services.batch import BatchManager, TaskStatus
    from app.services import retriever as retriever_mod

    def bad_store():
        raise RuntimeError("向量库不可用")

    monkeypatch.setattr(retriever_mod, "get_default_store", bad_store)

    manager = BatchManager()
    job = manager.create_job(["题目一"])
    asyncio.run(manager.run_job(job.batch_id))

    assert job.status == TaskStatus.FAILED
    assert manager.running_count() == 0


def test_batch_solution_carries_step_check(isolated, monkeypatch) -> None:
    """批量结果与单题口径一致：携带 step_check，供历史记录与导出展示。"""
    from app.services import batch as batch_mod
    from app.services.batch import BatchManager

    manager = BatchManager()
    manager._store = object()

    def fake_retrieve(question, store=None, scope="textbook"):
        return {"items": [], "context": "【参考资料 1】\n来源：教材\n内容：3 = 3\n",
                "source_map": {"来源1": {"chunk_id": "c1", "source_file": "教材.pdf",
                                        "chapter": "第一章", "section": "1.1",
                                        "page_number": 1, "text_snippet": "3 = 3",
                                        "relevance": 0.9, "low_relevance": False}},
                "fallback": False, "message": ""}

    async def fake_stream(question, context):
        yield "## 解题步骤\n\n1. 由依据可知 3 = 3 [来源1]\n"

    saved: list[dict] = []
    monkeypatch.setattr(batch_mod.retriever, "retrieve_with_fallback", fake_retrieve)
    monkeypatch.setattr(batch_mod, "stream_analysis", fake_stream)
    monkeypatch.setattr(batch_mod.doc_store, "save_solution", lambda s: saved.append(s))

    solution_id, blocked = asyncio.run(manager._solve_one("计算 3 的值是多少呢？"))

    assert solution_id and blocked is None
    assert saved[0]["step_check"]["checked"] == 1
    assert saved[0]["step_check"]["ok"] is True
    assert saved[0]["mode"] in ("mock", "ollama", "cloud")


# ------------------------------------------------------------ 上传防坑

def test_upload_rejects_scanned_pdf_without_chunks(tmp_path, monkeypatch) -> None:
    """无文本层文档：返回 400 且不留下临时文件（原实现会入库 0 块并让修复后重传被 409 挡住）。"""
    from app.api import upload as upload_api

    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(upload_api, "get_settings", lambda: settings)
    monkeypatch.setattr("app.store.db.get_settings", lambda: settings)
    init_db()

    monkeypatch.setattr(upload_api.document_parser, "parse_document",
                        lambda path: [{"page_number": 1, "content": "   ", "char_count": 0}])

    response = client.post(
        "/api/upload/textbook",
        files={"file": ("扫描版.pdf", b"%PDF-1.4 fake-scanned", "application/pdf")},
    )

    assert response.status_code == 400
    assert "扫描版" in response.json()["detail"]
    assert list(settings.upload_dir.glob("*")) == []  # 临时文件已清理


# ------------------------------------------------------------ 评测报告健壮性

def test_eval_latest_survives_malformed_report(tmp_path, monkeypatch) -> None:
    from app.api import eval as eval_api

    class _TmpSettings(Settings):
        @property
        def reports_dir(self) -> Path:
            return tmp_path

    (tmp_path / "eval_broken.json").write_text("{不是合法 JSON", encoding="utf-8")
    monkeypatch.setattr(eval_api, "get_settings", lambda: _TmpSettings())

    payload = client.get("/api/eval/latest").json()

    assert payload["available"] is False
    assert payload["file"] == "eval_broken.json"
    assert "解析失败" in payload["error"]


# ------------------------------------------------------------ verifier 健壮性

def test_pi_coefficient_degenerate_input_does_not_crash() -> None:
    from app.services.verifier import compare_answers

    # 退化系数（"+.π"）不得抛异常；判定不了就返回 None/False
    assert compare_answers("+.π", "π") in (None, False)


# ------------------------------------------------------------ 向量库单例

def test_default_store_is_cached(monkeypatch) -> None:
    from app.services import retriever as retriever_mod

    created: list[int] = []

    class _FakeVectorStore:
        def __init__(self, settings=None, ephemeral=False):
            created.append(1)

    monkeypatch.setattr("app.services.vector_store.VectorStore", _FakeVectorStore)
    retriever_mod.reset_default_store()
    try:
        first = retriever_mod.get_default_store()
        second = retriever_mod.get_default_store()
        assert first is second
        assert len(created) == 1          # 只加载一次（避免每请求重载 ONNX 模型）

        retriever_mod.reset_default_store()
        third = retriever_mod.get_default_store()
        assert third is not first
        assert len(created) == 2
    finally:
        retriever_mod.reset_default_store()


# ------------------------------------------------------------ 参数快照（model 字段）

def test_solution_records_generation_model(isolated) -> None:
    """历史记录需可追溯"哪份解析用的什么模型"（参数可调之后尤其重要）。"""
    from app.store import documents as doc_store

    doc_store.save_solution({
        "solution_id": "s-model-1",
        "question_text": "计算 1+1 的值。",
        "status": "ok",
        "answer_text": "## 参考答案\n2",
        "sources": {},
        "mode": "cloud",
        "model": "deepseek/deepseek-v4.1-flash",
        "created_at": "2026-09-22T00:00:00",
    })

    loaded = doc_store.load_solution("s-model-1")
    assert loaded["model"] == "deepseek/deepseek-v4.1-flash"
    items = doc_store.list_solutions(limit=5)
    assert any(item.get("model") == "deepseek/deepseek-v4.1-flash" for item in items)


# ------------------------------------------------------------ 缺口摘要

def test_gaps_endpoint_aggregates_blocked(isolated) -> None:
    """拒答记录聚合成缺口摘要：类型计数 + 高频考点词（跨题过滤后）。"""
    from app.store import documents as doc_store

    blocked_questions = [
        ("计算数列的通项公式。", "no_evidence"),
        ("已知数列前 n 项和，求数列通项。", "no_evidence"),
        ("求", "incomplete"),
    ]
    for index, (question, blocked_type) in enumerate(blocked_questions):
        doc_store.save_solution({
            "solution_id": f"s-gap-{index}",
            "question_text": question,
            "status": "blocked",
            "blocked_type": blocked_type,
            "answer_text": "",
            "sources": {},
            "mode": "cloud",
            "created_at": f"2026-09-22T00:00:0{index}",
        })

    payload = client.get("/api/gaps").json()

    assert payload["total"] == 3
    assert payload["no_evidence"] == 2
    assert payload["incomplete"] == 1
    terms = [item["term"] for item in payload["top_terms"]]
    assert "数列" in terms                     # 跨题出现 ≥2 次，被识别为高频考点词
    assert all(len(term) >= 2 for term in terms)
    assert payload["hint"]
