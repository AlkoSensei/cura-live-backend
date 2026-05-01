from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_warmup_worker_external_when_embedded_disabled(monkeypatch: object) -> None:
    monkeypatch.setenv("START_EMBEDDED_LIVEKIT_WORKER", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.get("/api/warmup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["worker"] == "external"
