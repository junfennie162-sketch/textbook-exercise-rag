"""解析质量校验测试：答案抽取 / 数值步骤验算 / 答案比对 / 安全求值。"""
from app.services.verifier import (
    check_equation,
    compare_answers,
    extract_reference_answer,
    normalize_expression,
    verify_steps,
)


def test_extract_reference_answer_stops_at_next_heading() -> None:
    text = "## 解题思路\n思路\n\n## 参考答案\nB\n\n## 引用来源\n[来源1] 定义"
    assert extract_reference_answer(text) == "B"
    assert extract_reference_answer("没有答案段落") is None
    assert extract_reference_answer(None) is None


def test_check_equation_numeric_cases() -> None:
    assert check_equation("2**5 = 32") is True
    assert check_equation("3 + 4 = 8") is False
    assert check_equation("2 + 3 = 5") is True
    assert check_equation("sqrt(16) = 4") is True
    assert check_equation("sqrt(16) = 5") is False


def test_check_equation_skips_symbolic() -> None:
    assert check_equation("a_n = a_1 + (n-1)d") is None
    assert check_equation("S₅ = 242") is None


def test_check_equation_handles_chinese_math_notation() -> None:
    assert check_equation("2⁵ = 32") is True
    assert check_equation("log₂ 8 = 3") is True
    assert check_equation("log₂ 8 = 4") is False


def test_check_equation_strips_leading_label() -> None:
    assert check_equation("第1步：2 + 3 = 5") is True
    assert check_equation("所以 3 × 4 = 12") is True


def test_check_equation_supports_chained_equality() -> None:
    assert check_equation("q = 6/2 = 3") is True
    assert check_equation("2 + 8 = 10 = 11") is False
    assert check_equation("a = b = c") is None


def test_check_equation_skips_ambiguous_symbols() -> None:
    assert check_equation("sin 30° = 1/2") is None   # 角度 vs 弧度歧义
    assert check_equation("2π = 6.28") is None       # π 归一化后易被抹掉


def test_check_equation_keeps_negative_sign() -> None:
    """列表符号"-"不能吃掉负号，否则 -2 会退化成 2 而误报。"""
    assert check_equation("分母 1 - 3 = -2") is True
    assert check_equation("-2 = -2") is True
    assert check_equation("- 2 + 3 = 5") is True    # 作为列表项时仍可剥离


def test_check_equation_skips_unhandled_symbols() -> None:
    """未知符号若被静默删除会制造误报（2ˣ 退化成 2），必须跳过。"""
    assert check_equation("2ˣ = 8") is None
    assert check_equation("3ʸ = 9") is None
    assert check_equation("2¹⁺¹⁺¹ = 8") is None


def test_check_equation_skips_markdown_emphasis() -> None:
    """Markdown 加粗的星号不能被当成乘方/乘法（模板与模型输出里都很常见）。"""
    assert check_equation("依据要点 3**：log₃ 9=2") is None   # 未配对星号 → 跳过
    assert check_equation("3*4 = 12") is None                # 裸乘法语义不明 → 跳过
    assert check_equation("3 × 4 = 12") is True              # 全角乘号是明确乘法


def test_check_equation_strips_paired_emphasis() -> None:
    """成对的加粗标记是明确强调，剥掉后应当正常验算。"""
    assert check_equation("**要点**：log₃ 9 = 2") is True
    assert check_equation("**首项**：a₁ = 3 = 3") is True
    assert check_equation("**要点**：2 + 2 = 5") is False


def test_check_equation_strips_citation_marks() -> None:
    """[来源N] 是行文注释而非表达式的一部分，不能让它挡掉本该验算的等式。"""
    assert check_equation("**依据要点**：例如log₂ 8=3 [来源1]") is True
    assert check_equation("log₃ 9 = 2 [来源2]") is True
    assert check_equation("log₃ 9 = 4 [来源2]") is False


def test_check_equation_supports_caret_power() -> None:
    assert check_equation("2^5 = 32") is True
    assert check_equation("2^5 = 30") is False


def test_verify_steps_splits_multi_equation_line() -> None:
    text = "验证：4−1=3，7−4=3，10−7=3，所以 d = 3。"
    result = verify_steps(text)
    assert result["checked"] == 3
    assert result["passed"] == 3
    assert result["ok"] is True
    assert result["skipped"] == 1                    # "所以 d = 3" 含变量，跳过


def test_verify_steps_flags_wrong_arithmetic_in_line() -> None:
    result = verify_steps("第2步：18 ÷ 6 = 4，所以 q = 3")
    assert result["checked"] == 1
    assert result["failed"] == ["18 ÷ 6 = 4"]


def test_safe_eval_refuses_code_like_input() -> None:
    assert check_equation("__import__('os').system('echo pwned') = 0") is None
    assert check_equation("2**999 = 1") is None
    assert check_equation("open('x') = 0") is None


def test_verify_steps_reports_counts_and_failures() -> None:
    text = "## 解题步骤\n1. 2 + 3 = 5\n2. 5 × 2 = 11\n3. a_1 = 3\n"
    result = verify_steps(text)
    assert result["checked"] == 2
    assert result["passed"] == 1
    assert result["ok"] is False
    assert result["failed"] == ["5 × 2 = 11"]


def test_verify_steps_empty_input() -> None:
    assert verify_steps(None) == {
        "checked": 0, "passed": 0, "skipped": 0, "failed": [], "ok": True}


def test_compare_answers_numeric() -> None:
    assert compare_answers("58", "58") is True
    assert compare_answers("58.0", "58") is True
    assert compare_answers("57", "58") is False
    assert compare_answers("a₂₀ = 58（第 20 项）", "58") is True


def test_compare_answers_choice_letter() -> None:
    assert compare_answers("**B**", "B") is True
    assert compare_answers("B. 不超过 20 的非负整数", "B") is True
    assert compare_answers("C.", "B") is False


def test_compare_answers_text_and_undecidable() -> None:
    assert compare_answers("相等", "相等") is True
    assert compare_answers("", "58") is None
    assert compare_answers("无法判定", "12") is None
    assert compare_answers(None, "12") is None


def test_compare_answers_ignores_whitespace() -> None:
    """数学表达式的空格只是书写习惯，不应造成比对失败。"""
    assert compare_answers("x < 2 或 x > 3", "x<2或x>3") is True
    assert compare_answers("[-1/2, 2]", "[-1/2,2]") is True


def test_compare_answers_pi_coefficient() -> None:
    assert compare_answers("36π", "36π") is True
    assert compare_answers("12π", "12π") is True
    assert compare_answers("12π", "36π") is False
    assert compare_answers("π", "π") is True
    assert compare_answers("12", "12π") is False


def test_normalize_expression_fullwidth_and_superscript() -> None:
    assert normalize_expression("２＋３") == "2+3"
    assert normalize_expression("2³") == "2**3"
    assert normalize_expression("log₂ 8") == "log(8,2)"
