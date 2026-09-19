"""混合检索融合与重排：RRF 倒数排名融合 + 查询词覆盖度轻量重排。

不引入交叉编码器（bge-reranker 约 1GB），用“余弦相似度 + 关键词覆盖度”
线性加权完成精排：离线可跑、秒级延迟、结果可解释，适合教学场景。
"""
from app.services.lexical_index import tokenize


def rrf_fuse(vector_items: list[dict], lexical_items: list[dict],
             k: int = 60) -> list[dict]:
    """两路召回结果按 RRF 融合：score = Σ 1/(k + rank)。

    两路都命中的块得分最高；合并时保留向量路的余弦 score 供阈值门控使用。
    """
    merged: dict[str, dict] = {}
    for rank, item in enumerate(vector_items, start=1):
        entry = merged.setdefault(item["chunk_id"], {**item, "score": item.get("score", 0.0)})
        entry["rrf_score"] = entry.get("rrf_score", 0.0) + 1.0 / (k + rank)
    for rank, item in enumerate(lexical_items, start=1):
        if item["chunk_id"] not in merged:
            merged[item["chunk_id"]] = {**item, "score": 0.0}
            merged[item["chunk_id"]]["rrf_score"] = 0.0
        merged[item["chunk_id"]]["rrf_score"] += 1.0 / (k + rank)
    fused = sorted(merged.values(),
                   key=lambda item: (item["rrf_score"], item["chunk_id"]),
                   reverse=True)
    for item in fused:
        item["rrf_score"] = round(item["rrf_score"], 6)
    return fused


def rerank(query: str, items: list[dict], alpha: float = 0.6) -> list[dict]:
    """轻量精排：rerank_score = α×余弦相似度 + (1-α)×查询词覆盖度。"""
    if not items:
        return []
    query_terms = set(tokenize(query))
    for item in items:
        chunk_terms = set(tokenize(item.get("text", "")))
        coverage = (len(query_terms & chunk_terms) / len(query_terms)
                    if query_terms else 0.0)
        item["coverage"] = round(coverage, 4)
        item["rerank_score"] = round(alpha * item.get("score", 0.0)
                                     + (1 - alpha) * coverage, 4)
    return sorted(items, key=lambda item: (item["rerank_score"],
                                           item["rrf_score"]), reverse=True)
