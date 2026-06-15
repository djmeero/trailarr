from datetime import datetime, timezone

from pydantic import field_validator
from sqlmodel import Field

from core.base.database.models.base import AppSQLModel


def get_current_time():
    return datetime.now(timezone.utc)


class ClipBase(AppSQLModel):
    """
    Base model for Clip.\n
    Note: \n
        🚨DO NOT USE THIS CLASS DIRECTLY.🚨 \n
    👉Use :class:`Clip` for working with database.👈 \n
    👉Use :class:`ClipCreate` to create clips.👈 \n
    👉Use :class:`ClipRead` to read the data.👈
    """

    clip_number: int  # Per-media sequence number (1, 2, 3, ...)
    url: str  # Source URL (used for dedup)
    title: str = ""  # Best-effort title from yt-dlp metadata
    file_name: str  # Final file name on disk
    path: str  # Absolute final file path
    size: int  # Size in bytes
    duration: int = 0  # Duration in seconds
    resolution: int = 0  # Height, e.g. 1080 (0 if unknown)
    file_format: str  # Container, e.g. "mp4"
    source: str = "unknown"  # yt-dlp extractor, e.g. "tiktok", "youtube"
    source_id: str = "unknown"  # Best-effort source video id
    uploader: str = "unknown"  # Best-effort uploader/channel/author
    file_exists: bool = True
    downloaded_at: datetime


class Clip(ClipBase, table=True):
    """
    Database model for Clip.\n
    Note: \n
        🚨DO NOT USE THIS CLASS OUTSIDE OF DATABASE MANAGER.🚨 \n
    👉Use :class:`ClipCreate` to create clips.👈 \n
    👉Use :class:`ClipRead` to read the data.👈
    """

    id: int | None = Field(default=None, primary_key=True)
    media_id: int = Field(foreign_key="media.id", ondelete="CASCADE")

    @field_validator("downloaded_at", mode="after")
    @classmethod
    def update_to_utc_to_save(cls, value: datetime) -> datetime:
        return cls.convert_to_utc(value)


class ClipCreate(ClipBase):
    """
    Model for creating a Clip.
    """

    id: int | None = None
    media_id: int


class ClipRead(ClipBase):
    """
    Model for reading a Clip.
    """

    id: int
    media_id: int

    @field_validator("downloaded_at", mode="after")
    @classmethod
    def correct_timezone_after_read(cls, value: datetime) -> datetime:
        return cls.set_timezone_to_utc(value)
