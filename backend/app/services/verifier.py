"""4.4 解析质量校验：参考答案抽取 + 数值步骤验算（不调 LLM 的神经符号校验）。

设计原则：
1. 只验算"两侧都能求值为纯数值"的等式；含变量或未知符号的一律跳过，宁可不判也不误判；
2. 表达式求值走 AST 白名单递归求值，绝不使用 eval()，杜绝执行模型输出的任意字符串；
3. 校验结果只作为"人工复核提示"——数值一致不代表解析一定正确。
"""
import ast
import math
import re

ANSWER_HEADING = re.compile(r"^#{1,6}\s*参考答案\s*$", re.M)
NEXT_HEADING = re.compile(r"^#{1,6}\s+\S", re.M)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
CJK = re.compile(r"[一-鿿\u3000-\u303f\uff01-\uff65]")
PURE_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
OPERATORS = re.compile(r"\s*([+\-*/^(),])\s*")
# 一行里可能塞多个等式（"验证：4−1=3，7−4=3"）或 LaTeX 块，按中文标点切开逐个验算
EQUATION_SPLITTER = re.compile(r"[，,。；;、]|\$\$")
# 角度/圆周率存在歧义（弧度 vs 角度、π 归一化后易被抹掉），一律不判
AMBIGUOUS_SYMBOLS = ("°", "π")
# ASCII 星号只有在"数字 ** 数字/括号"这种明确乘方写法下才放行；
# 其余情形（Markdown 加粗 **要点**、裸乘法 3*4）语义不明，一律跳过
_EXPLICIT_POWER = re.compile(r"\d\s*\*\*\s*[\d(]")
# 成对的 Markdown 加粗标记：**要点** → 要点（配对出现时是明确强调，不是运算）
_EMPHASIS = re.compile(r"\*\*([^*]+)\*\*")
# 引用标注 [来源N]：是行文注释而不是表达式的一部分，求值前必须剥离
_CITATION_MARK = re.compile(r"\[来源\s*\d+\]")


def _strip_annotations(text: str) -> str:
    """剥离排版注释：成对加粗标记与引用标注（未配对的星号保持原样交由歧义检查）。"""
    previous = None
    while previous != text:
        previous = text
        text = _EMPHASIS.sub(r"\1", text)
    return _CITATION_MARK.sub("", text)


def _has_ambiguous_star(expr: str) -> bool:
    """判断（已剥离成对强调后的）ASCII 星号是否语义不明。"""
    if "*" not in expr:
        return False
    return _EXPLICIT_POWER.search(expr) is None
# 前导标签：列表符号 / "第N步：" / "所以、因此、得" 等中文连接词
LEAD_LABEL = re.compile(
    r"^\s*(?:[>*+]\s*|\-(?!\d)\s*|\d+[.、)]\s*"
    r"|第\s*[0-9一二三四五六七八九十]+\s*步\s*[：:、.)]?\s*"
    r"|步骤\s*[0-9]+\s*[：:、.)]?\s*"
    r"|(?:所以|因此|于是|故|得|即|由|解)\s*[：:，,]?\s*)")


def _strip_lead_label(text: str) -> str:
    """反复剥离前导标签，处理"因此得"这类连缀写法。"""
    current = text
    while True:
        stripped = LEAD_LABEL.sub("", current, count=1)
        if stripped == current:
            return current
        current = stripped

_SUPERSCRIPT = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SUBSCRIPT = "₀₁₂₃₄₅₆₇₈₉"
_MAX_EXPONENT = 100
_MAX_MAGNITUDE = 1e15

_FUNCS = {"sqrt": math.sqrt, "ln": math.log, "lg": math.log10, "abs": abs,
          "sin": math.sin, "cos": math.cos, "tan": math.tan}
_CONSTANTS = {"pi": math.pi, "e": math.e}
# 中文教材里不带底数的 log 既可指常用对数也可指自然对数，含义歧义 → 只认显式底数
_EXPLICIT_FUNCS = ("sqrt", "ln", "lg", "abs", "sin", "cos", "tan")


def _build_translation() -> dict[int, str]:
    table: dict[int, str] = {}
    for offset, base in ((0xFF10, "0"), (0xFF21, "A"), (0xFF41, "a")):
        width = 10 if base.isdigit() else 26
        for i in range(width):
            table[offset + i] = chr(ord(base) + i)
    table.update({
        0xFF08: "(", 0xFF09: ")", 0xFF0B: "+", 0xFF0C: ",", 0xFF0D: "-",
        0xFF0E: ".", 0xFF0F: "/", 0xFF1A: ":", 0xFF1B: ";", 0xFF1D: "=",
        0xFF1C: "<", 0xFF1E: ">", 0xFF01: "!", 0xFF0A: "*",
        0x00D7: "*", 0x22C5: "*", 0x00F7: "/", 0x2212: "-", 0x2013: "-",
        0x2014: "-", 0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',
        0x3010: "[", 0x3011: "]",
    })
    for i, ch in enumerate(_SUPERSCRIPT):
        table[ord(ch)] = f"**{i}"
    for i, ch in enumerate(_SUBSCRIPT):
        table[ord(ch)] = f"_{i}"
    return table


_TRANSLATION = _build_translation()
# 归一化过程中"认得"的非 ASCII 字符：翻译表内的上下标/全角符号，以及根号
_HANDLED_NON_ASCII = set(_TRANSLATION) | {ord("√")}


def _has_unhandled_symbol(expr: str) -> bool:
    """检测无法识别的符号（如修饰符 ˣ、上标加号 ⁺）。

    这类字符若被静默删除，"2ˣ" 会退化成 "2"，从而把 `2ˣ = 8` 误判为错误步骤，
    因此遇到不认识的符号一律放弃验算（跳过而非判错）。
    """
    for char in expr:
        if ord(char) <= 127 or ord(char) in _HANDLED_NON_ASCII or CJK.match(char):
            continue
        return True
    return False


# ---------------------------------------------------------------- 抽取

def extract_reference_answer(text: str | None) -> str | None:
    """从解析文本中抽取「## 参考答案」段落内容；找不到返回 None。"""
    if not text:
        return None
    match = ANSWER_HEADING.search(text)
    if not match:
        return None
    rest = text[match.end():]
    stop = NEXT_HEADING.search(rest)
    section = rest[:stop.start()] if stop else rest
    cleaned = section.strip()
    return cleaned or None


def _iter_equations(text: str, max_length: int = 120) -> list[str]:
    """逐行切出候选等式：按中文标点切成小段，每段独立判断是否可验算。"""
    found: list[str] = []
    for raw_line in text.splitlines():
        line = _strip_lead_label(raw_line.strip())
        if not line:
            continue
        for segment in EQUATION_SPLITTER.split(line):
            segment = segment.strip().strip("$").strip()
            if not segment or "=" not in segment or len(segment) > max_length:
                continue
            if any(mark in segment for mark in ("≈", "≠", "≤", "≥", "°", "π", "…")):
                continue
            found.append(segment)
    return found


# ---------------------------------------------------------------- 归一化

def normalize_expression(expr: str) -> str:
    """把中文/LaTeX/上下标混排的表达式归一为可求值的 ASCII 表达式。"""
    text = expr.translate(_TRANSLATION)
    text = text.replace("\\left", "").replace("\\right", "")
    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"((\1)/(\2))", text)
    text = re.sub(r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)", text)
    text = text.replace("\\cdot", "*").replace("\\times", "*").replace("\\", "")
    text = re.sub(r"\^\{([^{}]*)\}", r"**(\1)", text)
    text = re.sub(r"\^([0-9.]+|\([^()]*\))", r"**\1", text)  # 纯文本幂写法 2^5 → 2**5
    text = re.sub(r"_\{([^{}]*)\}", r"_\1", text)
    text = re.sub(r"√\s*\(?([0-9.]+)\)?", r"sqrt(\1)", text)
    # 冒号分号不是合法数学符号；换成空格而不是删除，避免"第1步：2"被粘成"12"
    text = re.sub(r"[:;]", " ", text)
    # 显式底数的对数：log_2 8 / log_2(8) / log_28 → log(8, 2)
    text = re.sub(r"log_([0-9.]+|\([^()]*\))\s*\(([^()]*)\)", r"log(\2, \1)", text)
    text = re.sub(r"log_([0-9.]+)\s*([0-9.]+)", r"log(\2, \1)", text)
    for func in _EXPLICIT_FUNCS:
        text = re.sub(rf"{func}\s*([0-9.]+)", rf"{func}(\1)", text)
    # 中文与全角符号替换成空格（不能直接删除，"第1步：2"会被粘成"12"导致误判）
    text = CJK.sub(" ", text)
    text = re.sub(r"[^\x00-\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = OPERATORS.sub(r"\1", text)  # 运算符/括号周围不留空格
    return text.strip(" ,:;.")


# ---------------------------------------------------------------- 求值

def _safe_eval(expr: str) -> float:
    """AST 白名单求值；任何不认识的节点/名字都抛 ValueError。"""
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as exc:
        raise ValueError(f"表达式无法解析：{expr}") from exc
    return _eval_node(node)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("仅支持数值常量")
        return float(node.value)
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("不支持的一元运算")
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left), _eval_node(node.right)
        return _apply_binop(node.op, left, right)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise ValueError("仅支持白名单函数调用")
        args = [_eval_node(arg) for arg in node.args]
        if node.func.id == "log":
            if len(args) != 2:
                raise ValueError("只验算显式底数的对数")
            return math.log(args[0], args[1])
        if node.func.id not in _FUNCS:
            raise ValueError(f"未授权函数：{node.func.id}")
        return float(_FUNCS[node.func.id](*args))
    if isinstance(node, ast.Name):
        if node.id not in _CONSTANTS:
            raise ValueError(f"未知符号：{node.id}")
        return float(_CONSTANTS[node.id])
    raise ValueError(f"不支持的表达式节点：{type(node).__name__}")


def _apply_binop(op: ast.AST, left: float, right: float) -> float:
    if isinstance(op, ast.Add):
        result = left + right
    elif isinstance(op, ast.Sub):
        result = left - right
    elif isinstance(op, ast.Mult):
        result = left * right
    elif isinstance(op, ast.Div):
        if right == 0:
            raise ValueError("除数为零")
        result = left / right
    elif isinstance(op, ast.Pow):
        if abs(right) > _MAX_EXPONENT:
            raise ValueError("指数过大")
        result = left ** right
    elif isinstance(op, ast.Mod):
        result = left % right
    else:
        raise ValueError("不支持的二元运算")
    if not math.isfinite(result) or abs(result) > _MAX_MAGNITUDE:
        raise ValueError("数值超出可控范围")
    return float(result)


# ---------------------------------------------------------------- 对外接口

def _try_numeric(expr: str) -> float | None:
    """归一化后尝试求值；含未知符号、数字被切断或无法解析时返回 None（跳过而非判错）。"""
    expr = _strip_annotations(expr)  # **要点** 与 [来源N] 是排版注释，先剥掉再判断
    if _has_unhandled_symbol(expr) or _has_ambiguous_star(expr):
        # 星号误判成乘方会把"依据要点 3**：log₃ 9=2"算成 3**log(9,3)=9 而假报错，
        # 因此只放行明确的 2**5 写法；全角乘号 × 已被翻译为 *，不受此限制。
        return None
    normalized = normalize_expression(_strip_lead_label(expr))
    if not normalized or re.search(r"\d\s+\d", normalized):
        return None  # "1 2+3" 这类数字被标签切断的形态不可靠，宁可跳过
    compact = re.sub(r"\s+", "", normalized)
    for name in IDENTIFIER.findall(compact):
        if name not in _FUNCS and name not in _CONSTANTS and name != "log":
            return None
    try:
        return _safe_eval(compact)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        return None


def check_equation(equation: str) -> bool | None:
    """校验等式（支持 `A = B = C` 链式）：仅当相邻两项都能求值为数值时才判定。

    含变量、角度/圆周率标记的等式返回 None（跳过而非判错）。
    """
    if "=" not in equation or any(mark in equation for mark in AMBIGUOUS_SYMBOLS):
        return None
    parts = equation.split("=")
    if len(parts) < 2:
        return None
    values = [_try_numeric(part) for part in parts]
    verdicts: list[bool] = []
    for left, right in zip(values, values[1:]):
        if left is None or right is None:
            continue
        tolerance = max(1e-6, 1e-6 * max(abs(left), abs(right)))
        verdicts.append(abs(left - right) <= tolerance)
    return all(verdicts) if verdicts else None


def verify_steps(text: str | None, max_checks: int = 40) -> dict:
    """验算解析中的数值步骤：返回可验算步数、通过步数与可疑步骤列表。"""
    result = {"checked": 0, "passed": 0, "skipped": 0, "failed": [], "ok": True}
    if not text:
        return result
    for equation in _iter_equations(text):
        if result["checked"] + result["skipped"] >= max_checks:
            break
        outcome = check_equation(equation)
        if outcome is None:
            result["skipped"] += 1
            continue
        result["checked"] += 1
        if outcome:
            result["passed"] += 1
        else:
            result["failed"].append(equation)
    result["failed"] = result["failed"][:5]
    result["ok"] = not result["failed"]
    return result


def _clean_answer(value: str) -> str:
    """答案归一化：全角转半角、去 Markdown 装饰、去空白与首尾标点。

    去掉空白的理由：数学表达式中空格只是书写习惯（"x<2 或 x>3" 与 "x<2或x>3" 等价），
    保留会造成无意义的比对失败；中文仍然保留，便于文字型答案比对。
    """
    text = str(value).translate(_TRANSLATION)
    text = text.replace("**", "").replace("*", "").replace("#", "")
    text = re.sub(r"\s+", "", text)
    return text.split("\n")[0].strip("。.,;:")


PI_TERM = re.compile(r"^([-+]?\d*\.?\d*)π$")


def _pi_coefficient(text: str) -> float | None:
    """把 "12π" / "-π" / "2.5π" 解析为 π 的系数，用于几何答案比对。"""
    match = PI_TERM.match(text)
    if not match:
        return None
    coefficient = match.group(1)
    if coefficient in ("", "+"):
        return 1.0
    if coefficient == "-":
        return -1.0
    return float(coefficient)


def _choice_letter(text: str) -> str | None:
    """识别"B"、"B."、"B（…）"这类选项字母答案。"""
    match = re.match(r"^([A-Da-d])(?![0-9A-Za-z])", text)
    return match.group(1).upper() if match else None


def _numbers(text: str) -> list[float]:
    return [float(token) for token in NUMBER.findall(text)]


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-6, 1e-6 * abs(right))


def compare_answers(generated: str | None, expected: str) -> bool | None:
    """比较解析给出的答案与标准答案：数值容差 → π 系数 → 选项字母 → 归一化字符串。

    返回 True（一致）/ False（不一致）/ None（无法判定，不计入统计）。
    """
    if not generated or not expected:
        return None
    gen_text, exp_text = _clean_answer(generated), _clean_answer(expected)
    if not gen_text or not exp_text:
        return None

    exp_choice = _choice_letter(exp_text)
    if exp_choice:
        return _choice_letter(gen_text) == exp_choice

    expected_pi = _pi_coefficient(exp_text)
    if expected_pi is not None:
        generated_pi = _pi_coefficient(gen_text)
        if generated_pi is not None:
            return _close(generated_pi, expected_pi)
        return False

    if PURE_NUMBER.match(exp_text):
        exp_value = float(exp_text)
        if PURE_NUMBER.match(gen_text):
            return _close(float(gen_text), exp_value)
        gen_numbers = _numbers(gen_text)
        if not gen_numbers:
            return None
        return any(_close(value, exp_value) for value in gen_numbers)

    return gen_text == exp_text
