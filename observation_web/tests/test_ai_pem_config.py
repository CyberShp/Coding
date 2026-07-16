"""AI custom CA PEM path configuration contract."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import certifi
import pytest

from backend.api.auth import _create_token
from backend.config import AppConfig
from backend.core import ai_service


def _admin_headers():
    return {"Authorization": f"Bearer {_create_token('admin')}"}


def test_ai_pem_path_survives_config_round_trip(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig()
    config.ai.pem_cert_path = "/etc/observation/ai-ca.pem"

    config.save(config_path)
    loaded = AppConfig.load(config_path)

    assert loaded.ai.pem_cert_path == "/etc/observation/ai-ca.pem"


def test_httpx_client_uses_configured_pem_as_custom_ca(monkeypatch):
    context = object()
    create_context = MagicMock(return_value=context)
    config = SimpleNamespace(
        ai=SimpleNamespace(
            proxy_mode="none",
            pem_cert_path="/etc/observation/ai-ca.pem",
        )
    )
    monkeypatch.setattr(ai_service, "get_config", lambda: config)
    monkeypatch.setattr(ai_service.ssl, "create_default_context", create_context)

    kwargs = ai_service._get_httpx_client_kwargs()

    assert kwargs["verify"] is context
    assert kwargs["proxy"] is None
    assert kwargs["trust_env"] is False
    create_context.assert_called_once_with(cafile="/etc/observation/ai-ca.pem")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("relative/ai-ca.pem", "绝对路径"),
        ("/path/that/does/not/exist.pem", "文件不存在"),
    ],
)
def test_ai_pem_path_rejects_unusable_paths(value, message):
    with pytest.raises(ValueError, match=message):
        ai_service.validate_ai_pem_path(value)


def test_ai_pem_path_rejects_invalid_ca_content(tmp_path):
    pem_path = tmp_path / "invalid.pem"
    pem_path.write_text("not a certificate", encoding="utf-8")

    with pytest.raises(ValueError, match="无法加载"):
        ai_service.validate_ai_pem_path(str(pem_path))


@pytest.mark.asyncio
async def test_ai_config_api_accepts_user_provided_pem_path(app_client, monkeypatch):
    config = AppConfig()
    config.save = MagicMock()
    monkeypatch.setattr("backend.api.ai.get_config", lambda: config)

    pem_path = certifi.where()
    response = await app_client.put(
        "/api/ai/config",
        json={"pem_cert_path": pem_path},
        headers=_admin_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["pem_cert_path"] == pem_path
    assert config.ai.pem_cert_path == pem_path
    config.save.assert_called_once()


@pytest.mark.asyncio
async def test_ai_config_api_rejects_missing_pem_without_saving(app_client, monkeypatch):
    config = AppConfig()
    config.save = MagicMock()
    monkeypatch.setattr("backend.api.ai.get_config", lambda: config)

    response = await app_client.put(
        "/api/ai/config",
        json={"pem_cert_path": "/missing/ai-ca.pem"},
        headers=_admin_headers(),
    )

    assert response.status_code == 400
    assert "文件不存在" in response.json()["detail"]
    config.save.assert_not_called()
