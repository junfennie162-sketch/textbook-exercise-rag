"""2.3 检索召回与上下文拼接（向量+BM25 混合检索、RRF 融合、轻量重排、降级策略）。"""
from app.core.config import get_settings
from app.services.citation import build_source_map


def retrieve_top_k(query: str, top_k: int | None = None,
                   store=None, scope: str | None = "textbook") -> list[dict]:
    """混合检索入口：scope='textbook' 时只在教材文档中检索，避免习题册原题干扰依据召回。

    流程：向量稠密召回 + BM25 稀疏召回（各 top_k×recall_multiplier）→ RRF 融合
    → 查询词覆盖度轻量重排 → 截取 top_k。每项保留向量路余弦 score 供阈值门控。
    """
    cfg = get_settings()
    vs = store
    if vs is None:
        from app.services.vector_store import VectorStore
        vs = VectorStore(cfg)
    where = {"doc_type": scope} if scope else None
    k = top_k or cfg.retrieval_top_k

    if cfg.retrieval_mode == "vector":
        return vs.query(query, top_k=k, where=where)

    from app.services.lexical_index import get_lexical_index
    from app.services.reranker import rerank, rrf_fuse

    recall_k = k * cfg.recall_multiplier
    vector_items = vs.query(query, top_k=recall_k, where=where)
    lexical_items = (get_lexical_index()
                     .search(query, top_k=recall_k, doc_type=scope))
    fused = rrf_fuse(vector_items, lexical_items, k=cfg.rrf_k)
    ranked = (rerank(query, fused, alpha=cfg.rerank_alpha)
              if cfg.rerank_enabled else fused)
    return ranked[:k]


def build_context(items: list[dict],
                  warn_threshold: float | None = None) -> tuple[str, dict[str, dict]]:
    """把检索结果拼成【参考资料 N】上下文，返回 (context_text, source_map)。

    warn_threshold 传入检索门控阈值，使引用预警与门控口径一致。
    """
    if not items:
        return "", {}
    source_map = build_source_map(items, warn_threshold)
    parts: list[str] = []
    for idx, item in enumerate(items, start=1):
        meta = item["metadata"]
        label = f"{meta.get('source_file', '未知来源')} {meta.get('chapter', '')} 第{meta.get('page_number')}页"
        parts.append(f"【参考资料 {idx}】\n来源：{label}\n内容：{item['text']}\n")
    return "\n".join(parts), source_map


def retrieve_with_fallback(query: str, store=None,
                           scope: str | None = "textbook") -> dict:
    """带降级的检索入口：空结果或相似度低于阈值时不放行。

    门控仍以向量路余弦相似度为锚：BM25 单独命中（余弦过低）不足以作为
    生成依据，保持"宁拒答不编造"的保守边界。
    """
    cfg = get_settings()
    items = retrieve_top_k(query, store=store, scope=scope)

    if not items:
        return {"items": [], "context": "", "source_map": {}, "fallback": True,
                "message": "未在知识库中找到相关依据，请谨慎参考生成结果。"}

    max_score = max(item["score"] for item in items)
    if max_score < cfg.similarity_threshold:
        return {"items": [], "context": "", "source_map": {}, "fallback": True,
                "message": f"找到的内容与问题相关性较低（最高相似度 {max_score:.2f}），建议人工复核。"}

    # 引用预警阈值与检索门控阈值共用同一配置，避免两处口径漂移
    context, source_map = build_context(items, cfg.similarity_threshold)
    return {"items": items, "context": context, "source_map": source_map,
            "fallback": False, "message": ""}
