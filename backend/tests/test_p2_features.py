"""P2 功能测试：检索消融报告接口 + Ollama 模型拉取（校验与错误路径）。

不依赖真实 Ollama/网络：拉取用例只覆盖"参数校验"与"连不上时的可读错误"。
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app

client = TestClient(app)


# ------------------------------------------------------------ 检索消融报告接口

def test_ablation_endpoint_returns_latest_report(tmp_path, monkeypatch) -> None:
    from app.api import eval as eval_api

    class _TmpSettings(Settings):
        @property
        def reports_dir(self) -> Path:
            return tmp_path

    payload = {
        "summary": "切块粒度 × 检索模式 × 重排 × Top-k 消融实验（检索层代理指标）",
        "note": "kw_coverage@k/hit@1 越高越好",
        "similarity_threshold": 0.6,
        "timestamp": "2026-09-22 10:00:00",
        "dataset_size": 60,
        "corpus_units": 171,
        "grounding": {"graded_items": 56, "grounded_items": 56,
                      "grounding_rate": 1.0, "ungrounded": []},
        "grid": {"chunk_sizes": [600], "top_ks": [2, 4]},
        "rows": [
            {"chunk_size": 600, "mode": "hybrid", "rerank": "on", "top_k": 4,
             "kw_coverage@k": 0.905, "hit@1": 0.946, "refusal_correct": 1.0, "avg_max_cos": 0.83},
            {"chunk_size": 600, "mode": "vector", "rerank": "off", "top_k": 2,
             "kw_coverage@k": 0.774, "hit@1": 0.893, "refusal_correct": 1.0, "avg_max_cos": 0.80},
        ],
    }
    (tmp_path / "ablation_20260922_100000.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(eval_api, "get_settings", lambda: _TmpSettings())

    data = client.get("/api/eval/ablation").json()

    assert data["available"] is True
    assert data["file"] == "ablation_20260922_100000.json"
    assert len(data["rows"]) == 2
    assert data["grounding"]["grounding_rate"] == 1.0
    assert data["grid"]["chunk_sizes"] == [600]


def test_ablation_endpoint_handles_missing_and_malformed(tmp_path, monkeypatch) -> None:
    from app.api import eval as eval_api

    class _TmpSettings(Settings):
        @property
        def reports_dir(self) -> Path:
            return tmp_path

    monkeypatch.setattr(eval_api, "get_settings", lambda: _TmpSettings())
    assert client.get("/api/eval/ablation").json() == {"available": False}

    (tmp_path / "ablation_broken.json").write_text("{不是 JSON", encoding="utf-8")
    data = client.get("/api/eval/ablation").json()
    assert data["available"] is False
    assert "解析失败" in data["error"]


# ------------------------------------------------------------ Ollama 拉取接口

def test_pull_rejects_invalid_model_name(monkeypatch) -> None:
    from app.api import llm as llm_api

    for bad_name in ("", "  ", "bad name!", "../../etc/passwd", "x" * 81):
        response = client.post("/api/llm/pull", json={"model": bad_name})
        assert response.status_code == 400, bad_name
        assert "模型名不合法" in response.json()["detail"]


def test_pull_reports_readable_error_when_ollama_unreachable(monkeypatch) -> None:
    """Ollama 未启动：流里给出 error 事件 + 排查提示，而不是 500/静默。"""
    from app.api import llm as llm_api

    monkeypatch.setattr(
        llm_api, "get_settings",
        lambda: Settings(_env_file=None, ollama_base_url="http://127.0.0.1:11499/v1"))

    response = client.post("/api/llm/pull", json={"model": "qwen2.5:3b"})

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events and events[-1]["type"] == "error"
    assert "Ollama" in events[-1]["hint"]
    assert events[-1]["model"] == "qwen2.5:3b"


def test_ollama_native_base_strips_compat_suffix(monkeypatch) -> None:
    from app.api import llm as llm_api

    cases = [
        ("http://localhost:11434/v1", "http://localhost:11434"),
        ("http://localhost:11434/v1/", "http://localhost:11434"),
        ("http://192.168.1.5:11434/api", "http://192.168.1.5:11434"),
        ("http://localhost:11434", "http://localhost:11434"),
    ]
    for configured, expected in cases:
        monkeypatch.setattr(
            llm_api, "get_settings",
            lambda value=configured: Settings(_env_file=None, ollama_base_url=value))
        assert llm_api._ollama_native_base() == expected


# ------------------------------------------------------------ Ollama 安装检测

def test_ollama_install_detection_and_hints(monkeypatch) -> None:
    """区分「未安装」与「装了没启动」：两者排查方式完全不同。"""
    from app.services import ollama_env

    monkeypatch.setattr(ollama_env.shutil, "which", lambda name: None)
    monkeypatch.setattr(ollama_env, "_DEFAULT_PATHS", ())
    assert ollama_env.ollama_installed() is False
    hint = ollama_env.ollama_failure_hint("qwen2.5:3b")
    assert "未检测到本地 Ollama" in hint
    assert "ollama.com/download" in hint

    monkeypatch.setattr(ollama_env.shutil, "which", lambda name: "/usr/bin/ollama")
    assert ollama_env.ollama_installed() is True
    hint = ollama_env.ollama_failure_hint("qwen2.5:3b")
    assert "已检测到 Ollama 安装但服务未响应" in hint
    assert "ollama pull qwen2.5:3b" in hint


def test_ollama_install_detection_falls_back_to_default_paths(monkeypatch, tmp_path) -> None:
    from app.services import ollama_env

    fake_binary = tmp_path / "ollama.exe"
    fake_binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(ollama_env.shutil, "which", lambda name: None)
    monkeypatch.setattr(ollama_env, "_DEFAULT_PATHS", (fake_binary,))
    assert ollama_env.ollama_installed() is True


def test_status_reports_ollama_install_state(monkeypatch) -> None:
    """未安装 Ollama 时，状态接口要明确告知（而不是笼统的"连接失败"）。"""
    from app.api import llm as llm_api
    from app.services import ollama_env

    monkeypatch.setattr(
        llm_api, "get_settings",
        lambda: Settings(_env_file=None, llm_provider="ollama",
                         ollama_base_url="http://127.0.0.1:11499/v1",
                         ollama_model="qwen2.5:3b"))
    monkeypatch.setattr(ollama_env.shutil, "which", lambda name: None)
    monkeypatch.setattr(ollama_env, "_DEFAULT_PATHS", ())

    data = client.get("/api/llm/status").json()

    assert data["ok"] is False
    assert data["ollama_installed"] is False
    assert "未检测到本地 Ollama" in data["hint"]


# ------------------------------------------------------------ .env 写入工具（一键部署脚本使用）

def test_apply_env_value_replaces_and_appends(tmp_path) -> None:
    """部署脚本用它设置 LLM_MOCK / LLM_PROVIDER：替换已有键、追加新键、保留注释。"""
    import sys as _sys
    from pathlib import Path as _Path

    scripts_dir = _Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    from apply_env_value import apply_value  # noqa: E402

    env_file = tmp_path / ".env"
    env_file.write_text("# 注释\nLLM_PROVIDER=cloud\nLLM_MOCK=false\n", encoding="utf-8")

    assert apply_value(env_file, "LLM_MOCK", "true") is True     # 替换已有键
    assert apply_value(env_file, "OLLAMA_MODEL", "qwen2.5:3b") is False  # 追加新键

    text = env_file.read_text(encoding="utf-8")
    assert "# 注释" in text                    # 注释保留
    assert "LLM_PROVIDER=cloud" in text        # 无关行不动
    assert "LLM_MOCK=true" in text and "LLM_MOCK=false" not in text
    assert text.endswith("OLLAMA_MODEL=qwen2.5:3b\n")
