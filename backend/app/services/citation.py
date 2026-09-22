"""3.3 引用来源标注与追溯（含引用相关度预警）。"""
import re

# 兼容模型输出的多种引用写法：[来源1] / [来源 1] / [来源1、2] / [来源1-3] /
# 【来源1】/ [参考资料1]（上下文中的格式）。统一归一化为 [来源N] 形式。
CITATION_PATTERN = re.compile(r"[\[【](?:来源|参考资料)\s*([\d\s、,，\-–~]+?)[\]】]")

# 引用相关度预警阈值：默认与检索门控阈值（SIMILARITY_THRESHOLD）一致——
# 低于门控分数说明"这条依据自身的接地强度不足"，值得人工复核；
# 调用方（检索层）会把配置里的门控阈值传进来，避免两处阈值各走各的。
CITATION_WARN_THRESHOLD = 0.60

_MAX_RANGE_SPAN = 20  # 引用区间展开上限（防止 [来源1-9999] 制造超长标注）


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


def _expand_labels(group: str) -> list[str]:
    """把 "1、2" / "1-3" / "1 2" 展开为序号列表。"""
    labels: list[str] = []
    for part in re.split(r"[、,，]", group):
        part = part.strip()
        if not part:
            continue
        span = re.fullmatch(r"(\d+)\s*[-–~]\s*(\d+)", part)
        if span:
            start, end = int(span.group(1)), int(span.group(2))
            if 0 < start <= end and end - start <= _MAX_RANGE_SPAN:
                labels.extend(str(value) for value in range(start, end + 1))
            continue
        if part.isdigit():
            labels.append(part)
    return labels


def extract_citation_keys(text: str) -> set[str]:
    """提取文本中出现的全部引用键（含区间展开），如 {"来源1", "来源2"}。

    评测脚本用它判断"答案里是否真的带引用标注"，而不是"检索是否返回了依据"。
    """
    keys: set[str] = set()
    for group in CITATION_PATTERN.findall(text or ""):
        keys.update(f"来源{label}" for label in _expand_labels(group))
    return keys


def validate_and_fix_citations(text: str, source_map: dict[str, dict]) -> str:
    """归一化并清理引用标注：只保留指向真实来源的编号，其余一律移除，防止编造引用。

    输出统一为可点击的 [来源N] 单编号形式（前端按此模式拆分渲染）；
    多编号/区间一律展开为连写的多个标注，如 [来源1][来源2]。

    另清理弱模型的两类残留（本地小模型常见）：
    - 残缺标记：抄上下文前缀且括号不闭合，如 "[参考资料11未在教材…"、"【来源3"；
    - 拒答套话：已有可追溯引用时，整行只有"未在教材中找到相关依据，无法解析"的行会被移除
      （模型把拒答模板抄进了解析；真正的部分拒答句带上下文，不受影响）。
    """
    valid_keys = set(source_map.keys())

    def replace_func(match: re.Match) -> str:
        labels = [label for label in _expand_labels(match.group(1))
                  if f"来源{label}" in valid_keys]
        return "".join(f"[来源{label}]" for label in labels)

    fixed = CITATION_PATTERN.sub(replace_func, text)
    fixed = _STRAY_CITATION.sub("", fixed)
    if extract_citation_keys(fixed):
        lines = ["" if _is_refusal_only_line(line) else line for line in fixed.split("\n")]
        fixed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return fixed


def ensure_source_section(text: str, source_map: dict[str, dict]) -> str:
    """出处保底：检索有依据、但模型一个 [来源N] 都没标注时，补一个「引用来源」栏目。

    目标是"每道题都有出处"——弱模型（如本地 3B）偶发漏标引用时，用**真实检索结果**
    补全可追溯信息（章节 · 小节 · 页码），不编造任何内容。
    """
    if not source_map or extract_citation_keys(text):
        return text
    lines: list[str] = []
    for key, detail in source_map.items():
        page = f"第{detail['page_number']}页" if detail.get("page_number") else None
        location = " · ".join(part for part in
                              (detail.get("chapter"), detail.get("section"), page) if part)
        lines.append(f"- [{key}] 《{detail.get('source_file', '未知来源')}》{location}")
    return text.rstrip() + "\n\n## 引用来源\n\n" + "\n".join(lines) + "\n"


# 残缺引用标记：抄了"参考资料/来源"前缀但右括号缺失（合法引用先经 CITATION_PATTERN 归一化，
# 这里的否定前瞻保证不会误删已闭合的 [来源N]）
_STRAY_CITATION = re.compile(r"[\[【]\s*(?:参考资料|来源)\s*\d+\s*(?![\]】])")

# 「整行只是无依据套话」的归一化集合
_REFUSAL_ONLY = {
    "未在教材中找到相关依据无法解析",
    "未在教材中找到相关依据",
    "依据不足无法解析",
    "无法解析",
}


def _is_refusal_only_line(line: str) -> bool:
    """整行只有"无依据 / 无法解析"套话时为 True（可带残留引用前缀）；含实质内容则 False。"""
    text = line.strip().lstrip("-•*#> ").strip()
    text = re.sub(r"^[\[【][^\]】]{0,16}[\]】]?", "", text).strip()  # 行首残留引用标记
    if not text:
        return False
    normalized = re.sub(r"[\s。.!！,，、：:；;]", "", text)
    return normalized in _REFUSAL_ONLY
