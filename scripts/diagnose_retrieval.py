"""检索门控诊断：逐题检查样例题的教材依据召回情况与阈值余量（离线，不调用大模型）。

用途：
- 「边界处理」交付物的证据工具：哪些题能召回依据、哪些被相似度门控拦下、余量多少；
- 语料或阈值调整前后的对比基线（改教材内容 / SIMILARITY_THRESHOLD 后重跑本脚本）；
- 只在教材范围内检索（与生成链路同一 scope），并统计检索到的上下文对期望关键词的覆盖。

用法：
    python scripts/diagnose_retrieval.py
    python scripts/diagnose_retrieval.py --ids Q041 Q012
    python scripts/diagnose_retrieval.py --json backend/reports/gate_diagnose.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
BACKEND = BASE_DIR / "backend"
ORIGINAL_CWD = Path.cwd()   # chdir 之前记住调用目录：--json 的相对路径按调用处解析

# 切到 backend 目录：Settings 的 env_file=".env" 相对 CWD，与后端服务保持同一套配置
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services import retriever  # noqa: E402

DATASET = BASE_DIR / "scripts" / "eval_dataset.json"


def build_question_text(item: dict) -> str:
    parts = [item["question"]]
    if item.get("options"):
        parts.extend(item["options"])
    return "\n".join(parts)


def keyword_coverage(keywords: list[str], text: str) -> tuple[int, int]:
    hits = sum(1 for kw in keywords if kw.lower() in text.lower())
    return hits, len(keywords)


def diagnose(limit_ids: set[str] | None = None) -> dict:
    settings = get_settings()
    threshold = settings.similarity_threshold
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    if limit_ids:
        dataset = [item for item in dataset if item["id"] in limit_ids]

    print(f"配置：top_k={settings.retrieval_top_k} 模式={settings.retrieval_mode} "
          f"重排={'开' if settings.rerank_enabled else '关'} 门控阈值={threshold}")
    print(f"题量：{len(dataset)}（教材范围检索）\n")

    store = retriever.get_default_store()
    rows: list[dict] = []
    for item in dataset:
        question = build_question_text(item)
        try:
            items = retriever.retrieve_top_k(question, store=store)
        except Exception as exc:  # 检索异常也如实记录，不让诊断脚本崩掉
            rows.append({"id": item["id"], "has_reference": item["has_reference"],
                         "status": "error", "error": str(exc)[:120]})
            print(f"{item['id']}  检索异常：{exc}")
            continue

        top = items[0] if items else None
        max_score = max((entry["score"] for entry in items), default=0.0)
        context = "\n".join(entry["text"] for entry in items)
        hits, total = keyword_coverage(item["expected_keywords"], context)
        rows.append({
            "id": item["id"],
            "type": item["type"],
            "difficulty": item["difficulty"],
            "has_reference": item["has_reference"],
            "status": "ok",
            "max_score": round(max_score, 4),
            "gate_pass": bool(items) and max_score >= threshold,
            "margin": round(max_score - threshold, 4),
            "top_source": (f"{top['metadata'].get('chapter', '?')} · "
                           f"{top['metadata'].get('section', '?')}") if top else "",
            "context_chars": len(context),
            "keyword_hits": hits,
            "keyword_total": total,
        })
        flag = "✅" if rows[-1]["gate_pass"] else "⛔"
        ref = "有依据" if item["has_reference"] else "无依据"
        print(f"{item['id']} {flag} [{ref}] score={max_score:.3f} "
              f"(余量 {max_score - threshold:+.3f}) 关键词覆盖 {hits}/{total} "
              f"{rows[-1]['top_source']}")

    # 汇总：有依据题应过闸、无依据题应被拦（4/4 拦截是预期行为）
    ref_rows = [r for r in rows if r["has_reference"] and r["status"] == "ok"]
    noref_rows = [r for r in rows if not r["has_reference"] and r["status"] == "ok"]
    ref_pass = [r for r in ref_rows if r["gate_pass"]]
    noref_blocked = [r for r in noref_rows if not r["gate_pass"]]
    errors = [r for r in rows if r["status"] == "error"]

    print("\n===== 汇总 =====")
    print(f"有依据题过闸：{len(ref_pass)}/{len(ref_rows)}")
    if len(ref_pass) < len(ref_rows):
        print("  未过闸（需要语料或检索侧排查）：")
        for row in ref_rows:
            if not row["gate_pass"]:
                print(f"    {row['id']}  score={row['max_score']:.3f}  [{row['top_source']}]")
    print(f"无依据题被拦：{len(noref_blocked)}/{len(noref_rows)}"
          + ("（全部拦截，符合预期）" if len(noref_blocked) == len(noref_rows) else "  ⚠️ 有漏放！"))
    if errors:
        print(f"检索异常：{len(errors)} 题")

    return {
        "threshold": threshold,
        "config": {"top_k": settings.retrieval_top_k,
                   "mode": settings.retrieval_mode,
                   "rerank": settings.rerank_enabled},
        "ref_total": len(ref_rows), "ref_pass": len(ref_pass),
        "noref_total": len(noref_rows), "noref_blocked": len(noref_blocked),
        "errors": len(errors),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="检索门控诊断（离线，不调用大模型）")
    parser.add_argument("--ids", nargs="*", default=None, help="只诊断指定题号，如 Q041 Q012")
    parser.add_argument("--json", default=None, help="把完整结果写入 JSON 文件")
    args = parser.parse_args()

    result = diagnose(set(args.ids) if args.ids else None)
    if args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = ORIGINAL_CWD / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
