from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import MIB, Settings
from app.main import create_app
from app.models import Recording
from conftest import make_settings, make_wav_bytes, upload


@pytest.fixture
def db_session(settings):
    from app import db

    with db.SessionLocal() as session:
        yield session


def rows(db_session):
    return db_session.query(Recording).all()


def test_upload_wav_ok(client, settings, db_session):
    content = make_wav_bytes()
    response = upload(client, "rec.wav", content)

    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "rec.wav"
    assert body["status"] == "uploaded"
    assert body["file_size"] == len(content)

    stored = Path(settings.audio_storage_dir) / body["stored_filename"]
    assert stored.is_file()
    assert stored.read_bytes() == content

    records = rows(db_session)
    assert len(records) == 1
    assert records[0].status == "uploaded"
    assert records[0].file_size == len(content)


def test_upload_mp3_ok(client, settings, db_session):
    content = b"\xff\xfb\x90\x00" + b"\x00" * 100
    response = upload(client, "song.MP3", content, content_type="audio/mpeg")

    assert response.status_code == 201
    body = response.json()
    assert body["stored_filename"].endswith(".mp3")

    stored = Path(settings.audio_storage_dir) / body["stored_filename"]
    assert stored.is_file()
    assert stored.read_bytes() == content
    assert len(rows(db_session)) == 1


def test_reject_unsupported_extension(client, settings, db_session):
    response = upload(client, "notes.txt", b"hello", content_type="text/plain")

    assert 400 <= response.status_code < 500
    assert list(Path(settings.audio_storage_dir).iterdir()) == []
    assert rows(db_session) == []


def test_reject_file_over_50mb(client, settings, db_session):
    content = b"\x00" * (51 * MIB)
    response = upload(client, "big.wav", content)

    assert response.status_code == 413
    assert list(Path(settings.audio_storage_dir).iterdir()) == []
    assert rows(db_session) == []


def test_default_limit_is_50mb():
    assert Settings(_env_file=None).max_file_size_bytes == 50 * MIB


def test_list_recordings(client):
    upload(client, "first.wav", make_wav_bytes())
    upload(client, "second.wav", make_wav_bytes())

    response = client.get("/recordings")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert [item["original_filename"] for item in items] == ["second.wav", "first.wav"]


def test_same_original_name_twice(client, settings, db_session):
    upload(client, "rec.wav", make_wav_bytes())
    upload(client, "rec.wav", make_wav_bytes())

    records = rows(db_session)
    assert len(records) == 2
    stored_names = {r.stored_filename for r in records}
    assert len(stored_names) == 2
    for name in stored_names:
        assert (Path(settings.audio_storage_dir) / name).is_file()


def test_persistence_after_restart(client, settings, tmp_path):
    upload(client, "rec.wav", make_wav_bytes())

    restarted_app = create_app(make_settings(tmp_path))
    with TestClient(restarted_app) as restarted_client:
        response = restarted_client.get("/recordings")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["original_filename"] == "rec.wav"


def test_no_orphan_file_when_db_fails(client, settings, db_session, monkeypatch):
    def broken_commit(self):
        raise RuntimeError("db failure")

    monkeypatch.setattr(Session, "commit", broken_commit)
    response = upload(client, "rec.wav", make_wav_bytes())
    monkeypatch.undo()

    assert response.status_code == 500
    assert list(Path(settings.audio_storage_dir).iterdir()) == []

    count = db_session.execute(
        text("SELECT COUNT(*) FROM recordings")
    ).scalar_one()
    assert count == 0
