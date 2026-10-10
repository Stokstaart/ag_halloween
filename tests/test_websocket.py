"""Tests voor de WebSocket communicatie."""
import json
import pytest
from starlette.testclient import TestClient
from app.main import app, engine, manager


@pytest.fixture(autouse=True)
def cleanup_ws():
    engine.stop_effect()
    engine.last_effect_ended_at = 0.0
    yield
    # Schoon managers op
    manager.screen_connections.clear()
    manager.controller_connections.clear()


def test_websocket_screen_connection():
    """Test dat een projectiescherm verbindt en het init-bericht ontvangt."""
    client = TestClient(app)
    with client.websocket_connect("/ws?role=screen") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "init"
        assert "background" in msg
        assert "volume" in msg
        assert len(manager.screen_connections) == 1


def test_websocket_controller_connection():
    """Test dat een mobiele controller verbindt en het init-bericht ontvangt."""
    client = TestClient(app)
    with client.websocket_connect("/ws?role=control") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "init"
        assert "effects" in msg
        assert "status" in msg
        assert len(manager.controller_connections) == 1


def test_websocket_ping_pong():
    """Test ping/pong mechanisme vanaf controller."""
    client = TestClient(app)
    with client.websocket_connect("/ws?role=control") as ws:
        _ = ws.receive_json()  # Consumeer init
        ws.send_json({"action": "ping"})
        resp = ws.receive_json()
        assert resp["type"] == "pong"


def test_websocket_stop_broadcast():
    """Test dat een stop-commando van de controller gebroadcast wordt naar het scherm."""
    client = TestClient(app)
    with client.websocket_connect("/ws?role=screen") as ws_screen:
        _ = ws_screen.receive_json()  # Consumeer init van screen

        with client.websocket_connect("/ws?role=control") as ws_control:
            _ = ws_control.receive_json()  # Consumeer init van control
            # Screen krijgt ook stats update wanneer control verbindt (of omgekeerd)

            # Stuur stop actie vanaf controller
            ws_control.send_json({"action": "stop"})

            # Screen moet stop_effect ontvangen
            msg_screen = ws_screen.receive_json()
            assert msg_screen["type"] == "stop_effect"

            # Control moet effect_stopped ontvangen
            msg_control = ws_control.receive_json()
            assert msg_control["type"] == "effect_stopped"


def test_websocket_large_message_rejected():
    """Test dat overmatig grote berichten (> 64KB) netjes geweigerd worden."""
    client = TestClient(app)
    with client.websocket_connect("/ws?role=control") as ws:
        _ = ws.receive_json()  # init
        huge_payload = json.dumps({"action": "test", "data": "A" * (70 * 1024)})
        ws.send_text(huge_payload)
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert "overschrijdt maximale toegestane grootte" in resp["message"]
