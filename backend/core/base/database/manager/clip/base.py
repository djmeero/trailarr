from typing import Sequence

from sqlmodel import Session

from core.base.database.models.clip import Clip, ClipRead
from exceptions import ItemNotFoundError


def convert_to_read_item(db_clip: Clip) -> ClipRead:
    """Convert a Clip database object to a ClipRead object."""
    return ClipRead.model_validate(db_clip)


def convert_to_read_list(db_clips: Sequence[Clip]) -> list[ClipRead]:
    """Convert a list of Clip database objects to a list of ClipRead."""
    if not db_clips:
        return []
    return [ClipRead.model_validate(c) for c in db_clips]


def _get_db_item(clip_id: int, session: Session) -> Clip:
    """Get a Clip database object by ID.
    Raises:
        ItemNotFoundError: If the Clip with the given ID is not found.
    """
    db_clip = session.get(Clip, clip_id)
    if db_clip is None:
        raise ItemNotFoundError(model_name="Clip", id=clip_id)
    return db_clip
