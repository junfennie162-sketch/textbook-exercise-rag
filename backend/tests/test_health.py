from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint_reports_backend_is_ready() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "UP"
    assert payload["message"] == "前后端连接正常"
    assert isinstance(payload["llm_mock"], bool)


def test_health_exposes_generation_mode(monkeypatch) -> None:
    """健康检查要暴露当前生成模式，前端据此显示「离线模板模式」提示。"""
    from app.api import health as health_api
    from app.core.config import Settings

    monkeypatch.setattr(health_api, "get_settings", lambda: Settings(llm_mock=True))
    assert client.get("/api/health").json()["llm_mock"] is True

    monkeypatch.setattr(health_api, "get_settings", lambda: Settings(llm_mock=False))
    assert client.get("/api/health").json()["llm_mock"] is False
