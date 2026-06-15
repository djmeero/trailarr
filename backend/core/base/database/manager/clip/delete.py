from sqlmodel import Session, select

from . import base
from core.base.database.models.clip import Clip
from core.base.database.utils.engine import write_session


@write_session
def delete(id: int, *, _session: Session = None) -> bool:  # type: ignore
    """
    Delete a clip by id.
    Raises:
        ItemNotFoundError: If the clip with the given id does not exist.
    """
    db_clip = base._get_db_item(id, _session)
    _session.delete(db_clip)
    _session.commit()
    return True


@write_session
def delete_all_for_media(
    media_id: int,
    *,
    _session: Session = None,  # type: ignore
) -> int:
    """Delete all clips for a specific media item.
    Returns:
        int: Number of clips deleted.
    """
    statement = select(Clip).where(Clip.media_id == media_id)
    clips = _session.exec(statement).all()
    count = len(clips)
    for clip in clips:
        _session.delete(clip)
    _session.commit()
    return count
