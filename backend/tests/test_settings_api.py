"""模型与参数设置系统测试：规格下发 / 白名单截断 / Key 掩码 / 热生效 / 恢复默认。

覆盖"设置面板"的完整契约，其中热生效（保存后无需重启即生效）是核心卖点。
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.core import runtime_settings as rt
from app.core.config import get_settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """覆盖值文件指向临时目录；每个用例前后清空 get_settings 缓存。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    rt.reset_overrides()
    yield tmp_path
    rt.reset_overrides()
    get_settings.cache_clear()


# ------------------------------------------------------------ 单元：规格与截断

def test_sanitize_updates_whitelist_and_clamp() -> None:
    accepted, rejected = rt.sanitize_updates({
        "llm_temperature": -5,          # clamp 到下限 0
        "retrieval_top_k": 99,          # clamp 到上限 10
        "rerank_enabled": "false",      # 字符串布尔归一化
        "llm_provider": "bad-provider",  # select 校验失败
        "custom_instruction": "x" * 999,  # 超过 max_length
        "unknown_field": 1,              # 白名单外
    })
    assert accepted["llm_temperature"] == 0.0
    assert accepted["retrieval_top_k"] == 10
    assert accepted["rerank_enabled"] is False
    assert set(rejected) == {"llm_provider", "custom_instruction", "unknown_field"}


def test_mask_key_only_shows_tail() -> None:
    assert rt.mask_key("sk-1234567890abcd") == "••••abcd"
    assert rt.mask_key("") == ""
    assert rt.mask_key(None) == ""
    assert rt.is_masked("••••abcd") and rt.is_masked("") and rt.is_masked(None)
    assert not rt.is_masked("sk-real-key")


# ------------------------------------------------------------ 接口：读取

def test_get_settings_returns_spec_and_masked_key(isolated_runtime) -> None:
    rt.apply_overrides({"llm_api_key": "sk-super-secret-abcd", "llm_temperature": 0.55})
    get_settings.cache_clear()

    payload = client.get("/api/settings").json()

    keys = {item["key"] for item in payload["spec"]}
    assert {"llm_provider", "llm_base_url", "llm_model", "llm_api_key", "ollama_model",
            "llm_temperature", "llm_top_p", "llm_max_tokens",
            "retrieval_top_k", "similarity_threshold", "rerank_enabled", "rerank_alpha",
            "recall_multiplier", "batch_concurrency", "custom_instruction"} <= keys
    assert payload["values"]["llm_api_key"].endswith("abcd")
    assert "super-secret" not in json.dumps(payload)     # 明文 Key 绝不出现在响应里
    assert payload["values"]["llm_temperature"] == 0.55
    assert "llm_temperature" in payload["overridden"]
    assert payload["mode"] in ("cloud", "ollama", "mock")


# ------------------------------------------------------------ 接口：保存

def test_put_clamps_and_reports_rejected(isolated_runtime) -> None:
    resp = client.put("/api/settings", json={"values": {
        "llm_temperature": 99,          # 越界 → 截断到 2.0
        "retrieval_top_k": 3,
        "hacker_field": 1,             # 未知键 → 拒绝
    }}).json()

    assert resp["saved"] == ["llm_temperature", "retrieval_top_k"]
    assert resp["rejected"] == ["hacker_field"]
    assert resp["hot_applied"] is True
    assert get_settings().llm_temperature == 2.0
    assert get_settings().retrieval_top_k == 3


def test_key_masked_or_empty_means_unchanged(isolated_runtime) -> None:
    rt.apply_overrides({"llm_api_key": "sk-original-key-1234"})
    get_settings.cache_clear()

    masked = client.get("/api/settings").json()["values"]["llm_api_key"]
    assert masked == "••••1234"

    client.put("/api/settings", json={"values": {"llm_api_key": masked}})   # 掩码回传
    client.put("/api/settings", json={"values": {"llm_api_key": ""}})       # 留空
    assert get_settings().llm_api_key == "sk-original-key-1234"             # 均视为不修改

    client.put("/api/settings", json={"values": {"llm_api_key": "sk-new-key-9999"}})
    assert get_settings().llm_api_key == "sk-new-key-9999"


def test_provider_switch_is_hot_applied(isolated_runtime) -> None:
    """切通道无需重启：保存后 /api/health 立刻反映新模式。"""
    client.put("/api/settings", json={"values": {"llm_provider": "ollama"}})
    health = client.get("/api/health").json()
    assert health["llm_mode"] == "ollama"
    assert health["llm_provider"] == "ollama"


def test_temperature_change_is_hot_applied(isolated_runtime) -> None:
    client.put("/api/settings", json={"values": {"llm_temperature": 0.9}})
    assert get_settings().llm_temperature == 0.9     # 无需重启，直接生效


def test_reset_restores_defaults(isolated_runtime) -> None:
    client.put("/api/settings", json={"values": {"llm_temperature": 1.2, "custom_instruction": "用表格输出"}})
    assert (isolated_runtime / rt.RUNTIME_FILE_NAME).exists()

    resp = client.post("/api/settings/reset").json()

    assert resp["reset"] is True
    assert resp["overridden"] == []
    assert not (isolated_runtime / rt.RUNTIME_FILE_NAME).exists()
    assert get_settings().llm_temperature != 1.2     # 回到 .env / 默认值
    assert get_settings().custom_instruction == ""
