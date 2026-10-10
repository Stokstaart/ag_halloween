"""Tests voor de authenticatie en beveiliging."""
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
import app.main as main_module
import app.config as config


@pytest.mark.asyncio
async def test_auth_protection_enabled(monkeypatch):
    """Test dat endpoints 401 vereisen wanneer AUTH_TOKEN is ingesteld."""
    monkeypatch.setattr(config, "AUTH_TOKEN", "spooky_secret_key_123")
    monkeypatch.setattr(main_module, "AUTH_TOKEN", "spooky_secret_key_123")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Zonder token -> 401
        res_no_auth = await client.get("/api/status")
        assert res_no_auth.status_code == 401

        # 2. Met foutief token -> 401
        res_bad_auth = await client.get("/api/status", headers={"Authorization": "Bearer verkeerd_token"})
        assert res_bad_auth.status_code == 401

        # 3. Met geldig Bearer token -> 200
        res_bearer = await client.get("/api/status", headers={"Authorization": "Bearer spooky_secret_key_123"})
        assert res_bearer.status_code == 200

        # 4. Met geldig X-Auth-Token header -> 200
        res_x_header = await client.get("/api/status", headers={"X-Auth-Token": "spooky_secret_key_123"})
        assert res_x_header.status_code == 200

        # 5. Met query param (?token=...) -> 200
        res_query = await client.get("/api/status?token=spooky_secret_key_123")
        assert res_query.status_code == 200
