"""混合检索（BM25+向量、RRF 融合、轻量重排）单元与集成测试。"""
import pytest

from app.core.config import Settings
from app.services.lexical_index import LexicalIndex, tokenize
from app.services.reranker import rerank, rrf_fuse
from app.services import retriever


def _cfg(**overrides) -> Settings:
    base = {"retrieval_mode": "hybrid", "rerank_enabled": True,
            "retrieval_top_k": 2, "recall_multiplier": 3,
            "rrf_k": 60, "rerank_alpha": 0.6}
    base.update(overrides)
    return Settings(**base)


def test_tokenize_chinese_bigrams() -> None:
    assert tokenize("对数") == ["对数"]
    assert tokenize("等差数列") == ["等差", "差数", "数列"]


def test_tokenize_ascii_words_lowercased() -> None:
    assert tokenize("log2 8") == ["log2", "8"]
    assert "f" in tokenize("f(x) = x²")


def test_tokenize_empty_and_mixed() -> None:
    assert tokenize("") == []
    assert "求值" in tokenize("求值：( )" )


def test_bm25_finds_keyword_chunk() -> None:
    index = LexicalIndex()
    index.add_chunks([
        {"chunk_id": "c1", "text": "对数的定义：若 a^x = N，则 x = log_a N。",
         "metadata": {"doc_type": "textbook"}},
        {"chunk_id": "c2", "text": "等差数列的通项公式为 a_n = a_1 + (n-1)d。",
         "metadata": {"doc_type": "textbook"}},
    ])
    hits = index.search("对数的定义是什么", top_k=2, doc_type="textbook")
    assert hits[0]["chunk_id"] == "c1"
    assert hits[0]["bm25_score"] > 0


def test_bm25_filters_by_doc_type() -> None:
    index = LexicalIndex()
    index.add_chunks([
        {"chunk_id": "t1", "text": "三角函数的特殊值。", "metadata": {"doc_type": "textbook"}},
        {"chunk_id": "e1", "text": "三角函数的特殊值。", "metadata": {"doc_type": "exercise"}},
    ])
    hits = index.search("三角函数特殊值", top_k=5, doc_type="textbook")
    assert [h["chunk_id"] for h in hits] == ["t1"]


def test_lexical_index_removes_document() -> None:
    """删除文档后，其词条统计要一并回收，不能残留空引用。"""
    index = LexicalIndex()
    index.add_chunks([
        {"chunk_id": "t1", "text": "对数的定义", "metadata": {"doc_id": "A"}},
        {"chunk_id": "t2", "text": "对数的运算法则", "metadata": {"doc_id": "A"}},
        {"chunk_id": "t3", "text": "等差数列的通项公式", "metadata": {"doc_id": "B"}},
    ])
    assert index.remove_document("A") == 2
    assert index.remove_document("A") == 0        # 重复删除无副作用
    assert len(index) == 1
    assert index.search("对数的定义", top_k=5) == []
    assert [h["chunk_id"] for h in index.search("等差数列", top_k=5)] == ["t3"]


def test_rrf_prefers_dual_path_hits() -> None:
    vector_items = [
        {"chunk_id": "a", "text": "甲", "metadata": {}, "score": 0.5},
        {"chunk_id": "b", "text": "乙", "metadata": {}, "score": 0.4},
    ]
    lexical_items = [
        {"chunk_id": "b", "text": "乙", "metadata": {}, "bm25_score": 3.0},
        {"chunk_id": "c", "text": "丙", "metadata": {}, "bm25_score": 2.0},
    ]
    fused = rrf_fuse(vector_items, lexical_items, k=60)
    assert fused[0]["chunk_id"] == "b"          # 两路都命中 → 第一名
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]
    ids = {item["chunk_id"] for item in fused}
    assert ids == {"a", "b", "c"}
    # 向量路余弦分保留，供阈值门控
    by_id = {item["chunk_id"]: item for item in fused}
    assert by_id["a"]["score"] == 0.5
    assert by_id["c"]["score"] == 0.0


def test_rerank_boosts_term_coverage() -> None:
    items = [
        {"chunk_id": "x", "text": "集合的确定性是指元素是否属于集合是明确的。",
         "metadata": {}, "score": 0.55, "rrf_score": 0.02},
        {"chunk_id": "y", "text": "函数的单调性定义。", "metadata": {},
         "score": 0.62, "rrf_score": 0.018},
    ]
    ranked = rerank("集合的确定性", items, alpha=0.6)
    assert ranked[0]["chunk_id"] == "x"
    assert ranked[0]["coverage"] > ranked[1]["coverage"]
    assert ranked[0]["rerank_score"] > 0


class _FakeVectorStore:
    """模拟向量召回：固定返回预置排序，避免测试依赖真实嵌入模型。"""

    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def query(self, text: str, top_k: int = 4, where: dict | None = None) -> list[dict]:
        doc_type = (where or {}).get("doc_type")
        rows = [i for i in self._items
                if doc_type is None or i["metadata"].get("doc_type") == doc_type]
        return rows[:top_k]


@pytest.fixture
def textbook_corpus() -> list[dict]:
    return [
        {"chunk_id": "t1", "text": "对数的定义：若 a 的 x 次方等于 N，则 x 记作 log 以 a 为底 N 的对数。",
         "metadata": {"doc_type": "textbook", "chapter": "第三章", "page_number": 5}},
        {"chunk_id": "t2", "text": "对数的运算法则：log_a M + log_a N = log_a (MN)。",
         "metadata": {"doc_type": "textbook", "chapter": "第三章", "page_number": 6}},
        {"chunk_id": "t3", "text": "等差数列的通项公式 a_n = a_1 + (n-1)d，公差为 d。",
         "metadata": {"doc_type": "textbook", "chapter": "第二章", "page_number": 12}},
        {"chunk_id": "e1", "text": "习题：计算 log2 8 的值。",
         "metadata": {"doc_type": "exercise", "chapter": "习题册", "page_number": 1}},
    ]


def test_retrieve_hybrid_end_to_end(monkeypatch, textbook_corpus) -> None:
    # 向量路故意把弱相关块排在前面，验证 BM25+重排能纠偏
    fake_store = _FakeVectorStore([
        {**textbook_corpus[2], "score": 0.48},   # 等差数列（跑题但向量分高）
        {**textbook_corpus[1], "score": 0.46},   # 对数运算法则
        {**textbook_corpus[0], "score": 0.44},   # 对数定义
    ])
    index = LexicalIndex()
    index.add_chunks(textbook_corpus)
    monkeypatch.setattr("app.services.lexical_index.get_lexical_index", lambda: index)
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())

    items = retriever.retrieve_top_k("对数的定义", store=fake_store)
    assert len(items) <= 2
    assert items[0]["chunk_id"] in {"t1", "t2"}   # 词法+覆盖度把对数块顶上去
    assert all(i["metadata"]["doc_type"] == "textbook" for i in items)


def test_retrieve_vector_mode_bypass(monkeypatch, textbook_corpus) -> None:
    """retrieval_mode=vector 时退回纯向量单路（消融实验对照组）。"""
    fake_store = _FakeVectorStore([{**textbook_corpus[2], "score": 0.48}])
    monkeypatch.setattr(retriever, "get_settings",
                        lambda: _cfg(retrieval_mode="vector"))
    items = retriever.retrieve_top_k("对数的定义", store=fake_store)
    assert [i["chunk_id"] for i in items] == ["t3"]


def test_retrieve_rerank_disabled(monkeypatch, textbook_corpus) -> None:
    """rerank_enabled=false 时仍输出融合结果，且不携带重排字段。"""
    fake_store = _FakeVectorStore([{**textbook_corpus[0], "score": 0.8}])
    index = LexicalIndex()
    index.add_chunks(textbook_corpus)
    monkeypatch.setattr("app.services.lexical_index.get_lexical_index", lambda: index)
    monkeypatch.setattr(retriever, "get_settings",
                        lambda: _cfg(rerank_enabled=False, retrieval_top_k=4))
    items = retriever.retrieve_top_k("对数的定义", store=fake_store)
    assert items
    assert all("rerank_score" not in i for i in items)
    assert all("rrf_score" in i for i in items)


def test_build_context_uses_source_map(textbook_corpus) -> None:
    context, source_map = retriever.build_context(textbook_corpus[:2])
    assert "【参考资料 1】" in context
    assert "【参考资料 2】" in context
    assert source_map["来源1"]["chunk_id"] == "t1"
    assert source_map["来源2"]["page_number"] == 6


def test_build_context_accepts_custom_warn_threshold(textbook_corpus) -> None:
    """引用预警阈值可覆盖；不传阈值时必须走默认值而不是把 None 拿去比较。"""
    items = [{"chunk_id": "t1", "text": "对数的定义",
              "metadata": {"source_file": "教材.pdf", "chapter": "第三章", "page_number": 5},
              "score": 0.75}]
    _, strict = retriever.build_context(items, 0.90)
    _, loose = retriever.build_context(items, 0.50)
    _, default = retriever.build_context(items)

    assert strict["来源1"]["low_relevance"] is True
    assert loose["来源1"]["low_relevance"] is False
    assert default["来源1"]["low_relevance"] is False   # 0.75 ≥ 默认阈值 0.60
