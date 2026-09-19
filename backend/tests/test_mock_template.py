"""离线模板生成测试：不调用大模型，从检索片段拼装五段式解析。"""
import asyncio

from app.core.config import Settings
from app.services import llm_service

CONTEXT = (
    "【参考资料 1】\n来源：教材.docx 第三章 指数函数与对数函数 第24页\n"
    "内容：对数的定义：一般地，如果aˣ=N（a>0，且a≠1），那么数x叫做以a为底N的对数，"
    "记作x=log_a N。例如log₂ 8=3，因为2³=8；log₃ 9=2。\n"
    "\n【参考资料 2】\n来源：教材.docx 第三章 指数函数与对数函数 第25页\n"
    "内容：对数运算法则：log_a(MN)=log_a M+log_a N；log_a(M/N)=log_a M-log_a N。\n"
)


def test_parse_context_recovers_structured_references() -> None:
    references = llm_service.parse_context(CONTEXT)
    assert len(references) == 2
    assert references[0]["label"] == "来源1"
    assert "第三章" in references[0]["source"]
    assert references[0]["content"].startswith("对数的定义")
    assert references[1]["label"] == "来源2"


def test_template_analysis_has_five_sections_and_citations() -> None:
    text = "".join(llm_service.build_template_analysis("计算 log₂ 8 + log₃ 9。", CONTEXT))
    assert "离线模板模式" in text
    for section in ("## 解题思路", "## 解题步骤", "## 易错点", "## 参考答案", "## 引用来源"):
        assert section in text, f"缺少段落 {section}"
    assert "[来源1]" in text
    assert "对数的定义" in text          # 步骤里引用了检索到的原句
    assert "log₂ 8 + log₃ 9" in text     # 回显题目


def test_template_analysis_ranks_by_overlap() -> None:
    """与题干词面重合度高的片段应排在前面。"""
    references = llm_service.parse_context(CONTEXT)
    ranked = llm_service._rank_sentences("对数运算法则是什么", references)
    assert ranked
    assert ranked[0][1] == "来源2"       # 第二段讲运算法则


def test_template_analysis_handles_empty_context() -> None:
    text = "".join(llm_service.build_template_analysis("某道题", ""))
    assert "## 参考答案" in text
    assert "（无引用来源）" in text


def test_template_output_passes_own_verification() -> None:
    """模板文本里的 Markdown 加粗不应被验算器误判成"算错的步骤"。"""
    from app.services import verifier

    text = "".join(llm_service.build_template_analysis("计算 log₂ 8 + log₃ 9。", CONTEXT))
    result = verifier.verify_steps(text)
    assert result["failed"] == []
    assert result["ok"] is True
    assert result["checked"] >= 1        # 教材原句里的等式应当被验算到


def test_mock_mode_never_creates_llm_client(monkeypatch) -> None:
    """离线模式的核心契约：绝不实例化大模型客户端。"""

    def explode(*args, **kwargs):  # pragma: no cover - 触发即失败
        raise AssertionError("离线模式不应创建大模型客户端")

    monkeypatch.setattr(llm_service, "create_llm_client", explode)
    monkeypatch.setattr(llm_service, "get_settings", lambda: Settings(llm_mock=True))

    async def collect() -> list[str]:
        return [piece async for piece in llm_service.stream_analysis("计算 log₂ 8", CONTEXT)]

    pieces = asyncio.run(collect())
    assert pieces and any("离线模板模式" in piece for piece in pieces)
