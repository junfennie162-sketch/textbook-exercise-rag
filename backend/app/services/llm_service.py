"""3.2 单题解析生成：流式调用大模型；LLM_MOCK=true 时切换为离线模板生成。

离线模板模式（`LLM_MOCK=true`）不访问任何外部服务：把检索到的教材片段按与题干的
词面重合度排序，拼装成「思路 / 步骤 / 易错点 / 答案 / 引用」五段结构。
它产出的是**模板文本而非模型作答**，因此每份解析开头都会显式标注，报告也会打上 mode=mock。
"""
import asyncio
import re

from app.core.config import get_settings
from app.core.llm import create_llm_client
from app.prompts.solution_prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.services.lexical_index import tokenize

MOCK_NOTICE = "> 离线模板模式：本解析由检索到的教材片段拼装而成，未调用大模型。"

_SENTENCE_SPLIT = re.compile(r"[。；;!?！？]")
_MAX_SENTENCE_CHARS = 110


async def stream_analysis(question: str, context: str):
    """按提示词组装请求，逐块 yield 解析文本。"""
    cfg = get_settings()
    if cfg.llm_mock:
        for piece in build_template_analysis(question, context):
            await asyncio.sleep(0.02)  # 保留流式观感，便于前端逐段渲染
            yield piece
        return

    client = create_llm_client(cfg)
    async with client.messages.stream(
        model=cfg.llm_model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(question=question, context=context),
        }],
    ) as stream:
        async for text in stream.text_stream:
            if text:
                yield text


# ------------------------------------------------------------ 离线模板实现

def parse_context(context: str) -> list[dict]:
    """把【参考资料 N】拼接块还原为结构化片段（离线模板与测试共用）。"""
    references: list[dict] = []
    for block in context.split("【参考资料 ")[1:]:
        index, _, remainder = block.partition("】")
        source, _, body = remainder.partition("内容：")
        references.append({
            "label": f"来源{index.strip()}",
            "source": source.replace("来源：", "").strip(),
            "content": body.strip(),
        })
    return references


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if len(part.strip()) >= 10]


def _rank_sentences(question: str, references: list[dict],
                    limit: int = 6) -> list[tuple[str, str]]:
    """按与题干的词面重合度排序（离线启发式，非语义模型），返回 (句子, 来源标签)。"""
    query_terms = set(tokenize(question))
    scored: list[tuple[int, int, str, str]] = []
    for reference in references:
        for sentence in _split_sentences(reference["content"]):
            overlap = len(query_terms & set(tokenize(sentence)))
            scored.append((overlap, -len(sentence), sentence, reference["label"]))
    scored.sort(reverse=True)
    return [(sentence, label) for _, _, sentence, label in scored[:limit]]


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_SENTENCE_CHARS else f"{text[:_MAX_SENTENCE_CHARS]}…"


def _answer_candidate(ranked: list[tuple[str, str]]) -> tuple[str, str] | None:
    """从检索片段里挑一句含数值/等式的短句作为参考答案候选。"""
    candidates = [(sentence, label) for sentence, label in ranked
                  if "=" in sentence or re.search(r"\d", sentence)]
    return min(candidates, key=lambda pair: len(pair[0])) if candidates else None


def build_template_analysis(question: str, context: str) -> list[str]:
    """离线模板：五段结构 + 依据引用，不调用大模型。"""
    references = parse_context(context)
    ranked = _rank_sentences(question, references)
    answer = _answer_candidate(ranked)
    lead_label = ranked[0][1] if ranked else None

    lines = [f"{MOCK_NOTICE}\n\n"]

    lines.append("## 解题思路\n\n")
    lines.append(f"本题围绕「{question.strip()[:40]}」展开。")
    if lead_label:
        lines.append(f"教材依据中与题目关键词重合度最高的是 {lead_label} 的表述，"
                     f"先厘清其中的定义与公式，再按步骤代入推导。\n\n")
    else:
        lines.append("当前依据不足以定位到具体定义，请补充教材章节后重试。\n\n")

    lines.append("## 解题步骤\n\n")
    if ranked:
        for index, (sentence, label) in enumerate(ranked[:4], start=1):
            # 标签内不放数字：避免与依据句里的表达式粘连，影响步骤验算
            lines.append(f"{index}. **依据要点**：{_clip(sentence)} [{label}]\n")
    else:
        lines.append("1. 现有依据不足，无法拆解步骤。\n")
    lines.append("\n")

    lines.append("## 易错点\n\n")
    lines.append("- 忽略依据中的前提条件（如定义域、正数条件、公比不为零）直接套用结论。\n")
    lines.append("- 公式或符号抄写错误，建议逐步写出中间结果再代入计算。\n\n")

    lines.append("## 参考答案\n\n")
    if answer:
        sentence, label = answer
        lines.append(f"{_clip(sentence)} [{label}]\n\n")
    else:
        lines.append("（离线模板未能从依据中提取出结论句，请参考上一步骤中的依据要点。）\n\n")

    lines.append("## 引用来源\n\n")
    if references:
        for reference in references:
            summary = _clip(_split_sentences(reference["content"])[0]) \
                if _split_sentences(reference["content"]) else "（无摘要）"
            lines.append(f"- [{reference['label']}] {reference['source']}：{summary}\n")
    else:
        lines.append("- （无引用来源）\n")

    return lines
