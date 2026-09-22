"""评测报告统计测试：答案正确率、步骤验算汇总、按题型/难度分维度。"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_eval  # noqa: E402


def _detail(**overrides) -> dict:
    base = {"id": "Q001", "type": "选择题", "difficulty": "基础", "has_reference": True,
            "completeness": 1.0, "citation_hit": True, "status": "ok", "num_sources": 3,
            "answer_correct": True, "extracted_answer": "B", "steps_checked": 2,
            "steps_passed": 2, "answer_preview": ""}
    base.update(overrides)
    return base


def test_report_summary_aggregates_new_metrics() -> None:
    details = [
        _detail(),
        _detail(id="Q002", completeness=0.5, answer_correct=False,
                steps_checked=3, steps_passed=1),
        _detail(id="Q011", has_reference=False, completeness=0.0,
                answer_correct=None, steps_checked=0, steps_passed=0),
    ]
    summary = run_eval.build_report(details)["summary"]
    assert summary["answer_accuracy"] == 0.5      # 2 题可判定，1 题正确
    assert summary["answer_judged"] == 2
    assert summary["steps_checked"] == 5
    assert summary["steps_passed"] == 3
    assert summary["step_pass_rate"] == 0.6
    assert summary["no_reference_refusal_rate"] == 1.0


def test_report_breakdown_groups_by_type_and_difficulty() -> None:
    details = [
        _detail(),
        _detail(id="Q009", type="选择题", difficulty="中等", completeness=0.5),
        _detail(id="Q010", type="计算题", difficulty="较难", completeness=1.0),
    ]
    breakdown = run_eval.build_report(details)["breakdown"]
    assert breakdown["by_type"]["选择题"]["count"] == 2
    assert breakdown["by_type"]["选择题"]["avg_completeness"] == 0.75
    assert breakdown["by_type"]["选择题"]["answer_accuracy"] == 1.0
    assert breakdown["by_difficulty"]["较难"]["count"] == 1
    assert breakdown["by_difficulty"]["基础"]["avg_completeness"] == 1.0


def test_report_metrics_are_null_when_not_judged() -> None:
    details = [_detail(answer_correct=None, steps_checked=0, steps_passed=0,
                       has_reference=True)]
    summary = run_eval.build_report(details)["summary"]
    assert summary["answer_accuracy"] is None
    assert summary["answer_judged"] == 0
    assert summary["step_pass_rate"] is None


def test_report_uses_null_for_empty_denominator() -> None:
    """评分集合里没有无依据题时，拒答率是"无法判定"而不是 0%。"""
    only_ref = [_detail(), _detail(id="Q002")]
    summary = run_eval.build_report(only_ref)["summary"]
    assert summary["no_reference_refusal_rate"] is None

    only_noref = [_detail(id="Q011", has_reference=False, answer_correct=None)]
    summary = run_eval.build_report(only_noref)["summary"]
    assert summary["avg_completeness"] is None
    assert summary["no_reference_refusal_rate"] == 1.0


# ------------------------------------------------------------ 引用命中口径

def test_citation_hit_requires_actual_labels() -> None:
    """有依据题：必须"答案里真的带 [来源N] 标注且标注合法"才算命中，检索到依据不算。"""
    item = {"has_reference": True}
    # 检索有依据、模型却一个标注都没写 → 未达标
    assert not run_eval.citation_hit(
        item, {"status": "ok", "answer": "解题过程略。", "sources": {"来源1": {}}})
    # 标注合法 → 命中
    assert run_eval.citation_hit(
        item, {"status": "ok", "answer": "由定义可知[来源1]。", "sources": {"来源1": {}}})
    # 标注指向来源表之外的编号（编造引用）→ 不算命中
    assert not run_eval.citation_hit(
        item, {"status": "ok", "answer": "由定义可知[来源2]。", "sources": {"来源1": {}}})
    # 区间/多编号标注同样识别
    assert run_eval.citation_hit(
        item, {"status": "ok", "answer": "见[来源1][来源2]。",
               "sources": {"来源1": {}, "来源2": {}}})
    # 拒答不算命中（有依据题本应作答）
    assert not run_eval.citation_hit(
        item, {"status": "blocked", "answer": "", "sources": {}})


def test_citation_hit_noref_requires_refusal() -> None:
    """无依据题：必须明确拒答，编造答案判不通过。"""
    item = {"has_reference": False}
    assert run_eval.citation_hit(item, {"status": "blocked", "answer": "", "sources": {}})
    assert run_eval.citation_hit(
        item, {"status": "ok", "answer": "依据不足，无法解析。", "sources": {}})
    assert not run_eval.citation_hit(
        item, {"status": "ok", "answer": "答案是 3。", "sources": {}})


# ------------------------------------------------------------ 失败题与空集合

def test_report_excludes_error_rows_from_metrics() -> None:
    """请求失败的题从指标分母剔除并单独计数：网络抖动不该拖低覆盖率指标。"""
    details = [
        _detail(),
        _detail(id="Q002", status="error", completeness=0.0, citation_hit=False,
                answer_correct=None, steps_checked=0, steps_passed=0),
    ]
    summary = run_eval.build_report(details)["summary"]
    assert summary["errors"] == 1
    assert summary["scored"] == 1
    assert summary["citation_hit_rate"] == 1.0
    assert summary["avg_completeness"] == 1.0


def test_report_empty_details_returns_null_rates() -> None:
    summary = run_eval.build_report([])["summary"]
    assert summary["citation_hit_rate"] is None
    assert summary["pass_rate"] is None


# ------------------------------------------------------------ 关键词匹配与去回声完整率

def test_keyword_hit_uses_boundaries() -> None:
    """纯数值关键词按边界匹配，杜绝 "3" 命中 "13"/"3.5" 这类虚高。"""
    norm = run_eval._normalize_text
    assert run_eval.keyword_hit("3", norm("答案是 3。"))
    assert not run_eval.keyword_hit("3", norm("a = 13"))
    assert not run_eval.keyword_hit("3", norm("约为 3.5"))
    assert run_eval.keyword_hit("1/2", norm("结果是 1/2。"))
    assert not run_eval.keyword_hit("1/2", norm("共 31/2 个"))
    assert run_eval.keyword_hit("对数", norm("对数的定义"))
    assert not run_eval.keyword_hit("had", norm("hadn't finished"))


def test_completeness_delta_excludes_question_echo() -> None:
    """题干里已出现的关键词被照抄不算覆盖：delta 口径只统计真正的补充知识点。"""
    item = {"id": "QX", "type": "计算题", "difficulty": "基础", "has_reference": True,
            "question": "求集合 A 与集合 B 的交集", "options": [],
            "expected_keywords": ["集合", "交集", "互异性"]}

    comp, delta = run_eval.completeness(item, "集合的交集运算需要用到元素的互异性")

    assert comp == 1.0            # 三个词都在答案里（传统口径）
    assert delta == 1.0           # 只剩「互异性」不是题干回声，且命中

    comp, delta = run_eval.completeness(item, "集合的交集是空集")
    assert comp == 2 / 3
    assert delta == 0.0           # 非回声词「互异性」未覆盖


def test_completeness_delta_none_when_all_echo() -> None:
    item = {"id": "QX", "type": "选择题", "difficulty": "基础", "has_reference": True,
            "question": "函数 f(x) 的单调区间是什么", "options": [],
            "expected_keywords": ["函数", "单调"]}
    _, delta = run_eval.completeness(item, "函数在定义域内单调")
    assert delta is None          # 全部是题干回声：不可判定，不虚报 0 或 100%


def test_judge_answer_prefers_aliases() -> None:
    """答案判定：主答案命中或任一等价写法出现即正确；有别名时未命中断定为错误。"""
    item = {"answer": "x<2或x>3", "answer_aliases": ["(-∞,2)∪(3,+∞)"]}
    assert run_eval.judge_answer(item, "x<2或x>3") is True
    assert run_eval.judge_answer(item, "所以解集是 (-∞,2)∪(3,+∞)") is True
    assert run_eval.judge_answer(item, "解集为 (2,3)") is False
    # 没有可判据（模型未给出答案）且有别名：计为错误而不是"无法判定"
    assert run_eval.judge_answer(item, None) is False


def test_judge_answer_without_aliases_keeps_undecidable() -> None:
    item = {"answer": "12"}
    assert run_eval.judge_answer(item, "无法判定") is None
    assert run_eval.judge_answer(item, "12") is True
