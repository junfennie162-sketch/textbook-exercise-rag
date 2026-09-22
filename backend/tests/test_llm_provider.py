"""LLM 双通道（云端 API / 本地 Ollama）单元测试：配置解析、端点解析与流式调用形状。

全部离线：不访问网络，OpenAI 客户端用假对象替换。
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.llm import create_llm_client, resolve_llm_endpoint
from app.main import app

client = TestClient(app)


# ------------------------------------------------------------ 配置与端点解析

def test_llm_mode_precedence() -> None:
    """模式口径：LLM_MOCK 优先于 LLM_PROVIDER，全项目共用这一个真源。"""
    assert Settings(_env_file=None, llm_provider="ollama").llm_mode() == "ollama"
    assert Settings(_env_file=None, llm_provider="cloud").llm_mode() == "cloud"
    # mock 兜底：即使配置了 ollama，LLM_MOCK=true 也必须是离线模板
    assert Settings(_env_file=None, llm_provider="ollama", llm_mock=True).llm_mode() == "mock"
    assert Settings(_env_file=None, llm_provider="cloud", llm_mock=True).llm_mode() == "mock"


def test_resolve_endpoint_switches_by_provider() -> None:
    ollama = Settings(_env_file=None, llm_provider="ollama",
                      ollama_base_url="http://localhost:11434/v1",
                      ollama_model="qwen2.5:3b", ollama_api_key="ollama")
    endpoint = resolve_llm_endpoint(ollama)
    assert (endpoint.provider, endpoint.model) == ("ollama", "qwen2.5:3b")
    assert endpoint.base_url == "http://localhost:11434/v1"

    cloud = Settings(_env_file=None, llm_provider="cloud",
                     llm_base_url="https://api.deepseek.com",
                     llm_model="deepseek-chat", llm_api_key="sk-test")
    endpoint = resolve_llm_endpoint(cloud)
    assert (endpoint.provider, endpoint.model) == ("cloud", "deepseek-chat")
    assert endpoint.base_url == "https://api.deepseek.com"


def test_create_llm_client_returns_openai_compatible_client() -> None:
    """两条通道都必须产出 OpenAI 兼容客户端（上层代码路径唯一）。"""
    ollama = Settings(_env_file=None, llm_provider="ollama")
    api = create_llm_client(ollama)
    assert isinstance(api, AsyncOpenAI)

    cloud = Settings(_env_file=None, llm_provider="cloud")
    api = create_llm_client(cloud)
    assert isinstance(api, AsyncOpenAI)


# ------------------------------------------------------------ 流式调用形状（假客户端）

class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content):
        # content=None 模拟部分兼容端点推送的空 choices 心跳块
        self.choices = [_Choice(content)] if content is not None else []


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def close(self):
        self.closed = True


class _FakeCompletions:
    def __init__(self, stream):
        self._stream = stream
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self._stream


class _FakeClient:
    def __init__(self, stream):
        self.chat = SimpleNamespace(completions=_FakeCompletions(stream))


def test_stream_analysis_builds_openai_messages(monkeypatch) -> None:
    """live 分支：system+user 双消息、温度与 max_tokens 透传、空 choices 心跳块被跳过。"""
    import asyncio

    from app.services import llm_service

    stream = _FakeStream([_Chunk(None), _Chunk("第一步"), _Chunk("第二步")])
    fake = _FakeClient(stream)
    monkeypatch.setattr(llm_service, "create_llm_client", lambda cfg: fake)
    monkeypatch.setattr(
        llm_service, "get_settings",
        lambda: Settings(_env_file=None, llm_provider="ollama",
                         ollama_model="qwen2.5:3b", llm_temperature=0.3,
                         llm_top_p=0.9, llm_max_tokens=2048,
                         custom_instruction="用表格输出"))

    async def collect():
        return [piece async for piece in llm_service.stream_analysis("题干", "上下文")]

    pieces = asyncio.run(collect())

    assert pieces == ["第一步", "第二步"]  # None 心跳块未产出文本
    kwargs = fake.chat.completions.kwargs
    assert kwargs["model"] == "qwen2.5:3b"
    assert kwargs["stream"] is True
    assert kwargs["max_tokens"] == 2048      # 来自配置（设置面板可调）
    assert kwargs["temperature"] == 0.3
    assert kwargs["top_p"] == 0.9
    roles = [message["role"] for message in kwargs["messages"]]
    assert roles == ["system", "user"]
    prompt = kwargs["messages"][1]["content"]
    assert "题干" in prompt
    assert "【补充要求】用表格输出" in prompt   # 附加指令只追加、不覆盖底线提示词
    assert stream.closed is True  # 提前结束也释放连接


# ------------------------------------------------------------ /api/llm/status

def _parse_sse(text: str) -> list[dict]:
    import json
    return [json.loads(line[5:].strip()) for line in text.splitlines()
            if line.startswith("data: ")]


def test_llm_status_mock_mode_never_probes_network(monkeypatch) -> None:
    from app.api import llm as llm_api

    monkeypatch.setattr(
        llm_api, "get_settings", lambda: Settings(_env_file=None, llm_mock=True))
    payload = client.get("/api/llm/status").json()
    assert payload == {
        "mode": "mock",
        "ok": True,
        "model": None,
        "message": "离线模板模式：不访问任何外部服务，无需探测",
        "models": [],
    }


class _FakeModelsPage:
    def __init__(self, data):
        self.data = data


class _FakeModelsResource:
    def __init__(self, data):
        self._data = data

    async def list(self):
        return _FakeModelsPage(self._data)


class _FakeStatusClient:
    def __init__(self, data):
        self.models = _FakeModelsResource(data)

    async def close(self):
        pass


def test_llm_status_handles_ollama_null_model_list(monkeypatch) -> None:
    """Ollama 在模型尚未装好时 /v1/models 返回 data:null，探测应按空列表处理而不是报错。"""
    from app.api import llm as llm_api

    monkeypatch.setattr(
        llm_api, "get_settings",
        lambda: Settings(_env_file=None, llm_provider="ollama"))
    monkeypatch.setattr(llm_api, "AsyncOpenAI", lambda **kwargs: _FakeStatusClient(None))

    payload = client.get("/api/llm/status").json()

    assert payload["ok"] is True
    assert payload["model_present"] is False
    assert payload["models"] == []
    assert "未见模型" in payload["message"]


def test_solve_stream_emits_error_event_on_llm_failure(monkeypatch) -> None:
    """模型调用失败（云端余额不足 / Ollama 未启动等）时：SSE 给出 error + done(error)，不静默断流、不落库。"""
    from app.api import solve as solve_api
    from app.services import retriever as retriever_mod
    from app.store import documents as doc_store

    async def boom(question, context):
        raise RuntimeError("RateLimitError: Error code 429 - 余额不足")
        yield  # pragma: no cover（保持异步生成器签名）

    saved: list[dict] = []
    monkeypatch.setattr(retriever_mod, "retrieve_with_fallback", lambda *a, **k: {
        "items": [], "context": "【参考资料 1】\n来源：教材\n内容：对数的定义\n",
        "source_map": {"来源1": {"chunk_id": "c1", "source_file": "教材.pdf",
                                "chapter": "第三章", "page_number": 5,
                                "text_snippet": "对数的定义",
                                "relevance": 0.81, "low_relevance": False}},
        "fallback": False, "message": ""})
    monkeypatch.setattr(solve_api, "stream_analysis", boom)
    monkeypatch.setattr(doc_store, "save_solution", lambda solution: saved.append(solution))

    response = client.post("/api/solve", json={"question_text": "计算 log2 8 的值。"})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    types = [e["type"] for e in events]
    assert "error" in types
    error_event = next(e for e in events if e["type"] == "error")
    assert "429" in error_event["message"]
    assert error_event["hint"]  # 给出排查方向
    assert types[-1] == "done"
    assert events[-1]["status"] == "error"
    assert saved == []  # 失败的解析不落库
