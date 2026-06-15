import os

from fastapi import APIRouter
from pydantic import BaseModel

from app_logger import ModuleLogger
import core.base.database.manager.clip as clip_manager
import core.base.database.manager.event as event_manager
from core.base.database.models.clip import ClipRead
from core.base.database.models.event import EventSource
from core.tasks.download_clips import download_clip_by_id

logger = ModuleLogger("ClipsAPI")

# Global clip routes (list + delete)
clips_router = APIRouter(prefix="/clips", tags=["Clips"])
# Media-scoped clip routes (sit next to the trailer routes under /media)
media_clips_router = APIRouter(prefix="/media", tags=["Clips"])


class ClipCreateRequest(BaseModel):
    url: str


@media_clips_router.get("/{media_id}/clips")
async def get_media_clips(media_id: int) -> list[ClipRead]:
    """Get all clips for a media item."""
    return clip_manager.read_by_media_id(media_id)


@media_clips_router.post("/{media_id}/clips")
async def download_media_clip(media_id: int, body: ClipCreateRequest) -> str:
    """Download a clip for a media item from a pasted URL. \n
    Schedules a background download and returns immediately.
    """
    return download_clip_by_id(media_id, body.url)


@clips_router.get("")
async def get_all_clips() -> list[ClipRead]:
    """Get all clips across all media (for the global Clips page)."""
    return clip_manager.read_all()


@clips_router.delete("/{clip_id}")
async def delete_clip(clip_id: int) -> str:
    """Delete a clip record and its file on disk."""
    clip = clip_manager.read(clip_id)
    if clip.path and os.path.exists(clip.path):
        try:
            os.remove(clip.path)
        except OSError as e:
            logger.warning(f"Failed to delete clip file {clip.path}: {e}")
    clip_manager.delete(clip_id)
    event_manager.track_clip_deleted(
        media_id=clip.media_id,
        reason="user_request",
        source=EventSource.USER,
        source_detail="ClipDelete",
    )
    return f"Clip [{clip_id}] deleted"
