import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MIB = 1024 * 1024


def make_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        audio_storage_dir=str(tmp_path / "audio"),
    )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def make_wav_bytes() -> bytes:
    return (
        b"RIFF"
        + (36).to_bytes(4, "little")
        + b"WAVE"
        + b"fmt "
        + (16).to_bytes(4, "little")
        + b"\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00"
        + b"data"
        + (0).to_bytes(4, "little")
    )


def upload(client, name: str, content: bytes, content_type: str = "audio/wav"):
    return client.post(
        "/recordings",
        files={"file": (name, content, content_type)},
    )
