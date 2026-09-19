"""接口冒烟测试：不触发向量库初始化（fastembed 模型下载）的轻量路径。"""
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _parse_sse(text: str) -> list[dict]:
    events = []
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data:"):
            events.append(json.loads(frame[len("data:"):].strip()))
    return events


def test_health_endpoint_reports_backend_is_ready() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "UP"


def test_upload_rejects_wrong_format() -> None:
    response = client.post(
        "/api/upload/textbook",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 400


def test_documents_404_for_unknown_id() -> None:
    assert client.get("/api/documents/nonexistent/pages").status_code == 404


def test_sources_404_for_unknown_chunk(monkeypatch) -> None:
    # 隔离真实向量库（避免单元测试触发嵌入模型下载）
    from app.services import vector_store as vs_mod
    monkeypatch.setattr(vs_mod.VectorStore, "get", lambda self, chunk_id: None)
    assert client.get("/api/sources/nonexistent-chunk").status_code == 404


def test_documents_delete_404(monkeypatch) -> None:
    from app.store import documents as doc_store
    monkeypatch.setattr(doc_store, "get_document", lambda doc_id: None)
    assert client.delete("/api/documents/not-exist").status_code == 404


def test_documents_delete_cleans_indexes_and_registry(monkeypatch) -> None:
    """删除文档需同时清理向量块、词法索引与登记项。"""
    from app.services import lexical_index as lex_mod
    from app.services import vector_store as vs_mod
    from app.store import documents as doc_store

    calls = {"vector": [], "lexical": [], "registry": []}

    class FakeStore:
        def delete_document(self, doc_id):
            calls["vector"].append(doc_id)
            return 41

    class FakeIndex:
        def remove_document(self, doc_id):
            calls["lexical"].append(doc_id)
            return 41

    monkeypatch.setattr(doc_store, "get_document", lambda doc_id: {
        "doc_id": doc_id, "original_name": "样例教材.docx", "units_file": "", "stored_name": ""})
    monkeypatch.setattr(doc_store, "delete_document",
                        lambda doc_id: calls["registry"].append(doc_id) or {"doc_id": doc_id})
    monkeypatch.setattr(vs_mod, "VectorStore", FakeStore)
    monkeypatch.setattr(lex_mod, "get_lexical_index", lambda: FakeIndex())

    response = client.delete("/api/documents/d1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_chunks"] == 41
    assert "样例教材.docx" in payload["message"]
    assert calls == {"vector": ["d1"], "lexical": ["d1"], "registry": ["d1"]}


def test_solve_blocks_incomplete_question() -> None:
    response = client.post("/api/solve", json={"question_text": "求"})
    assert response.status_code == 200
    events = _parse_sse(response.text)
    types = [e["type"] for e in events]
    assert "blocked" in types
    blocked = next(e for e in events if e["type"] == "blocked")
    assert blocked["error_type"] == "incomplete"
    assert types[-1] == "done"


def test_solve_stream_reports_relevance_and_step_check(monkeypatch) -> None:
    """mock 模式下的 SSE 事件契约：来源含相关度预警，done 含步骤验算结果。"""
    from app.core.config import Settings
    from app.services import llm_service as llm_mod
    from app.services import retriever as retriever_mod
    from app.store import documents as doc_store

    source_map = {
        "来源1": {"chunk_id": "c1", "source_file": "教材.pdf", "chapter": "第三章",
                  "page_number": 5, "text_snippet": "对数的定义",
                  "relevance": 0.81, "low_relevance": False},
    }
    saved: list[dict] = []
    monkeypatch.setattr(retriever_mod, "retrieve_with_fallback", lambda *a, **k: {
        "items": [], "context": "【参考资料 1】\n来源：教材 第三章 第5页\n内容：对数的定义\n",
        "source_map": source_map, "fallback": False, "message": ""})
    monkeypatch.setattr(llm_mod, "get_settings", lambda: Settings(llm_mock=True))
    monkeypatch.setattr(doc_store, "save_solution", lambda solution: saved.append(solution))

    response = client.post("/api/solve",
                           json={"question_text": "计算 log2 8 + log3 9 的值。"})
    assert response.status_code == 200
    events = _parse_sse(response.text)

    assert events[0]["type"] == "sources"
    assert events[0]["sources"]["来源1"]["relevance"] == 0.81
    assert events[0]["sources"]["来源1"]["low_relevance"] is False

    done = events[-1]
    assert done["type"] == "done" and done["status"] == "ok"
    assert done["step_check"]["ok"] is True
    assert saved and saved[0]["step_check"]["checked"] == 0  # mock 文本无可验算等式
    assert saved[0]["sources"]["来源1"]["relevance"] == 0.81
