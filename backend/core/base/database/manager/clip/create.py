from sqlmodel import Session

from . import base
from core.base.database.models.clip import Clip, ClipCreate, ClipRead
from core.base.database.utils.engine import write_session


@write_session
def create(
    clip_create: ClipCreate,
    *,
    _session: Session = None,  # type: ignore
) -> ClipRead:
    """
    Create a new clip.
    Args:
        clip_create (ClipCreate): ClipCreate model
        _session (Session, optional=None): A session to use for the \
            database connection. A new session is created if not provided.
    Returns:
        ClipRead: ClipRead object
    Raises:
        ValidationError: If the input data is not valid.
    """
    db_clip = Clip.model_validate(clip_create)
    _session.add(db_clip)
    _session.commit()
    _session.refresh(db_clip)
    return base.convert_to_read_item(db_clip)
