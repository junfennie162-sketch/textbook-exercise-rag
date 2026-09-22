from app.services.citation import (build_source_map, ensure_source_section,
                                   validate_and_fix_citations)
from app.services.guard import build_error_response, is_incomplete_by_rule


def test_incomplete_rules() -> None:
    assert is_incomplete_by_rule("求")
    assert is_incomplete_by_rule("已知a=3，求……")
    assert is_incomplete_by_rule("用上题结论求解")
    assert not is_incomplete_by_rule("计算 log2 8 + log3 9 的值。")


def test_validate_citations_removes_invalid() -> None:
    items = [
        {"chunk_id": "c1", "text": "对数的定义", "metadata": {
            "source_file": "教材.pdf", "chapter": "第三章", "page_number": 5}},
    ]
    source_map = build_source_map(items)
    text = "根据[来源1]的定义，[来源9]不存在。"
    fixed = validate_and_fix_citations(text, source_map)
    assert "[来源1]" in fixed
    assert "[来源9]" not in fixed


def test_source_map_carries_relevance_warning() -> None:
    items = [
        {"chunk_id": "c1", "text": "高相关块", "metadata": {}, "score": 0.82},
        {"chunk_id": "c2", "text": "低相关块", "metadata": {}, "score": 0.55},
    ]
    source_map = build_source_map(items)
    assert source_map["来源1"]["relevance"] == 0.82
    assert source_map["来源1"]["low_relevance"] is False
    assert source_map["来源2"]["low_relevance"] is True


def test_error_response_shape() -> None:
    resp = build_error_response("incomplete", "缺少边长")
    assert resp["status"] == "blocked"
    assert resp["error_type"] == "incomplete"
    assert resp["tip"]


# ------------------------------------------------------------ 弱模型残留清理（本地 3B 常见）

def _two_sources():
    return build_source_map([
        {"chunk_id": "c1", "text": "数量积定义", "metadata": {
            "source_file": "教材.docx", "chapter": "第七章 平面向量", "page_number": 30}},
        {"chunk_id": "c2", "text": "垂直例子", "metadata": {
            "source_file": "教材.docx", "chapter": "第七章 平面向量", "page_number": 31}},
    ])


def test_validate_citations_cleans_stray_reference_junk() -> None:
    """回归：本地小模型抄了「参考资料」前缀且括号残缺，还把拒答套话抄进引用来源一栏。"""
    source_map = _two_sources()
    text = (
        "## 解题步骤\n\n1. 由数量积定义可知 a·b=0 时两向量垂直[来源1]。\n\n"
        "## 引用来源\n\n"
        "[来源1] 说明了两个非零向量的数量积的定义。\n"
        "[来源2] 提供了垂直的例子。\n"
        "[参考资料11未在教材中找到相关依据，无法解析。\n"
        "[参考资料2]未在教材中找到相关依据，无法解析。\n"
        "[参考资料31未在教材中找到相关依据，无法解析。\n"
        "[参考资料4]未在教材中找到相关依据，无法解析。\n"
    )

    fixed = validate_and_fix_citations(text, source_map)

    assert "参考资料" not in fixed                    # 残缺前缀被清掉
    assert "未在教材中找到相关依据" not in fixed        # 有引用时拒答套话整行移除
    assert "[来源1]" in fixed and "[来源2]" in fixed  # 合法引用保留
    assert "a·b=0 时两向量垂直[来源1]" in fixed


def test_refusal_answer_preserved_without_citations() -> None:
    """整体拒答（没有任何引用）时不得误删——拒答句是有效输出。"""
    text = "未在教材中找到相关依据，无法解析。"
    assert validate_and_fix_citations(text, {}) == text

    # 带上下文的部分拒答句也要保留
    partial = "第 2 问：现有教材依据不足以完整解答，缺少正数条件。"
    assert validate_and_fix_citations(partial, _two_sources()) == partial


def test_ensure_source_section_fills_missing_citations() -> None:
    """出处保底：模型一个 [来源N] 都没写时，用真实检索结果补「引用来源」栏目。"""
    source_map = _two_sources()

    filled = ensure_source_section("## 参考答案\n\n两向量垂直。", source_map)

    assert "## 引用来源" in filled
    assert "[来源1]" in filled and "[来源2]" in filled
    assert "第30页" in filled and "第七章 平面向量" in filled

    # 已有引用 → 不重复补；无来源（拒答场景）→ 保持原样
    with_citation = "## 引用来源\n\n[来源1] 定义。"
    assert ensure_source_section(with_citation, source_map) == with_citation
    assert ensure_source_section("原文", {}) == "原文"
