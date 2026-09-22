"""解析结果历史接口测试（/api/solutions 列表、详情、删除）。"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.store import documents as doc_store
from app.store.db import init_db

client = TestClient(app)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """把数据目录指向临时目录，避免接口测试污染真实数据库。"""
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("app.store.db.get_settings", lambda: settings)
    init_db()
    doc_store.save_solution({
        "solution_id": "s1",
        "question_text": "计算：log₂ 8 + log₃ 9。",
        "status": "ok",
        "blocked_type": None,
        "answer_text": "## 参考答案\n5",
        "step_check": {"checked": 2, "passed": 2, "skipped": 0, "failed": [], "ok": True},
        "mode": "mock",
        "created_at": "2026-09-18T10:00:00",
        "sources": {
            "来源1": {"chunk_id": "c1", "source_file": "样例教材.docx", "chapter": "第三章",
                      "page_number": 24, "relevance": 0.71, "low_relevance": False,
                      "text_snippet": "对数的定义…"},
        },
    })
    return settings


def test_list_solutions_returns_items(isolated_store) -> None:
    response = client.get("/api/solutions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["solution_id"] == "s1"
    assert item["sources_count"] == 1
    assert item["mode"] == "mock"


def test_list_solutions_supports_filters(isolated_store) -> None:
    assert client.get("/api/solutions", params={"keyword": "log₂"}).json()["total"] == 1
    assert client.get("/api/solutions", params={"keyword": "等差数列"}).json()["total"] == 0
    assert client.get("/api/solutions", params={"status": "ok"}).json()["total"] == 1
    assert client.get("/api/solutions", params={"status": "blocked"}).json()["total"] == 0


def test_solution_detail_and_404(isolated_store) -> None:
    detail = client.get("/api/solutions/s1")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["question_text"].startswith("计算")
    assert payload["sources"]["来源1"]["chapter"] == "第三章"
    assert payload["step_check"]["passed"] == 2
    assert client.get("/api/solutions/missing").status_code == 404


def test_list_total_counts_all_matching_rows(isolated_store) -> None:
    """total 为符合条件的总数，limit 只影响本页返回条数。"""
    for index in (2, 3, 4):
        doc_store.save_solution({
            "solution_id": f"s{index}", "question_text": f"题目 {index}",
            "status": "ok", "blocked_type": None, "answer_text": "答案",
            "step_check": None, "mode": "live",
            "created_at": f"2026-09-19T10:0{index}:00", "sources": {},
        })
    payload = client.get("/api/solutions", params={"limit": 2}).json()
    assert payload["total"] == 4            # s1 + s2 / s3 / s4
    assert payload["returned"] == 2
    assert len(payload["items"]) == 2
    assert client.get("/api/solutions", params={"status": "blocked"}).json()["total"] == 0


def test_delete_solution_and_404(isolated_store) -> None:
    removed = client.delete("/api/solutions/s1")
    assert removed.status_code == 200
    assert removed.json()["status"] == "success"
    assert client.get("/api/solutions/s1").status_code == 404
    assert client.delete("/api/solutions/s1").status_code == 404
