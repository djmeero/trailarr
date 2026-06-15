"""Tests for the clip download pipeline and naming helpers."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

import core.base.database.manager.clip as clip_manager
import core.base.database.manager.media as media_manager
from core.base.database.models.clip import ClipCreate
from core.base.database.models.connection import (
    ArrType,
    Connection,
    MonitorType,
)
from core.base.database.models.media import MediaCreate
from core.base.database.utils.engine import write_session
from core.download import clip as clip_mod


# -------------------------------------------------------------------
# Naming helpers (pure)
# -------------------------------------------------------------------


def test_sanitize_strips_illegal_chars():
    # Illegal chars after C: * ? " < > |  -> six underscores
    assert clip_mod.sanitize_title('A:B/C*?"<>|D') == "A_B_C______D"


def test_build_clip_path_with_year(tmp_path):
    p = clip_mod.build_clip_path(str(tmp_path), "Inception", 2010, 3)
    assert p == str(tmp_path / "Inception (2010) - 3.mp4")


def test_build_clip_path_without_year(tmp_path):
    p = clip_mod.build_clip_path(str(tmp_path), "Some Show", 0, 1)
    assert p == str(tmp_path / "Some Show - 1.mp4")


def test_resolve_clips_dir_falls_back_to_app_data(monkeypatch):
    monkeypatch.setattr(clip_mod.app_settings, "clips_dir", "")
    resolved = clip_mod.resolve_clips_dir()
    assert Path(resolved).name == "clips"


# -------------------------------------------------------------------
# Pipeline (subprocess mocked)
# -------------------------------------------------------------------


@write_session
def _create_test_connection(
    name: str = "Clip Pipe Connection",
    *,
    _session: Session = None,  # type: ignore
) -> Connection:
    connection = Connection(
        name=name,
        arr_type=ArrType.RADARR,
        url="http://localhost:7878",
        api_key="test_api_key",
        monitor=MonitorType.MONITOR_MISSING,
    )
    _session.add(connection)
    _session.commit()
    _session.refresh(connection)
    return connection


@pytest.fixture
def media():
    connection = _create_test_connection()
    media_data = MediaCreate(
        connection_id=connection.id,  # type: ignore
        arr_id=1,
        is_movie=True,
        title="Pipe Movie",
        year=2021,
        txdb_id="tt0001112",
    )
    result = media_manager.create_or_update_bulk([media_data])
    return result[0][0]


@pytest.mark.asyncio
async def test_download_clip_dedup_skips(media, monkeypatch):
    clip_manager.create(
        ClipCreate(
            media_id=media.id,
            clip_number=1,
            url="dupe",
            file_name="f.mp4",
            path="/p/f.mp4",
            size=1,
            file_format="mp4",
            downloaded_at=datetime.now(timezone.utc),
        )
    )
    called = {"download": False}

    def _fake_download(*a, **k):
        called["download"] = True
        return {}

    monkeypatch.setattr(clip_mod, "_download_clip_file", _fake_download)

    result = await clip_mod.download_clip(media, "dupe")
    assert result is None
    assert called["download"] is False


@pytest.mark.asyncio
async def test_download_clip_creates_record(media, tmp_path, monkeypatch):
    monkeypatch.setattr(clip_mod.app_settings, "clips_dir", str(tmp_path))

    def _fake_download(url, temp_out, _stop_event=None):
        Path(temp_out).write_bytes(b"x" * 100)
        return {"extractor": "tiktok", "id": "vid123", "uploader": "bob"}

    monkeypatch.setattr(clip_mod, "_download_clip_file", _fake_download)
    monkeypatch.setattr(
        clip_mod,
        "_probe_clip",
        lambda path: {"duration": 30, "resolution": 1920, "size": 100},
    )

    result = await clip_mod.download_clip(media, "https://tiktok/x")
    assert result is not None
    assert result.clip_number == 1
    assert result.source == "tiktok"
    assert result.source_id == "vid123"
    assert result.uploader == "bob"
    assert result.file_format == "mp4"
    assert result.file_name == "Pipe Movie (2021) - 1.mp4"
    assert Path(result.path).exists()
    assert clip_manager.count_by_media_id(media.id) == 1


@pytest.mark.asyncio
async def test_download_clip_increments_number(media, tmp_path, monkeypatch):
    monkeypatch.setattr(clip_mod.app_settings, "clips_dir", str(tmp_path))

    def _fake_download(url, temp_out, _stop_event=None):
        Path(temp_out).write_bytes(b"x" * 10)
        return {}

    monkeypatch.setattr(clip_mod, "_download_clip_file", _fake_download)
    monkeypatch.setattr(
        clip_mod,
        "_probe_clip",
        lambda path: {"duration": 1, "resolution": 0, "size": 10},
    )

    first = await clip_mod.download_clip(media, "https://tiktok/a")
    second = await clip_mod.download_clip(media, "https://tiktok/b")
    assert first.clip_number == 1
    assert second.clip_number == 2
    assert second.file_name == "Pipe Movie (2021) - 2.mp4"
