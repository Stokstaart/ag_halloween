"""Pytest configuratie en fixtures voor Halloween Projection Control."""
import os
import pytest
import app.config as config
import app.main as main_module


@pytest.fixture(autouse=True)
def reset_auth_for_tests(monkeypatch):
    """Zorgt ervoor dat tests standaard in open LAN-modus draaien, tenzij test_auth expliciet een token instelt."""
    monkeypatch.setattr(config, "AUTH_TOKEN", "")
    monkeypatch.setattr(main_module, "AUTH_TOKEN", "")
