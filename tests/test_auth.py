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

        # 6. Met auth_token cookie -> 200
        client.cookies.set("auth_token", "spooky_secret_key_123")
        res_cookie = await client.get("/api/status")
        assert res_cookie.status_code == 200


@pytest.mark.asyncio
async def test_login_flow(monkeypatch):
    """Test de complete login- en redirect-flow met sessie-cookie."""
    secret = "geheim_wachtwoord_123"
    monkeypatch.setattr(config, "AUTH_TOKEN", secret)
    monkeypatch.setattr(main_module, "AUTH_TOKEN", secret)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Onbevoegde toegang tot /control leidt door naar /login
        res = await client.get("/control", follow_redirects=False)
        assert res.status_code == 303
        assert res.headers["location"] == "/login?next=/control"

        # Onjuist wachtwoord
        res_bad = await client.post("/login", data={"password": "fout_wachtwoord", "next": "/control"})
        assert res_bad.status_code == 401
        assert "auth_token" not in client.cookies

        # Juist wachtwoord
        res_login = await client.post("/login", data={"password": secret, "next": "/control"}, follow_redirects=False)
        assert res_login.status_code == 303
        assert res_login.headers["location"] == "/control"
        assert client.cookies.get("auth_token") == secret

        # Nu heeft client toegang tot /control
        res_control = await client.get("/control")
        assert res_control.status_code == 200

        # Uitloggen verwijdert cookie
        res_logout = await client.get("/logout", follow_redirects=False)
        assert res_logout.status_code == 303
        assert not client.cookies.get("auth_token")

