"""2.3 检索召回与上下文拼接（向量+BM25 混合检索、RRF 融合、轻量重排、降级策略）。"""
from app.core.config import get_settings
from app.services.citation import build_source_map

# 进程级单例：向量库 + 嵌入模型只初始化一次。
# 每次请求重建 VectorStore 会重复加载 ONNX 模型（秒级开销并阻塞事件循环），
# 批量管线早已缓存同一个 store，这里保持两条路径口径一致。
_default_store = None


def get_default_store():
    """懒加载默认向量库（进程级单例）；测试可用 reset_default_store() 清理。"""
    global _default_store
    if _default_store is None:
        from app.services.vector_store import VectorStore
        _default_store = VectorStore(get_settings())
    return _default_store


def reset_default_store() -> None:
    """清空默认向量库缓存（测试与配置变更后使用）。"""
    global _default_store
    _default_store = None


def retrieve_top_k(query: str, top_k: int | None = None,
                   store=None, scope: str | None = "textbook") -> list[dict]:
    """混合检索入口：scope='textbook' 时只在教材文档中检索，避免习题册原题干扰依据召回。

    流程：向量稠密召回 + BM25 稀疏召回（各 top_k×recall_multiplier）→ RRF 融合
    → 查询词覆盖度轻量重排 → 截取 top_k。每项保留向量路余弦 score 供阈值门控。
    """
    cfg = get_settings()
    vs = store if store is not None else get_default_store()
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


def _select_evidence(items: list[dict], relative_cut: float) -> list[dict]:
    """来源相对筛选：只保留与最佳来源分数接近的块，避免无关章节混入引用列表。

    只看向量路余弦（与门控、页面显示的相关度同一口径）：低于「最高分 × relative_cut」
    的块不再作为依据交给模型，也不会出现在引用来源里——检索总是会凑满 top_k，
    但凑数的低分块会让引用列表出现"对数题里引到数列章节"这类噪声。
    relative_cut ≤ 0 或 ≥ 1 表示关闭筛选；至少保留最佳来源。
    """
    if not items or relative_cut <= 0 or relative_cut >= 1:
        return items
    best = max(item.get("score", 0.0) for item in items)
    if best <= 0:
        return items
    floor = best * relative_cut
    kept = [item for item in items if item.get("score", 0.0) >= floor]
    return kept or items[:1]


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

    # 相对筛选：凑数的低分块不作为依据（避免"对数题引到数列章节"这类噪声），
    # 筛选后才拼上下文——模型看到的与引用列表显示的、以及标注校验用到的完全一致
    items = _select_evidence(items, cfg.evidence_relative_cut)

    # 引用预警阈值与检索门控阈值共用同一配置，避免两处口径漂移
    context, source_map = build_context(items, cfg.similarity_threshold)
    return {"items": items, "context": context, "source_map": source_map,
            "fallback": False, "message": ""}
