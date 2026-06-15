"""Tests for the Clip model and Clip manager."""

from datetime import datetime, timezone

import pytest
from sqlmodel import Session

import core.base.database.manager.clip as clip_manager
import core.base.database.manager.media as media_manager
from core.base.database.models.clip import Clip, ClipCreate, ClipRead
from core.base.database.models.connection import (
    ArrType,
    Connection,
    MonitorType,
)
from core.base.database.models.media import MediaCreate
from core.base.database.utils.engine import write_session
from exceptions import ItemNotFoundError


@write_session
def _create_test_connection(
    name: str = "Clip Test Connection",
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


def _make_clip(media_id: int, n: int, url: str) -> ClipCreate:
    return ClipCreate(
        media_id=media_id,
        clip_number=n,
        url=url,
        file_name=f"M (2020) - {n}.mp4",
        path=f"/clips/M (2020) - {n}.mp4",
        size=10,
        duration=5,
        resolution=1080,
        file_format="mp4",
        downloaded_at=datetime.now(timezone.utc),
    )


def test_clip_create_defaults():
    c = ClipCreate(
        media_id=5,
        clip_number=1,
        url="https://www.tiktok.com/@x/video/123",
        file_name="Movie (2020) - 1.mp4",
        path="/clips/Movie (2020) - 1.mp4",
        size=1024,
        file_format="mp4",
        downloaded_at=datetime.now(timezone.utc),
    )
    assert c.source == "unknown"
    assert c.source_id == "unknown"
    assert c.uploader == "unknown"
    assert c.file_exists is True
    assert c.duration == 0
    assert c.resolution == 0


def test_clip_read_validates_from_db_model():
    c = Clip(
        media_id=5,
        clip_number=2,
        url="u",
        file_name="f.mp4",
        path="/p/f.mp4",
        size=1,
        file_format="mp4",
        downloaded_at=datetime.now(timezone.utc),
    )
    c.id = 7
    read = ClipRead.model_validate(c)
    assert read.id == 7
    assert read.media_id == 5


class TestClipManager:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.connection = _create_test_connection()
        media_data = MediaCreate(
            connection_id=self.connection.id,  # type: ignore
            arr_id=1,
            is_movie=True,
            title="Test Movie",
            txdb_id="tt7654321",
        )
        result = media_manager.create_or_update_bulk([media_data])
        self.media, _, _, _ = result[0]

    def test_next_clip_number_starts_at_one(self):
        assert clip_manager.next_clip_number(self.media.id) == 1

    def test_create_and_increment(self):
        clip_manager.create(_make_clip(self.media.id, 1, "u1"))
        assert clip_manager.next_clip_number(self.media.id) == 2
        assert clip_manager.count_by_media_id(self.media.id) == 1

    def test_read_by_media_url_dedup(self):
        clip_manager.create(_make_clip(self.media.id, 1, "u1"))
        assert clip_manager.read_by_media_url(self.media.id, "u1") is not None
        assert clip_manager.read_by_media_url(self.media.id, "nope") is None

    def test_read_by_media_id_ordered(self):
        clip_manager.create(_make_clip(self.media.id, 2, "u2"))
        clip_manager.create(_make_clip(self.media.id, 1, "u1"))
        clips = clip_manager.read_by_media_id(self.media.id)
        assert [c.clip_number for c in clips] == [1, 2]

    def test_delete(self):
        created = clip_manager.create(_make_clip(self.media.id, 1, "u1"))
        assert clip_manager.delete(created.id) is True
        assert clip_manager.count_by_media_id(self.media.id) == 0
        with pytest.raises(ItemNotFoundError):
            clip_manager.read(created.id)

    def test_mark_as_deleted(self):
        created = clip_manager.create(_make_clip(self.media.id, 1, "u1"))
        updated = clip_manager.mark_as_deleted(created.id)
        assert updated.file_exists is False

    def test_delete_all_for_media(self):
        clip_manager.create(_make_clip(self.media.id, 1, "u1"))
        clip_manager.create(_make_clip(self.media.id, 2, "u2"))
        assert clip_manager.delete_all_for_media(self.media.id) == 2
        assert clip_manager.count_by_media_id(self.media.id) == 0
