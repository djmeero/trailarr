from sqlmodel import Session

from . import base
from core.base.database.models.clip import ClipRead
from core.base.database.utils.engine import write_session


@write_session
def mark_as_deleted(
    id: int,
    *,
    _session: Session = None,  # type: ignore
) -> ClipRead:
    """Mark a clip's file as no longer existing on disk.
    Raises:
        ItemNotFoundError: If the clip with the given id does not exist.
    """
    db_clip = base._get_db_item(id, _session)
    db_clip.file_exists = False
    _session.add(db_clip)
    _session.commit()
    _session.refresh(db_clip)
    return base.convert_to_read_item(db_clip)
