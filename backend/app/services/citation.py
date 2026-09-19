"""3.3 引用来源标注与追溯（含引用相关度预警）。"""
import re

CITATION_PATTERN = re.compile(r"\[来源(\d+)\]")

# 引用相关度预警阈值：默认与检索门控阈值（SIMILARITY_THRESHOLD）一致——
# 低于门控分数说明"这条依据自身的接地强度不足"，值得人工复核；
# 调用方（检索层）会把配置里的门控阈值传进来，避免两处阈值各走各的。
CITATION_WARN_THRESHOLD = 0.60


def build_source_map(items: list[dict],
                     warn_threshold: float | None = None) -> dict[str, dict]:
    """检索结果 -> {"来源N": 来源详情} 映射表，附带相关度分数与低相关预警。

    warn_threshold 传 None 时使用默认阈值（绝不把 None 直接参与比较）。
    """
    threshold = CITATION_WARN_THRESHOLD if warn_threshold is None else warn_threshold
    source_map: dict[str, dict] = {}
    for idx, item in enumerate(items, start=1):
        meta = item["metadata"]
        score = round(float(item.get("score", 0.0)), 4)
        source_map[f"来源{idx}"] = {
            "chunk_id": item["chunk_id"],
            "source_file": meta.get("source_file", "未知来源"),
            "chapter": meta.get("chapter", "未识别章节"),
            "section": meta.get("section", "未识别小节"),
            "page_number": meta.get("page_number"),
            "text_snippet": item["text"][:100] + ("..." if len(item["text"]) > 100 else ""),
            "relevance": score,
            "low_relevance": score < threshold,
        }
    return source_map


def validate_and_fix_citations(text: str, source_map: dict[str, dict]) -> str:
    """移除指向不存在来源的标注，防止模型编造引用。"""
    valid_keys = set(source_map.keys())

    def replace_func(match: re.Match) -> str:
        key = f"来源{match.group(1)}"
        return match.group(0) if key in valid_keys else ""

    return CITATION_PATTERN.sub(replace_func, text)
