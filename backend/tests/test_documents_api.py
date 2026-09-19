"""文档查看接口测试：页段摘要带章节与小节，并给出小节汇总（供按小节筛选）。"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.store import documents as doc_store
from app.store.db import init_db

client = TestClient(app)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("app.store.db.get_settings", lambda: settings)
    init_db()
    doc_store.save_document({
        "doc_id": "d1", "doc_type": "textbook", "original_name": "样例教材.docx",
        "stored_name": "d1.docx", "units_count": 4, "chunks_count": 4,
        "status": "indexed", "content_hash": "x" * 64, "created_at": "2026-09-19T10:00:00",
    })
    doc_store.save_units("d1", [
        {"unit_index": 0, "content": "第三章 指数函数与对数函数", "char_count": 14},
        {"unit_index": 1, "content": "3.3 对数与对数运算", "char_count": 10},
        {"unit_index": 2, "content": "对数的定义：如果 aˣ=N，那么 x=log_a N。", "char_count": 25},
        {"unit_index": 3, "content": "3.4 对数函数", "char_count": 8},
    ])
    return settings


def test_pages_carry_chapter_and_section(isolated) -> None:
    payload = client.get("/api/documents/d1/pages").json()
    assert payload["total"] == 4
    pages = payload["pages"]
    assert pages[0]["chapter"] == "第三章 指数函数与对数函数"
    assert pages[0]["section"] == "未识别小节"          # 尚未出现小节标题
    assert pages[1]["section"] == "3.3 对数与对数运算"
    assert pages[2]["section"] == "3.3 对数与对数运算"   # 未出现新小节时沿用
    assert pages[3]["section"] == "3.4 对数函数"


def test_pages_sections_summary(isolated) -> None:
    payload = client.get("/api/documents/d1/pages").json()
    summary = {item["section"]: item for item in payload["sections"]}
    assert summary["3.3 对数与对数运算"]["count"] == 2
    assert summary["3.3 对数与对数运算"]["first_page"] == 2
    assert summary["3.3 对数与对数运算"]["chapter"] == "第三章 指数函数与对数函数"
    assert summary["3.4 对数函数"]["count"] == 1


def test_pages_404_for_unknown_document(isolated) -> None:
    assert client.get("/api/documents/missing/pages").status_code == 404
