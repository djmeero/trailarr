from sqlmodel import Session, asc, desc, func, select

from . import base
from core.base.database.models.clip import Clip, ClipRead
from core.base.database.utils.engine import read_session


@read_session
def read(
    clip_id: int,
    *,
    _session: Session = None,  # type: ignore
) -> ClipRead:
    """
    Get a clip by ID.
    Raises:
        ItemNotFoundError: If the clip with the given ID is not found.
    """
    db_clip = base._get_db_item(clip_id, _session)
    return base.convert_to_read_item(db_clip)


@read_session
def read_all(
    *,
    _session: Session = None,  # type: ignore
) -> list[ClipRead]:
    """Get all clips ordered by most recently downloaded."""
    statement = select(Clip).order_by(desc(Clip.downloaded_at))
    return base.convert_to_read_list(_session.exec(statement).all())


@read_session
def read_by_media_id(
    media_id: int,
    *,
    _session: Session = None,  # type: ignore
) -> list[ClipRead]:
    """Get all clips for a specific media ID, ordered by clip number."""
    statement = (
        select(Clip)
        .where(Clip.media_id == media_id)
        .order_by(asc(Clip.clip_number))
    )
    return base.convert_to_read_list(_session.exec(statement).all())


@read_session
def read_by_media_url(
    media_id: int,
    url: str,
    *,
    _session: Session = None,  # type: ignore
) -> ClipRead | None:
    """Get a clip for a media item by its source URL (dedup helper).
    Returns:
        ClipRead | None: The clip if found, else None.
    """
    statement = select(Clip).where(
        Clip.media_id == media_id, Clip.url == url
    )
    db_clip = _session.exec(statement).first()
    return base.convert_to_read_item(db_clip) if db_clip else None


@read_session
def next_clip_number(
    media_id: int,
    *,
    _session: Session = None,  # type: ignore
) -> int:
    """Return the next per-media clip number (max existing + 1)."""
    statement = select(func.max(Clip.clip_number)).where(
        Clip.media_id == media_id
    )
    current_max = _session.exec(statement).one()
    return (current_max or 0) + 1


@read_session
def count_by_media_id(
    media_id: int,
    *,
    _session: Session = None,  # type: ignore
) -> int:
    """Return the number of clips for a media item."""
    statement = (
        select(func.count()).select_from(Clip).where(
            Clip.media_id == media_id
        )
    )
    return _session.exec(statement).one() or 0
