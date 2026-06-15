"""Tests for the clips API route handlers (called directly)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import api.v1.clips as clips_api
from api.v1.clips import ClipCreateRequest


@pytest.mark.asyncio
async def test_get_media_clips_returns_list():
    fake = [SimpleNamespace(id=1, media_id=5)]
    with patch.object(
        clips_api.clip_manager, "read_by_media_id", return_value=fake
    ) as mock_read:
        result = await clips_api.get_media_clips(5)
    assert result == fake
    mock_read.assert_called_once_with(5)


@pytest.mark.asyncio
async def test_download_media_clip_enqueues():
    with patch.object(
        clips_api,
        "download_clip_by_id",
        return_value="Clip download started in background",
    ) as mock_dl:
        result = await clips_api.download_media_clip(
            5, ClipCreateRequest(url="https://tiktok/x")
        )
    assert "background" in result.lower()
    mock_dl.assert_called_once_with(5, "https://tiktok/x")


@pytest.mark.asyncio
async def test_get_all_clips_returns_list():
    fake = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    with patch.object(clips_api.clip_manager, "read_all", return_value=fake):
        result = await clips_api.get_all_clips()
    assert len(result) == 2


@pytest.mark.asyncio
async def test_delete_clip_removes_file_and_record(tmp_path):
    clip_file = tmp_path / "clip.mp4"
    clip_file.write_bytes(b"x")
    clip = SimpleNamespace(
        id=9, media_id=5, path=str(clip_file), file_exists=True
    )
    with (
        patch.object(clips_api.clip_manager, "read", return_value=clip),
        patch.object(
            clips_api.clip_manager, "delete", MagicMock(return_value=True)
        ) as mock_del,
        patch.object(
            clips_api.event_manager, "track_clip_deleted", MagicMock()
        ) as mock_evt,
    ):
        result = await clips_api.delete_clip(9)
    assert "deleted" in result.lower()
    assert not clip_file.exists()  # file removed
    mock_del.assert_called_once_with(9)
    mock_evt.assert_called_once()


@pytest.mark.asyncio
async def test_delete_clip_missing_file_still_deletes_record():
    clip = SimpleNamespace(
        id=9, media_id=5, path="/does/not/exist.mp4", file_exists=True
    )
    with (
        patch.object(clips_api.clip_manager, "read", return_value=clip),
        patch.object(
            clips_api.clip_manager, "delete", MagicMock(return_value=True)
        ) as mock_del,
        patch.object(
            clips_api.event_manager, "track_clip_deleted", MagicMock()
        ),
    ):
        result = await clips_api.delete_clip(9)
    assert "deleted" in result.lower()
    mock_del.assert_called_once_with(9)
