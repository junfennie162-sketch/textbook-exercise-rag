"""4.2 边界与异常处理：题目信息不全 / 无教材依据。"""


def is_incomplete_by_rule(question: str) -> bool:
    """规则快筛：命中任一条件即疑似信息不全。

    - 过短 / 以"求、计算"等动词截断收尾：题干被截掉的典型特征；
    - 引用上一题或题图（"上题/同上/该题/如图"）：系统看不到外部上下文与图片，
      按"宁拒答不编造"的边界处理，明确提示补齐条件。
    """
    text = question.strip()
    if len(text) < 8:
        return True
    if text.endswith(("……", "...", "求", "求解", "计算")):
        return True
    if any(k in text for k in ("上题", "同上", "该题", "如图", "见图", "下图")):
        return True
    return False


def has_valid_evidence(hits: list[dict], threshold: float) -> bool:
    """检索结果中最高相似度达到阈值才算有依据。"""
    if not hits:
        return False
    return max(h["score"] for h in hits) >= threshold


def build_error_response(error_type: str, detail: str) -> dict:
    """统一的结构化异常响应：说清楚、给原因、指方向。"""
    messages = {
        "incomplete": {
            "title": "题目信息似乎不完整",
            "tip": "请补充缺失的条件（如数值、前提）后重试。",
        },
        "no_evidence": {
            "title": "未在教材中找到相关依据",
            "tip": "本题考点可能超出当前教材范围，建议核对或补充教材章节。",
        },
    }
    info = messages[error_type]
    return {
        "status": "blocked",
        "error_type": error_type,
        "title": info["title"],
        "tip": info["tip"],
        "detail": detail,
        "can_retry": True,
    }
