"""Tests voor de MediaOptimizer (FastStart en codec controle)."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.media_optimizer import is_faststart_mp4


def test_media_optimizer_health():
    client = TestClient(app)
    res = client.get("/api/media/health")
    assert res.status_code == 200
    data = res.json()
    assert "total_videos" in data
    assert "optimal_count" in data
    assert "needs_optimization" in data
    assert isinstance(data["files"], list)


def test_is_faststart_mp4_logic(tmp_path):
    # Dummy file met moov vóór mdat
    valid_faststart = tmp_path / "valid.mp4"
    valid_faststart.write_bytes(b"\x00\x00\x00\x20ftypisom\x00\x00\x00\x40moov...\x00\x00\x00\x40mdat...")
    assert is_faststart_mp4(valid_faststart) is True

    # Dummy file met mdat vóór moov
    non_faststart = tmp_path / "slow.mp4"
    non_faststart.write_bytes(b"\x00\x00\x00\x20ftypisom\x00\x00\x00\x40mdat...\x00\x00\x00\x40moov...")
    assert is_faststart_mp4(non_faststart) is False
