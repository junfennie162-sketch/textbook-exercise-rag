"""5.3 离线复评：对已保存的解析结果复算质量指标（不调用 LLM，零成本可复现）。

用途：指标口径调整（如新增答案正确率、步骤验算）或需要复核历史结果时，直接对
数据库中的解析结果（solutions 表）重新打分，无需重新调用大模型。

输出报告命名为 `eval_regraded_*.json`，会被 `/api/eval/latest`（取修改时间最新的报告）
识别为最近一次评测，可在前端「评测」面板查看。

用法：
    python scripts/regrade_solutions.py             # 复评全部已存解析（同题取最新一次）
    python scripts/regrade_solutions.py --limit 10  # 只复评最近 10 份
"""
import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts"))
sys.path.insert(0, str(BASE_DIR / "backend"))

import run_eval  # noqa: E402
from app.services import verifier  # noqa: E402
from app.store import documents as doc_store  # noqa: E402

DATASET = BASE_DIR / "scripts" / "eval_dataset.json"
REPORTS = BASE_DIR / "backend" / "reports"


def load_dataset() -> dict[str, dict]:
    """题目全文 -> 数据集条目（与 run_eval 构造 question_text 的方式保持一致）。"""
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    return {run_eval.build_question_text(item): item for item in dataset}


def load_solutions(limit: int | None) -> list[dict]:
    """从数据库读取已存解析，同一题只保留最新一份（按创建时间升序处理）。"""
    summaries = doc_store.list_solutions(limit=500)
    latest: dict[str, str] = {}
    for item in sorted(summaries, key=lambda row: row["created_at"]):
        latest[item["question_text"]] = item["solution_id"]
    solutions = [solution for solution in
                 (doc_store.load_solution(sid) for sid in latest.values()) if solution]
    return solutions[-limit:] if limit else solutions


def regrade(solution: dict, item: dict) -> dict:
    """对单份解析复算：完整率 / 引用命中 / 答案正确率 / 步骤验算。"""
    answer = solution.get("answer_text", "")
    result = {"answer": answer, "sources": solution.get("sources") or {},
              "status": solution.get("status", "unknown")}
    ref_answer = verifier.extract_reference_answer(answer)
    steps = verifier.verify_steps(answer)
    return {
        "id": item["id"],
        "type": item["type"],
        "difficulty": item["difficulty"],
        "has_reference": item["has_reference"],
        "completeness": round(run_eval.completeness(item, answer), 3),
        "citation_hit": run_eval.citation_hit(item, result),
        "status": result["status"],
        "num_sources": len(result["sources"]),
        "answer_correct": (verifier.compare_answers(ref_answer, item.get("answer", ""))
                           if item["has_reference"] else None),
        "extracted_answer": (ref_answer or "")[:60],
        "steps_checked": steps["checked"],
        "steps_passed": steps["passed"],
        "answer_preview": answer[:120],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="离线复评已保存的解析结果")
    parser.add_argument("--limit", type=int, default=None, help="只复评最近 N 份解析")
    args = parser.parse_args()

    dataset = load_dataset()
    solutions = load_solutions(args.limit)

    details: list[dict] = []
    unmatched: list[str] = []
    for solution in solutions:
        item = dataset.get(solution.get("question_text", ""))
        if item is None:
            unmatched.append(solution.get("solution_id", "?"))
            continue
        details.append(regrade(solution, item))

    if not details:
        print("没有可复评的解析结果：请先运行 scripts/run_eval.py 生成解析。")
        return

    report = run_eval.build_report(details)
    report["mode"] = run_eval.backend_mode()
    if report["mode"] == "mock":
        report["mode_note"] = ("离线复评 + 离线模板模式：被复评的解析由检索片段拼装而成，"
                               "未调用大模型；指标衡量的是离线模板子系统。")
    report["source"] = {
        "type": "regrade",
        "note": "对已保存解析离线复算，未调用大模型",
        "solutions_total": len(solutions),
        "matched": len(details),
        "unmatched_ids": unmatched,
    }
    run_eval.print_summary(report)
    if unmatched:
        print(f"\n未匹配到数据集的解析 {len(unmatched)} 份：{', '.join(unmatched)}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"eval_regraded_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n复评报告已保存: {out}")
    print("（文件名以 eval_ 开头，前端「评测」面板会展示为最近一次评测）")


if __name__ == "__main__":
    main()
