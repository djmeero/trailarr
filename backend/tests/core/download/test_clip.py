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


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/@x/video/123",
        "http://example.com/clip",
        "https://youtu.be/abc",
    ],
)
def test_is_valid_clip_url_accepts_http(url):
    assert clip_mod.is_valid_clip_url(url) is True


def test_build_ytdlp_error_login_required():
    from subprocess import CompletedProcess

    stderr = (
        "[TikTok] Extracting URL: https://...\n"
        "ERROR: [TikTok] 7649: TikTok is requiring login for access to this"
        " content. Use --cookies-from-browser or --cookies.\n"
    )
    result = CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)
    msg = clip_mod._build_ytdlp_error(result)
    assert "requires login" in msg.lower()
    assert "cookies" in msg.lower()
    assert "requiring login" in msg.lower()  # the real yt-dlp line is included


def test_build_ytdlp_error_generic():
    from subprocess import CompletedProcess

    stderr = "ERROR: Unable to download webpage: HTTP Error 404: Not Found\n"
    result = CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)
    msg = clip_mod._build_ytdlp_error(result)
    assert "404" in msg
    assert "yt-dlp error" in msg.lower()


def test_build_ytdlp_error_no_error_line():
    from subprocess import CompletedProcess

    result = CompletedProcess(args=[], returncode=2, stdout="", stderr="")
    msg = clip_mod._build_ytdlp_error(result)
    assert "exit 2" in msg


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "--exec=calc.exe",
        "-J",
        "ftp://example.com/x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "just-text",
        "https://",  # no host
    ],
)
def test_is_valid_clip_url_rejects_non_http_and_flags(url):
    assert clip_mod.is_valid_clip_url(url) is False


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
            url="https://tiktok/dupe",
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

    result = await clip_mod.download_clip(media, "https://tiktok/dupe")
    assert result is None
    assert called["download"] is False


@pytest.mark.asyncio
async def test_download_clip_rejects_flag_like_url(media, monkeypatch):
    called = {"download": False}

    def _fake_download(*a, **k):
        called["download"] = True
        return {}

    monkeypatch.setattr(clip_mod, "_download_clip_file", _fake_download)

    from exceptions import DownloadFailedError

    with pytest.raises(DownloadFailedError):
        await clip_mod.download_clip(media, "--exec=calc.exe")
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
async def test_download_clip_moves_cross_device(media, tmp_path, monkeypatch):
    """The final move must not rely on os.replace, which fails across
    filesystems (temp dir vs a /media mount) with 'Invalid cross-device link'.
    """
    monkeypatch.setattr(clip_mod.app_settings, "clips_dir", str(tmp_path))

    def _boom(*a, **k):
        raise OSError(18, "Invalid cross-device link")

    # If the code regressed to os.replace, this would surface the bug.
    monkeypatch.setattr(clip_mod.os, "replace", _boom)

    def _fake_download(url, temp_out, _stop_event=None):
        Path(temp_out).write_bytes(b"x" * 100)
        return {}

    monkeypatch.setattr(clip_mod, "_download_clip_file", _fake_download)
    monkeypatch.setattr(
        clip_mod,
        "_probe_clip",
        lambda path: {"duration": 1, "resolution": 0, "size": 100},
    )

    result = await clip_mod.download_clip(media, "https://tiktok/x")
    assert result is not None
    assert Path(result.path).exists()


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
