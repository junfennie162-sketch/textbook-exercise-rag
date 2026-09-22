"""检索策略消融实验（选做4）：切块粒度 × Top-k × 混合检索 × 重排 对检索质量的影响。

纯本地离线运行（只调嵌入模型，不调 LLM、不花钱、结果可复现），使用内存向量库，
不污染生产 chroma_db。对照维度：

  1. 切块粒度 chunk_size: 400 / 600 / 800
  2. 检索模式 retrieval_mode: vector（纯向量） vs hybrid（BM25+向量+RRF）
  3. 轻量重排 rerank_enabled: off / on（仅 hybrid 有意义）
  4. Top-k: 2 / 4 / 6

指标（检索层代理指标，不经过生成）：
  - kw_coverage@k  有依据题的期望关键词在 Top-k 检索文本中的覆盖率（越高越好）
  - hit@1          第 1 个检索块即包含关键词的题目比例
  - refusal_correct 无依据题被相似度门控正确拦截（max cos < 阈值）的比例
  - avg_max_cos    有依据题的平均最高余弦相似度

用法（后端目录下）：
    python ../scripts/run_ablation.py
    python ../scripts/run_ablation.py --chunk-sizes 400 600 800 --top-ks 2 4 6
"""
import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "backend"))

from app.core.config import Settings  # noqa: E402
from app.services import chunker, guard, retriever  # noqa: E402
from app.services.lexical_index import LexicalIndex  # noqa: E402
from app.services.vector_store import VectorStore  # noqa: E402

DATASET = BASE_DIR / "scripts" / "eval_dataset.json"
REPORTS = BASE_DIR / "backend" / "reports"


def load_corpus(settings: Settings) -> tuple[list[dict], list[str]]:
    """重建语料：优先读 SQLite（与运行中的知识库同源），旧版 JSON 作为兜底。

    历史版本把页段存在 documents.json / {doc_id}_units.json；知识库迁入 SQLite 后，
    继续读 JSON 会看不见新上传或已删除的文档，消融结论与真实语料脱节。
    """
    units: list[dict] = []
    names: list[str] = []

    try:
        from app.store import documents as doc_store
        registry = doc_store.load_documents()
    except Exception:
        registry = []

    if registry:
        for doc in registry:
            for unit in doc_store.load_units(doc["doc_id"]):
                units.append({**unit, "source_file": doc["original_name"],
                              "doc_type": doc["doc_type"]})
            if doc["doc_type"] == "textbook":
                names.append(doc["original_name"])
        if units:
            return units, names

    # 兜底：旧版 JSON 数据（没有 SQLite 数据库的旧环境仍可复现历史结论）
    docs_dir = settings.documents_dir
    registry_path = docs_dir / "documents.json"
    if not registry_path.exists():
        raise SystemExit(
            f"知识库为空：SQLite 无文档记录，且旧版语料 {registry_path} 不存在。\n"
            "请先上传样例（python scripts/upload_samples.py）或建库（python scripts/init_db.py --seed-samples）")

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for doc in registry:
        units_file = docs_dir / f"{doc['doc_id']}_units.json"
        if not units_file.exists():
            continue
        doc_units = json.loads(units_file.read_text(encoding="utf-8"))
        for unit in doc_units:
            units.append({**unit, "source_file": doc["original_name"],
                          "doc_type": doc["doc_type"]})
        if doc["doc_type"] == "textbook":
            names.append(doc["original_name"])
    if not units:
        raise SystemExit("语料为空：无法进行消融实验，请先上传教材样例。")
    return units, names


def build_stores(settings: Settings, units: list[dict], chunk_size: int
                 ) -> tuple[VectorStore, LexicalIndex]:
    """按指定粒度切块并构建内存向量库 + BM25 索引（互不污染生产数据）。"""
    chunks: list[dict] = []
    for seq, unit in enumerate(units):
        unit_chunks = chunker.build_chunks(
            [unit], doc_id=f"abl-{seq}", source_file=unit["source_file"],
            max_size=chunk_size, overlap=min(settings.chunk_overlap, chunk_size // 3))
        for chunk in unit_chunks:
            chunk["metadata"]["doc_type"] = unit["doc_type"]
        chunks.extend(unit_chunks)

    store = VectorStore(settings, ephemeral=True)
    store.add_chunks(chunks)

    index = LexicalIndex()
    index.add_chunks([c for c in chunks if c["metadata"]["doc_type"] == "textbook"])
    return store, index


def evaluate_combo(dataset: list[dict], settings: Settings, store: VectorStore,
                   index: LexicalIndex, mode: str, rerank_enabled: bool,
                   top_k: int) -> dict:
    """跑一组检索配置，返回四个指标（临时替换全局配置与词法索引）。"""
    combo_settings = Settings(_env_file=BASE_DIR / "backend" / ".env",
                              **{**settings.model_dump(),
                                 "retrieval_mode": mode,
                                 "rerank_enabled": rerank_enabled,
                                 "retrieval_top_k": top_k})

    import app.services.lexical_index as lex
    import app.services.retriever as rt
    original_settings = rt.get_settings
    original_index = lex.get_lexical_index
    rt.get_settings = lambda: combo_settings            # noqa: E731
    lex.get_lexical_index = lambda: index               # noqa: E731
    try:
        return score(dataset, store, combo_settings)
    finally:
        rt.get_settings = original_settings
        lex.get_lexical_index = original_index


def score(dataset: list[dict], store, settings: Settings) -> dict:
    ref, noref = [], []
    for item in dataset:
        question = "\n".join([item["question"], *item.get("options", [])])
        items = retriever.retrieve_top_k(question, store=store)
        max_cos = max((i["score"] for i in items), default=0.0)
        top_texts = [i["text"] for i in items]
        record = {"item": item, "question": question,
                  "top_texts": top_texts, "max_cos": max_cos}
        (ref if item["has_reference"] else noref).append(record)

    def kw_coverage(rec: dict) -> float:
        kws = rec["item"]["expected_keywords"]
        if not kws:
            return 0.0
        joined = "\n".join(rec["top_texts"])
        return sum(1 for kw in kws if kw in joined) / len(kws)

    ref_cov = [kw_coverage(r) for r in ref]
    hit1 = [any(kw in r["top_texts"][0] for kw in r["item"]["expected_keywords"])
            for r in ref if r["top_texts"]]
    # 拒答判断与线上两层防线一致：规则快筛 + 相似度门控
    refused = [guard.is_incomplete_by_rule(r["question"])
               or r["max_cos"] < settings.similarity_threshold
               for r in noref]
    return {
        "kw_coverage@k": round(sum(ref_cov) / len(ref_cov), 3) if ref_cov else 0.0,
        "hit@1": round(sum(hit1) / len(hit1), 3) if hit1 else 0.0,
        "refusal_correct": round(sum(refused) / len(refused), 3) if refused else 0.0,
        "avg_max_cos": round(sum(r["max_cos"] for r in ref) / len(ref), 3) if ref else 0.0,
    }


def audit_keyword_grounding(dataset: list[dict], units: list[dict]) -> dict:
    """核对评测关键词是否都"接地"（出现在教材原文中）。

    关键词落不到教材里，完整率就永远不可能达标——这是数据与语料的一致性检查，
    和检索策略无关，所以放在消融实验前先跑一遍。
    """
    corpus = "\n".join(u["content"] for u in units if u.get("doc_type") == "textbook")
    graded = [item for item in dataset if item["has_reference"]]
    missing: list[str] = []
    grounded = 0
    for item in graded:
        gaps = [kw for kw in item["expected_keywords"] if kw not in corpus]
        if gaps:
            missing.append(f"{item['id']}: {'、'.join(gaps)}")
        else:
            grounded += 1
    return {
        "graded_items": len(graded),
        "grounded_items": grounded,
        "grounding_rate": round(grounded / len(graded), 3) if graded else 0.0,
        "ungrounded": missing[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="检索策略消融实验")
    parser.add_argument("--chunk-sizes", type=int, nargs="+", default=[400, 600, 800])
    parser.add_argument("--top-ks", type=int, nargs="+", default=[2, 4, 6])
    args = parser.parse_args()

    # 显式加载 backend/.env，保证门控阈值等配置与线上服务一致
    settings = Settings(_env_file=BASE_DIR / "backend" / ".env")
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    units, names = load_corpus(settings)
    print(f"语料：{len(units)} 个解析单元，教材文档：{names}")
    print(f"评测集：{len(dataset)} 道题（有依据 {sum(1 for d in dataset if d['has_reference'])} 道）")

    grounding = audit_keyword_grounding(dataset, units)
    print(f"关键词接地检查：{grounding['grounded_items']}/{grounding['graded_items']} 题关键词全部命中教材"
          f"（接地率 {grounding['grounding_rate']:.1%}）")
    for gap in grounding["ungrounded"]:
        print(f"  [未接地] {gap}")

    rows: list[dict] = []
    for chunk_size in args.chunk_sizes:
        store, index = build_stores(settings, units, chunk_size)
        combos = [("vector", False), ("hybrid", False), ("hybrid", True)]
        for mode, rerank_enabled in combos:
            for top_k in args.top_ks:
                metrics = evaluate_combo(dataset, settings, store, index,
                                         mode, rerank_enabled, top_k)
                row = {"chunk_size": chunk_size, "mode": mode,
                       "rerank": "on" if rerank_enabled else "off",
                       "top_k": top_k, **metrics}
                rows.append(row)
                print(f"chunk={chunk_size:<4} mode={mode:<7} rerank={row['rerank']:<3} "
                      f"top_k={top_k}  kw_cov={metrics['kw_coverage@k']:.3f} "
                      f"hit@1={metrics['hit@1']:.3f} "
                      f"refusal={metrics['refusal_correct']:.3f}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"ablation_{time.strftime('%Y%m%d_%H%M%S')}.json"
    # 报告连同实验网格、语料/数据集规模与关键词接地检查一起落盘，
    # 便于评测面板「检索实验对比」直接展示并可复核
    report = {"summary": "切块粒度 × 检索模式 × 重排 × Top-k 消融实验（检索层代理指标）",
              "note": "kw_coverage@k/hit@1 越高越好；refusal_correct 为无依据题门控拦截率",
              "similarity_threshold": settings.similarity_threshold,
              "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
              "dataset_size": len(dataset),
              "corpus_units": len(units),
              "grounding": grounding,
              "grid": {"chunk_sizes": args.chunk_sizes, "top_ks": args.top_ks},
              "rows": rows}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已保存: {out}\n")

    best = max(rows, key=lambda r: (r["kw_coverage@k"], r["hit@1"]))
    print("结论建议（按 kw_coverage@k 优先，hit@1 次之）：")
    print(f"  最优配置 chunk_size={best['chunk_size']} mode={best['mode']} "
          f"rerank={best['rerank']} top_k={best['top_k']} "
          f"-> kw_cov={best['kw_coverage@k']} hit@1={best['hit@1']} "
          f"refusal={best['refusal_correct']}")


if __name__ == "__main__":
    main()
