"""5.1/5.2 评测脚本：跑 15 道样例题，统计解析完整率、引用命中率、答案正确率与步骤验算。

用法（后端服务启动后）：
    python scripts/run_eval.py
    python scripts/run_eval.py --base-url http://127.0.0.1:8000 --delay 1
    python scripts/run_eval.py --base-url http://127.0.0.1:8001
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "backend"))

from app.services import verifier  # noqa: E402

DATASET = BASE_DIR / "scripts" / "eval_dataset.json"
REPORTS = BASE_DIR / "backend" / "reports"  # 与 /api/eval/latest 读取路径一致


def build_question_text(item: dict) -> str:
    parts = [item["question"]]
    if item.get("options"):
        parts.extend(item["options"])
    return "\n".join(parts)


async def solve_one(client: httpx.AsyncClient, base_url: str, item: dict) -> dict:
    """调用 SSE 解析接口，收集完整解析文本与引用列表。"""
    payload = {"question_text": build_question_text(item)}
    answer_parts: list[str] = []
    sources: dict = {}
    status = "unknown"
    async with client.stream("POST", f"{base_url}/api/solve", json=payload) as resp:
        resp.raise_for_status()
        buffer = ""
        async for raw in resp.aiter_text():
            buffer += raw
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                line = frame.strip()
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:"):].strip())
                if event["type"] == "chunk":
                    answer_parts.append(event["content"])
                elif event["type"] == "sources":
                    sources = event["sources"]
                elif event["type"] == "done":
                    status = event["status"]
    return {
        "answer": "".join(answer_parts),
        "sources": sources,
        "status": status,
    }


def completeness(item: dict, answer: str) -> float:
    """单题完整率 = 命中期望关键词比例。"""
    keywords = item["expected_keywords"]
    hits = sum(1 for kw in keywords if kw.lower() in answer.lower())
    return hits / len(keywords) if keywords else 0.0


REFUSAL_MARKERS = ("未在教材中找到相关依据", "不足以完整解答", "依据不足", "无法解析")


def citation_hit(item: dict, result: dict) -> bool:
    """has_reference=true 应有引用；false 应为 blocked 或 LLM 明确拒答（不编造）。"""
    if item["has_reference"]:
        return result["status"] == "ok" and len(result["sources"]) > 0
    if result["status"] == "blocked":
        return True
    answer = result["answer"]
    refused = any(marker in answer for marker in REFUSAL_MARKERS)
    return refused


def backend_mode() -> str:
    """读取后端配置判断当前生成模式：mock（离线模板）或 live（真实大模型）。"""
    try:
        from app.core.config import Settings
        settings = Settings(_env_file=BASE_DIR / "backend" / ".env")
        return "mock" if settings.llm_mock else "live"
    except Exception:
        return "unknown"


async def evaluate(base_url: str, delay: float) -> dict:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    mode = backend_mode()
    if mode == "mock":
        print("[注意] 后端当前为离线模板模式（LLM_MOCK=true）：解析由检索片段拼装，"
              "不调用大模型；报告会标注 mode=mock。")
    elif mode == "live":
        print(f"[注意] 后端为真实大模型模式，将对 {len(dataset)} 道题逐一调用模型接口。")
    details: list[dict] = []
    async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
        for i, item in enumerate(dataset, start=1):
            result = await solve_one(client, base_url, item)
            comp = completeness(item, result["answer"])
            hit = citation_hit(item, result)
            # 答案正确率只考核"教材中有依据"的题目（无依据题本应拒答，比对无意义）
            ref_answer = verifier.extract_reference_answer(result["answer"])
            answer_correct = (verifier.compare_answers(ref_answer, item.get("answer", ""))
                              if item["has_reference"] else None)
            steps = verifier.verify_steps(result["answer"])
            details.append({
                "id": item["id"],
                "type": item["type"],
                "difficulty": item["difficulty"],
                "has_reference": item["has_reference"],
                "completeness": round(comp, 3),
                "citation_hit": hit,
                "status": result["status"],
                "num_sources": len(result["sources"]),
                "answer_correct": answer_correct,
                "extracted_answer": (ref_answer or "")[:60],
                "steps_checked": steps["checked"],
                "steps_passed": steps["passed"],
                "answer_preview": result["answer"][:120],
            })
            verdict = "—" if answer_correct is None else ("✅" if answer_correct else "❌")
            print(f"[{i}/{len(dataset)}] {item['id']} 完整率: {comp:.2f} 引用命中: {hit} "
                  f"答案: {verdict} 步骤验算: {steps['passed']}/{steps['checked']}")
            if delay > 0 and i < len(dataset):
                await asyncio.sleep(delay)

    report = build_report(details)
    report["mode"] = mode
    if mode == "mock":
        report["mode_note"] = ("离线模板模式：解析由检索到的教材片段拼装而成，未调用大模型；"
                               "指标衡量的是离线模板子系统，不代表真实模型生成效果。")
    print_summary(report)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已保存: {out}")
    return report


def group_metrics(details: list[dict], key: str) -> dict[str, dict]:
    """按题型/难度分组统计（选做2）：题数、完整率、引用命中率、答案正确率。"""
    groups: dict[str, dict] = {}
    for item in details:
        bucket = groups.setdefault(item[key], {
            "count": 0, "ref_count": 0, "completeness_sum": 0.0,
            "citation_hits": 0, "judged": 0, "correct": 0})
        bucket["count"] += 1
        bucket["citation_hits"] += 1 if item["citation_hit"] else 0
        if item["has_reference"]:
            bucket["ref_count"] += 1
            bucket["completeness_sum"] += item["completeness"]
        if item.get("answer_correct") is not None:
            bucket["judged"] += 1
            bucket["correct"] += 1 if item["answer_correct"] else 0

    for bucket in groups.values():
        ref_count, judged = bucket.pop("ref_count"), bucket.pop("judged")
        completeness_sum, correct = bucket.pop("completeness_sum"), bucket.pop("correct")
        hits = bucket.pop("citation_hits")
        bucket["avg_completeness"] = (round(completeness_sum / ref_count, 3)
                                      if ref_count else None)
        bucket["citation_hit_rate"] = round(hits / bucket["count"], 3)
        bucket["answer_accuracy"] = round(correct / judged, 3) if judged else None
    return groups


def build_report(details: list[dict]) -> dict:
    """分域统计：完整率只考核有依据题；无依据题只考核是否正确拒答。

    分母为空的指标返回 None（页面显示"—"）：例如评分集合里没有无依据题时，
    拒答率不是 0%，而是"无法判定"，否则会把"没有这类题"误读成"全部没拒答"。
    """
    ref_details = [d for d in details if d["has_reference"]]
    noref_details = [d for d in details if not d["has_reference"]]

    avg_comp = (round(sum(d["completeness"] for d in ref_details) / len(ref_details), 3)
                if ref_details else None)
    avg_hit = sum(1 for d in details if d["citation_hit"]) / len(details) if details else 0.0
    passed = sum(
        1 for d in details
        if d["citation_hit"] and (not d["has_reference"] or d["completeness"] >= 0.6)
    ) / len(details) if details else 0.0
    noref_refused = (round(sum(1 for d in noref_details if d["citation_hit"])
                           / len(noref_details), 3) if noref_details else None)

    judged = [d for d in ref_details if d.get("answer_correct") is not None]
    answer_accuracy = (round(sum(1 for d in judged if d["answer_correct"]) / len(judged), 3)
                       if judged else None)
    steps_checked = sum(d.get("steps_checked", 0) for d in details)
    steps_passed = sum(d.get("steps_passed", 0) for d in details)
    step_pass_rate = round(steps_passed / steps_checked, 3) if steps_checked else None

    return {
        "summary": {
            "total": len(details),
            "avg_completeness": avg_comp,
            "completeness_scope": "仅统计教材中有依据的题目",
            "citation_hit_rate": round(avg_hit, 3),
            "no_reference_refusal_rate": noref_refused,
            "answer_accuracy": answer_accuracy,
            "answer_judged": len(judged),
            "steps_checked": steps_checked,
            "steps_passed": steps_passed,
            "step_pass_rate": step_pass_rate,
            "pass_rate": round(passed, 3),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "breakdown": {
            "by_type": group_metrics(details, "type"),
            "by_difficulty": group_metrics(details, "difficulty"),
        },
        "details": details,
    }


def _pct(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "—"


def print_summary(report: dict) -> None:
    s = report["summary"]
    print(f"\n解析完整率(有依据题): {_pct(s['avg_completeness'])}  "
          f"引用命中率: {s['citation_hit_rate']:.2%}  "
          f"无依据拒答率: {_pct(s['no_reference_refusal_rate'])}  "
          f"通过率: {s['pass_rate']:.2%}")
    print(f"答案正确率(有依据题 {s['answer_judged']} 题可判定): {_pct(s['answer_accuracy'])}  "
          f"步骤验算通过率: {_pct(s['step_pass_rate'])} "
          f"({s['steps_passed']}/{s['steps_checked']} 步)")
    print("\n分维度统计：")
    for group_name, label in (("by_difficulty", "按难度"), ("by_type", "按题型")):
        for name, metrics in report["breakdown"][group_name].items():
            print(f"  {label} {name:<6} 题数 {metrics['count']:>2}  "
                  f"完整率 {_pct(metrics['avg_completeness']):>7}  "
                  f"引用命中 {metrics['citation_hit_rate']:.2%}  "
                  f"答案正确率 {_pct(metrics['answer_accuracy'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="15 道样例题评测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--delay", type=float, default=0.5, help="每题间隔秒数")
    args = parser.parse_args()
    asyncio.run(evaluate(args.base_url, args.delay))


if __name__ == "__main__":
    main()
