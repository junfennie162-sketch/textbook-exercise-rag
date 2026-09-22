"""5.1/5.2 评测脚本：跑样例题，统计解析完整率、引用命中率、答案正确率与步骤验算。

用法（后端服务启动后）：
    python scripts/run_eval.py
    python scripts/run_eval.py --concurrency 3 --delay 0.5      # 并发评测（默认 3 路限流）
    python scripts/run_eval.py --base-url http://127.0.0.1:8001 --concurrency 1   # 串行
"""
import argparse
import asyncio
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "backend"))

from app.services import verifier  # noqa: E402
from app.services.citation import extract_citation_keys  # noqa: E402

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


def _normalize_text(text: str) -> str:
    """比较用归一化：NFKC（全角→半角、上标折叠）+ 去空白 + 小写。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).lower()


def keyword_hit(keyword: str, text_norm: str) -> bool:
    """关键词命中判定（text_norm 需先经 _normalize_text）。

    - 纯数值/分数关键词按数值边界匹配：避免 "3" 命中 "13"、"3.5"、"1/3"；
    - 含拉丁字母的关键词按字母数字边界匹配：避免 "had" 命中 "hadn't"；
    - 中文关键词按子串匹配。
    """
    kw = _normalize_text(keyword)
    if not kw:
        return False
    if re.fullmatch(r"[\d./]+", kw):
        return re.search(r"(?<![\d./])" + re.escape(kw) + r"(?![\d./])", text_norm) is not None
    if re.search(r"[0-9a-z]", kw):
        return re.search(r"(?<![0-9a-z])" + re.escape(kw) + r"(?![0-9a-z])", text_norm) is not None
    return kw in text_norm


def completeness(item: dict, answer: str) -> tuple[float, float | None]:
    """返回 (完整率, 去题干回声完整率)。

    完整率 = 命中期望关键词比例（与历史报告口径一致）。
    去题干回声完整率只统计"没有出现在题干里"的关键词：题干中已有的词被解析照抄
    并不构成知识点覆盖，原口径会因此虚高（本数据集 135 个关键词中约一半是题干回声）；
    无回声关键词时为 None（不可判定）。
    """
    keywords = item["expected_keywords"]
    if not keywords:
        return 0.0, None
    answer_norm = _normalize_text(answer)
    question_norm = _normalize_text(build_question_text(item))
    echo_keywords = {kw for kw in keywords if keyword_hit(kw, question_norm)}
    hits = sum(1 for kw in keywords if keyword_hit(kw, answer_norm))
    delta_keywords = [kw for kw in keywords if kw not in echo_keywords]
    delta = None
    if delta_keywords:
        delta_hits = sum(1 for kw in delta_keywords if keyword_hit(kw, answer_norm))
        delta = delta_hits / len(delta_keywords)
    return hits / len(keywords), delta


REFUSAL_MARKERS = ("未在教材中找到相关依据", "不足以完整解答", "依据不足", "无法解析")


def citation_hit(item: dict, result: dict) -> bool:
    """引用命中口径：看"答案里有没有可追溯的引用标注"，而不是"检索有没有返回依据"。

    - has_reference=true：解析成功且答案中带 [来源N] 标注（且标注都在来源表内）才算命中；
      只检索到依据、模型却没标注引用，属于未达标；
    - has_reference=false：必须明确拒答（blocked，或答案含拒答语），不得编造。
    """
    if item["has_reference"]:
        if result["status"] != "ok":
            return False
        keys = extract_citation_keys(result["answer"])
        return bool(keys) and keys <= set(result["sources"].keys())
    if result["status"] == "blocked":
        return True
    answer = result["answer"]
    refused = any(marker in answer for marker in REFUSAL_MARKERS)
    return refused


def backend_mode() -> str:
    """从本地 .env 读取生成模式（服务端探测失败时的兜底）。"""
    try:
        from app.core.config import Settings
        settings = Settings(_env_file=BASE_DIR / "backend" / ".env")
        return settings.llm_mode()
    except Exception:
        return "unknown"


async def fetch_backend_info(client: httpx.AsyncClient, base_url: str) -> dict:
    """预检 + 读取服务端真实生成模式（报告以服务端为准，避免本地 .env 与运行实例不一致）。"""
    response = await client.get(f"{base_url}/api/health", timeout=10)
    response.raise_for_status()
    return response.json()


def judge_answer(item: dict, generated: str | None) -> bool | None:
    """答案判定：主答案比对 + 等价写法（answer_aliases）包含判定。

    - 主答案判定命中 → 正确；
    - 任一别名出现 → 正确（别名由人工逐题核定，覆盖区间/分数/π 项/定理表述等写法差异）；
    - 主答案明确不一致，或有别名但全部未命中 → 错误；
    - 无判据（如模型未给出答案）→ None，不计入统计。
    """
    primary = verifier.compare_answers(generated, item.get("answer", ""))
    if primary is True:
        return True
    aliases = item.get("answer_aliases") or []
    if any(verifier.contains_answer(generated, alias) for alias in aliases):
        return True
    if primary is False or aliases:
        return False
    return None


def grade(item: dict, result: dict) -> dict:
    """把一次解析结果换算为评测明细（完整率 / 引用命中 / 答案正确率 / 步骤验算）。"""
    comp, delta_comp = completeness(item, result["answer"])
    hit = citation_hit(item, result)
    # 答案正确率只考核"教材中有依据"的题目（无依据题本应拒答，比对无意义）
    ref_answer = verifier.extract_reference_answer(result["answer"])
    answer_correct = judge_answer(item, ref_answer) if item["has_reference"] else None
    steps = verifier.verify_steps(result["answer"])
    return {
        "id": item["id"],
        "type": item["type"],
        "difficulty": item["difficulty"],
        "has_reference": item["has_reference"],
        "completeness": round(comp, 3),
        "delta_completeness": round(delta_comp, 3) if delta_comp is not None else None,
        "citation_hit": hit,
        "status": result["status"],
        "num_sources": len(result["sources"]),
        "answer_correct": answer_correct,
        "extracted_answer": (ref_answer or "")[:60],
        "steps_checked": steps["checked"],
        "steps_passed": steps["passed"],
        "answer_preview": result["answer"][:120],
    }


async def evaluate(base_url: str, delay: float, concurrency: int = 3,
                   limit: int | None = None) -> dict:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    if limit and limit > 0:
        dataset = dataset[:limit]

    details: dict[int, dict] = {}
    lock = asyncio.Lock()
    finished = 0
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        # 预检：后端不可达时立即退出，避免跑完一轮全是 error 还产出一份"看似有效"的报告
        try:
            health = await fetch_backend_info(client, base_url)
        except Exception as exc:
            print(f"[错误] 后端不可达（{base_url}）：{exc}")
            print("请先启动后端：cd backend && uvicorn app.main:app --port 8000")
            raise SystemExit(2)

        mode = health.get("llm_mode") or backend_mode()
        model = health.get("llm_model") or ""
        if mode == "mock":
            print("[注意] 后端当前为离线模板模式（LLM_MOCK=true）：解析由检索片段拼装，"
                  "不调用大模型；报告会标注 mode=mock。")
        else:
            channel = "本地 Ollama" if mode == "ollama" else "云端 API"
            print(f"[注意] 后端为 {channel} 模式（{model}），将对 {len(dataset)} 道题调用模型接口"
                  f"（并发 {max(1, concurrency)} 路）。")

        async def run_one(index: int, item: dict) -> None:
            nonlocal finished
            async with semaphore:                       # 并发限流，避免打满模型接口
                try:
                    result = await solve_one(client, base_url, item)
                except Exception as exc:                # 单题失败不影响整体评测
                    details[index] = {
                        "id": item["id"], "type": item["type"],
                        "difficulty": item["difficulty"],
                        "has_reference": item["has_reference"], "completeness": 0.0,
                        "delta_completeness": None,
                        "citation_hit": False, "status": "error", "num_sources": 0,
                        "answer_correct": None, "extracted_answer": "",
                        "steps_checked": 0, "steps_passed": 0, "answer_preview": "",
                        "error": str(exc)[:160],
                    }
                    async with lock:
                        finished += 1
                        print(f"[{finished}/{len(dataset)}] {item['id']} 请求失败：{str(exc)[:60]}")
                    return
                details[index] = grade(item, result)
                async with lock:
                    finished += 1
                    row = details[index]
                    verdict = ("—" if row["answer_correct"] is None
                               else ("✅" if row["answer_correct"] else "❌"))
                    print(f"[{finished}/{len(dataset)}] {item['id']} "
                          f"完整率: {row['completeness']:.2f} 引用命中: {row['citation_hit']} "
                          f"答案: {verdict} 步骤验算: {row['steps_passed']}/{row['steps_checked']}")
                if delay > 0:
                    await asyncio.sleep(delay)

        await asyncio.gather(*(run_one(i, item) for i, item in enumerate(dataset)))

    report = build_report([details[i] for i in sorted(details)])
    report["mode"] = mode
    report["model"] = model
    report["concurrency"] = max(1, concurrency)
    report["delay"] = delay
    if limit and limit > 0:
        report["limit"] = limit
    if mode == "mock":
        report["mode_note"] = ("离线模板模式：解析由检索到的教材片段拼装而成，未调用大模型；"
                               "指标衡量的是离线模板子系统，不代表真实模型生成效果。")
    elif mode == "ollama":
        report["mode_note"] = f"本地 Ollama 模式：由本地模型（{model}）生成，零 API 费用。"
    else:
        report["mode_note"] = (f"云端 API 模式：由云端模型（{model}）生成；"
                               "指标受模型能力、账户额度与网络状况影响。")
    print_summary(report)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已保存: {out}")
    errors = report["summary"].get("errors", 0)
    if errors:
        print(f"[警告] {errors} 道题请求失败（已从指标分母剔除）；请查清原因后重跑，"
              "否则本次报告只覆盖成功部分。")
        if errors * 2 > report["summary"]["total"]:
            print("[错误] 过半题目请求失败，本次评测结果不可用。")
            raise SystemExit(1)
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

    请求失败（status=error）的题目从各项比例的分母中剔除，单独以 errors 计数——
    否则一次网络抖动会把完整率、引用命中率一起拖低，把"没跑到"误报成"跑得差"。
    """
    errors = sum(1 for d in details if d.get("status") == "error")
    scored = [d for d in details if d.get("status") != "error"]
    ref_details = [d for d in scored if d["has_reference"]]
    noref_details = [d for d in scored if not d["has_reference"]]

    avg_comp = (round(sum(d["completeness"] for d in ref_details) / len(ref_details), 3)
                if ref_details else None)
    delta_values = [d["delta_completeness"] for d in ref_details
                    if d.get("delta_completeness") is not None]
    avg_delta = round(sum(delta_values) / len(delta_values), 3) if delta_values else None
    avg_hit = (sum(1 for d in scored if d["citation_hit"]) / len(scored)
               if scored else None)
    passed = (sum(
        1 for d in scored
        if d["citation_hit"] and (not d["has_reference"] or d["completeness"] >= 0.6)
    ) / len(scored)) if scored else None
    noref_refused = (round(sum(1 for d in noref_details if d["citation_hit"])
                           / len(noref_details), 3) if noref_details else None)

    judged = [d for d in ref_details if d.get("answer_correct") is not None]
    answer_accuracy = (round(sum(1 for d in judged if d["answer_correct"]) / len(judged), 3)
                       if judged else None)
    steps_checked = sum(d.get("steps_checked", 0) for d in scored)
    steps_passed = sum(d.get("steps_passed", 0) for d in scored)
    step_pass_rate = round(steps_passed / steps_checked, 3) if steps_checked else None

    return {
        "summary": {
            "total": len(details),
            "scored": len(scored),
            "errors": errors,
            "avg_completeness": avg_comp,
            "completeness_scope": "仅统计教材中有依据的题目",
            "avg_delta_completeness": avg_delta,
            "delta_completeness_scope": "去掉题干回声后的关键词覆盖率（题干里已有的词不算覆盖）",
            "citation_hit_rate": round(avg_hit, 3) if avg_hit is not None else None,
            "no_reference_refusal_rate": noref_refused,
            "answer_accuracy": answer_accuracy,
            "answer_judged": len(judged),
            "steps_checked": steps_checked,
            "steps_passed": steps_passed,
            "step_pass_rate": step_pass_rate,
            "pass_rate": round(passed, 3) if passed is not None else None,
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
          f"去题干回声完整率: {_pct(s.get('avg_delta_completeness'))}  "
          f"引用命中率: {_pct(s['citation_hit_rate'])}  "
          f"无依据拒答率: {_pct(s['no_reference_refusal_rate'])}  "
          f"通过率: {_pct(s['pass_rate'])}")
    print(f"答案正确率(有依据题 {s['answer_judged']} 题可判定): {_pct(s['answer_accuracy'])}  "
          f"步骤验算通过率: {_pct(s['step_pass_rate'])} "
          f"({s['steps_passed']}/{s['steps_checked']} 步)"
          + (f"  请求失败: {s['errors']} 题（未计入分母）" if s.get("errors") else ""))
    print("\n分维度统计：")
    for group_name, label in (("by_difficulty", "按难度"), ("by_type", "按题型")):
        for name, metrics in report["breakdown"][group_name].items():
            print(f"  {label} {name:<6} 题数 {metrics['count']:>2}  "
                  f"完整率 {_pct(metrics['avg_completeness']):>7}  "
                  f"引用命中 {_pct(metrics['citation_hit_rate']):>7}  "
                  f"答案正确率 {_pct(metrics['answer_accuracy'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="样例题评测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--delay", type=float, default=0.5, help="每题完成后的间隔秒数（限流保护）")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="并发路数（默认 3；真实模型调用时建议 2~3，接口限流时设为 1）")
    parser.add_argument("--limit", type=int, default=None,
                        help="只跑前 N 道（快速冒烟 / 限流环境先验证一小批）")
    args = parser.parse_args()
    asyncio.run(evaluate(args.base_url, args.delay, args.concurrency, args.limit))


if __name__ == "__main__":
    main()
