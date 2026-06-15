import threading

from app_logger import ModuleLogger
from config.logging_context import with_logging_context
import core.base.database.manager.media as media_manager
from core.base.database.models.media import MediaRead
from core.download.clip import download_clip, is_valid_clip_url
from core.tasks import scheduler
from exceptions import InvalidResponseError

logger = ModuleLogger("ClipDownloadTasks")


@with_logging_context
async def _download_clip(
    media: MediaRead,
    url: str,
    *,
    _job_id: str | None = None,
    _stop_event: threading.Event | None = None,
) -> None:
    """Run the async clip download in a scheduled job."""
    await download_clip(media, url, _stop_event=_stop_event)
    return


def download_clip_by_id(media_id: int, url: str) -> str:
    """Validate the media + URL and schedule a background clip download.

    Args:
        media_id (int): The ID of the media to attach the clip to.
        url (str): The source URL to download the clip from.
    Returns:
        str: Message indicating the download has been scheduled.
    Raises:
        InvalidResponseError: If the URL is empty.
        ItemNotFoundError: If the media with the given ID is not found.
    """
    url = (url or "").strip()
    if not url:
        raise InvalidResponseError("A clip URL is required")
    # Reject non-http(s) URLs before scheduling — prevents argv flag smuggling
    # into yt-dlp (e.g. a "--exec=..." pseudo-URL).
    if not is_valid_clip_url(url):
        raise InvalidResponseError("A valid http(s) clip URL is required")

    # Raises ItemNotFoundError if the media does not exist
    media = media_manager.read(media_id)
    _type = "Movie" if media.is_movie else "Series"

    scheduler.add_task(
        task_name=f"Download Clip for {media.title}",
        func=_download_clip,
        interval=86400.0,
        delay=1,
        run_once=True,
        args=(media, url),
    )
    msg = (
        "Clip download started in background for "
        f"{_type}: '{media.title}' [{media_id}]"
    )
    logger.info(msg)
    return msg
