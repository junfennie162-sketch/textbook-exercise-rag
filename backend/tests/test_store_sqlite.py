"""SQLite 持久化层测试：文档与页段、解析结果与引用来源、批量任务记录。"""
import pytest

from app.core.config import Settings
from app.store import documents as doc_store
from app.store.db import connect, init_db


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把数据目录指向临时目录，避免污染真实数据库。"""
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("app.store.db.get_settings", lambda: settings)
    init_db()
    return settings


def _document(doc_id: str = "d1", **overrides) -> dict:
    base = {
        "doc_id": doc_id,
        "doc_type": "textbook",
        "original_name": "样例教材.docx",
        "stored_name": f"{doc_id}.docx",
        "units_count": 2,
        "chunks_count": 3,
        "status": "indexed",
        "created_at": "2026-09-18T10:00:00",
    }
    base.update(overrides)
    return base


def _solution(solution_id: str = "s1", **overrides) -> dict:
    base = {
        "solution_id": solution_id,
        "question_text": "计算：log₂ 8。",
        "status": "ok",
        "blocked_type": None,
        "answer_text": "## 参考答案\n3",
        "step_check": {"checked": 1, "passed": 1, "skipped": 0, "failed": [], "ok": True},
        "mode": "mock",
        "created_at": "2026-09-18T10:00:00",
        "sources": {
            "来源1": {
                "chunk_id": "c1", "source_file": "样例教材.docx", "chapter": "第三章",
                "page_number": 24, "relevance": 0.71, "low_relevance": False,
                "text_snippet": "对数的定义…",
            },
        },
    }
    base.update(overrides)
    return base


def test_document_roundtrip_and_upsert(store) -> None:
    doc_store.save_document(_document())
    assert doc_store.get_document("d1")["units_count"] == 2
    assert doc_store.get_document("missing") is None

    doc_store.save_document(_document(units_count=9, chunks_count=9))
    assert len(doc_store.load_documents()) == 1          # 同一 doc_id 覆盖而非新增
    assert doc_store.get_document("d1")["units_count"] == 9


def test_units_replaced_on_reupload(store) -> None:
    doc_store.save_document(_document())
    doc_store.save_units("d1", [
        {"unit_index": 0, "kind": "page", "content": "第一章 集合", "char_count": 6},
        {"unit_index": 1, "kind": "page", "content": "集合的定义", "char_count": 5},
    ])
    units = doc_store.load_units("d1")
    assert [unit["unit_index"] for unit in units] == [0, 1]
    assert units[0]["content"] == "第一章 集合"

    doc_store.save_units("d1", [{"unit_index": 0, "content": "新内容"}])
    assert len(doc_store.load_units("d1")) == 1
    assert doc_store.load_units("d1")[0]["char_count"] == 3   # 未传 char_count 时按长度补


def test_delete_document_cascades_units(store) -> None:
    doc_store.save_document(_document())
    doc_store.save_units("d1", [{"unit_index": 0, "content": "内容"}])
    removed = doc_store.delete_document("d1")
    assert removed and removed["doc_id"] == "d1"
    assert doc_store.get_document("d1") is None
    assert doc_store.load_units("d1") == []
    assert doc_store.delete_document("d1") is None


def test_solution_roundtrip_with_sources(store) -> None:
    doc_store.save_solution(_solution())
    loaded = doc_store.load_solution("s1")
    assert loaded["question_text"] == "计算：log₂ 8。"
    assert loaded["mode"] == "mock"
    assert loaded["step_check"]["passed"] == 1
    assert loaded["sources"]["来源1"]["chapter"] == "第三章"
    assert loaded["sources"]["来源1"]["low_relevance"] is False
    assert doc_store.load_solution("missing") is None


def test_solution_sources_replaced_on_resave(store) -> None:
    doc_store.save_solution(_solution())
    updated = _solution(sources={
        "来源1": {"chunk_id": "c9", "source_file": "新教材.docx", "chapter": "第五章",
                  "page_number": 39, "relevance": 0.55, "low_relevance": True,
                  "text_snippet": "数列…"},
    })
    doc_store.save_solution(updated)
    loaded = doc_store.load_solution("s1")
    assert list(loaded["sources"]) == ["来源1"]
    assert loaded["sources"]["来源1"]["chunk_id"] == "c9"
    assert loaded["sources"]["来源1"]["low_relevance"] is True
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM solution_sources").fetchone()[0]
    assert total == 1


def test_list_solutions_filters_and_order(store) -> None:
    doc_store.save_solution(_solution("s1", created_at="2026-09-18T10:00:00"))
    doc_store.save_solution(_solution("s2", question_text="已知等差数列求第 20 项",
                                      created_at="2026-09-18T11:00:00"))
    doc_store.save_solution(_solution("s3", status="blocked", blocked_type="no_evidence",
                                      answer_text="未在教材中找到相关依据",
                                      sources={}, created_at="2026-09-18T12:00:00"))

    everything = doc_store.list_solutions()
    assert [item["solution_id"] for item in everything] == ["s3", "s2", "s1"]   # 时间倒序
    assert everything[0]["sources_count"] == 0
    assert everything[1]["sources_count"] == 1

    assert [item["solution_id"] for item in doc_store.list_solutions(keyword="等差数列")] == ["s2"]
    assert [item["solution_id"] for item in doc_store.list_solutions(status="blocked")] == ["s3"]
    assert len(doc_store.list_solutions(limit=2)) == 2
    assert doc_store.list_solutions(keyword="不存在的关键词") == []


def test_delete_solution_cascades_sources(store) -> None:
    doc_store.save_solution(_solution())
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM solution_sources").fetchone()[0] == 1

    assert doc_store.delete_solution("s1") is True
    assert doc_store.load_solution("s1") is None
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM solution_sources").fetchone()[0] == 0
    assert doc_store.delete_solution("s1") is False


def test_batch_records_persisted(store) -> None:
    doc_store.save_batch_job("b1", 2, "2026-09-18T10:00:00")
    doc_store.save_batch_tasks("b1", [
        {"question_id": 0, "question": "计算 log₂ 8"},
        {"question_id": 1, "question": "已知等差数列"},
    ])

    doc_store.update_batch_task("b1", 0, "success", solution_id="s1")
    doc_store.update_batch_task("b1", 1, "failed", error="模型超时")
    doc_store.finish_batch_job("b1", "success", "2026-09-18T10:05:00")

    with connect() as conn:
        job = conn.execute("SELECT * FROM batch_jobs WHERE batch_id = 'b1'").fetchone()
        tasks = conn.execute(
            "SELECT * FROM batch_tasks WHERE batch_id = 'b1' ORDER BY question_id").fetchall()
    assert job["total"] == 2 and job["status"] == "success" and job["finished_at"]
    assert [task["status"] for task in tasks] == ["success", "failed"]
    assert tasks[0]["solution_id"] == "s1"
    assert tasks[1]["error"] == "模型超时"
