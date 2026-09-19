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
