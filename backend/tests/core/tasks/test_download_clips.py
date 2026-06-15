"""Tests for the clip download task."""

import pytest
from sqlmodel import Session

import core.base.database.manager.media as media_manager
from core.base.database.models.connection import (
    ArrType,
    Connection,
    MonitorType,
)
from core.base.database.models.media import MediaCreate
from core.base.database.utils.engine import write_session
from core.tasks import download_clips
from exceptions import InvalidResponseError, ItemNotFoundError


@write_session
def _create_test_connection(
    name: str = "Clip Task Connection",
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
        title="Task Movie",
        txdb_id="tt0009999",
    )
    result = media_manager.create_or_update_bulk([media_data])
    return result[0][0]


def test_download_clip_by_id_schedules(media, monkeypatch):
    captured = {}

    def _fake_add_task(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(download_clips.scheduler, "add_task", _fake_add_task)

    msg = download_clips.download_clip_by_id(media.id, "https://tiktok/x")
    assert "background" in msg.lower()
    assert captured["run_once"] is True
    assert captured["args"][1] == "https://tiktok/x"


def test_download_clip_by_id_rejects_blank_url(media):
    with pytest.raises(InvalidResponseError):
        download_clips.download_clip_by_id(media.id, "   ")


def test_download_clip_by_id_unknown_media():
    with pytest.raises(ItemNotFoundError):
        download_clips.download_clip_by_id(999999, "https://tiktok/x")
