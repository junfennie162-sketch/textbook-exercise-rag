"""缺口摘要：把"无教材依据 / 题目信息不全"的拒答聚合成待补资料清单。

边界处理的反哺闭环：拒答记录本身就是语料覆盖缺口的证据——按类型计数、
按高频考点词汇总，提示应补充哪些章节，避免"拒答了就完了"。

只读聚合（复用 solutions 表已有记录，不新增表、不调外部服务）。
"""
import re
from collections import Counter

from fastapi import APIRouter

from app.services.lexical_index import tokenize
from app.store import documents as doc_store

router = APIRouter(prefix="/api/gaps", tags=["缺口分析"])

MAX_SCAN = 200        # 最多扫描最近若干条记录
TOP_TERM_LIMIT = 8    # 返回的高频词条数
MIN_TERM_COUNT = 2    # 至少在 N 道题中出现才视为"高频考点"
# bigram 分词会把"求它/的第/已知"等虚词组合也切出来：含这些字的词条直接丢弃
_NOISE_CHARS = set("的了是求已知它其中个和与或")


def _collect_terms(questions: list[str]) -> list[dict]:
    """从题干里提取高频考点词：bigram 去噪 + 跨题频次过滤。"""
    counter: Counter = Counter()
    for question in questions:
        seen = set()
        for token in tokenize(question):
            if len(token) < 2 or token.isdigit():
                continue
            if any(ch in _NOISE_CHARS for ch in token):
                continue
            seen.add(token)          # 同一道题内只计一次，避免长题干刷频次
        counter.update(seen)
    return [
        {"term": term, "count": count}
        for term, count in counter.most_common(TOP_TERM_LIMIT)
        if count >= MIN_TERM_COUNT
    ]


@router.get("", summary="拒答缺口摘要（类型计数 + 高频考点词 + 补语料建议）")
async def gaps() -> dict:
    blocked = doc_store.list_solutions(limit=MAX_SCAN, status="blocked")
    by_type: Counter = Counter()
    for item in blocked:
        by_type[item.get("blocked_type") or "unknown"] += 1

    top_terms = _collect_terms([item.get("question_text") or "" for item in blocked])
    recent = [
        {"solution_id": item["solution_id"], "question_text": item["question_text"],
         "blocked_type": item.get("blocked_type") or "unknown"}
        for item in blocked[:5]
    ]
    total = len(blocked)
    if total == 0:
        hint = "暂无缺口：所有已提交题目都能在教材中找到依据。"
    else:
        hint = "这些题目缺少教材依据或信息不全：可按高频考点词补充对应章节语料后重跑评测。"
    return {
        "total": total,
        "no_evidence": by_type.get("no_evidence", 0),
        "incomplete": by_type.get("incomplete", 0),
        "other": total - by_type.get("no_evidence", 0) - by_type.get("incomplete", 0),
        "top_terms": top_terms,
        "recent": recent,
        "hint": hint,
    }
