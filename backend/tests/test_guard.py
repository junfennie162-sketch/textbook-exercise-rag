from app.services.citation import build_source_map, validate_and_fix_citations
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
