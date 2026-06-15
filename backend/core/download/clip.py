import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from api.v1 import websockets
from app_logger import ModuleLogger
import core.base.database.manager.clip as clip_manager
import core.base.database.manager.event as event_manager
from config.settings import app_settings
from core.base.database.models.clip import ClipCreate, ClipRead
from core.base.database.models.event import EventSource
from core.base.database.models.media import MediaRead
from exceptions import DownloadFailedError

logger = ModuleLogger("ClipsDownloader")

YTDLP_TIMEOUT = 900  # 15 minutes

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


# -------------------------------------------------------------------
# URL validation
# -------------------------------------------------------------------


def is_valid_clip_url(url: str) -> bool:
    """Return True only for well-formed http(s) URLs.

    This guards against argv flag smuggling: yt-dlp treats a leading-dash
    positional argument (e.g. ``--exec=...``) as an option, so a hostile
    "URL" could otherwise inject dangerous yt-dlp flags. Restricting to an
    http(s) scheme with a host rejects those before they ever reach the
    subprocess. The download command additionally passes ``--`` before the
    URL as defence in depth.
    """
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


# -------------------------------------------------------------------
# Naming helpers
# -------------------------------------------------------------------


def sanitize_title(title: str) -> str:
    """Replace filesystem-illegal characters with underscores."""
    return _ILLEGAL.sub("_", title)


def resolve_clips_dir() -> str:
    """Return the configured clips dir, or <APP_DATA_DIR>/clips if unset."""
    configured = app_settings.clips_dir.strip()
    if configured:
        return configured
    return os.path.join(app_settings.app_data_dir, "clips")


def build_clip_path(
    clips_dir: str, title: str, year: int, number: int
) -> str:
    """Build the final clip file path: '<title (year)> - <n>.mp4'."""
    clean = sanitize_title(title)
    if year:
        base = f"{clean} ({year}) - {number}.mp4"
    else:
        base = f"{clean} - {number}.mp4"
    return os.path.join(clips_dir, base)


# -------------------------------------------------------------------
# Download + probe
# -------------------------------------------------------------------


def _build_ytdlp_error(result: subprocess.CompletedProcess) -> str:
    """Build a human-readable failure message from a failed yt-dlp run.

    Surfaces the actual ``ERROR:`` line yt-dlp printed (so the Tasks UI shows
    the real reason, not just "exit 1"), and gives a clear hint when the site
    requires authentication.
    """
    stderr = result.stderr or ""
    # The last "ERROR:" line is usually the most relevant.
    err_line = ""
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("ERROR:"):
            err_line = stripped[len("ERROR:"):].strip()

    low = stderr.lower()
    needs_auth = any(
        kw in low
        for kw in ("login", "log in", "sign in", "requiring login", "cookies")
    )
    if needs_auth:
        msg = (
            "This clip requires login. Add a yt-dlp cookies file (Settings →"
            " Yt-dlp Cookies Path, or the YT_COOKIES_PATH env var) for the"
            " source site and try again."
        )
        if err_line:
            msg += f" [{err_line}]"
        return msg
    if err_line:
        return f"yt-dlp error: {err_line}"
    return f"yt-dlp failed for clip: exit {result.returncode}"


def _download_clip_file(
    url: str,
    temp_out: str,
    _stop_event: threading.Event | None = None,
) -> dict:
    """Download the clip as-is via yt-dlp, remuxing to mp4 when possible.

    yt-dlp natively detects the source site (TikTok, Instagram Reels,
    YouTube, ...). No transcode/vertical crop is applied.

    Returns:
        dict: The yt-dlp info dict (best-effort; empty if unavailable).
    Raises:
        DownloadFailedError: If yt-dlp exits non-zero.
    """
    info_path = temp_out + ".info.json"
    cmd = [
        app_settings.ytdlp_path,
        "-f",
        "b/bestvideo+bestaudio/best",
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
        "--no-playlist",
        "--restrict-filenames",
        "--force-overwrites",
        "--no-warnings",
        "--write-info-json",
        "--ffmpeg-location",
        app_settings.ffmpeg_path,
        "-o",
        temp_out,
    ]
    if app_settings.yt_cookies_path:
        cmd += ["--cookies", app_settings.yt_cookies_path]
    # Terminate option parsing so the URL can never be read as a yt-dlp flag,
    # even if validation upstream is bypassed (defence in depth).
    cmd += ["--", url]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=YTDLP_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise DownloadFailedError("yt-dlp clip download timed out")

    if result.returncode != 0:
        out = (result.stdout or "") + (result.stderr or "")
        # Always log the full yt-dlp output so failures are diagnosable.
        logger.error(f"yt-dlp failed for clip ({url}):\n{out}")
        raise DownloadFailedError(_build_ytdlp_error(result), output=out)

    info: dict = {}
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        info = {}
    finally:
        try:
            os.remove(info_path)
        except OSError:
            pass
    return info


def _probe_clip(path: str) -> dict:
    """Return {'duration', 'resolution', 'size'} via ffprobe (best-effort)."""
    size = 0
    try:
        size = os.path.getsize(path)
    except OSError:
        pass
    duration = 0
    resolution = 0
    try:
        out = subprocess.run(
            [
                app_settings.ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=height:format=duration",
                "-of",
                "json",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        data = json.loads(out.stdout or "{}")
        streams = data.get("streams") or [{}]
        resolution = int(streams[0].get("height") or 0)
        duration = int(float(data.get("format", {}).get("duration") or 0))
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return {"duration": duration, "resolution": resolution, "size": size}


def _find_temp_output(temp_out: str) -> str | None:
    """yt-dlp may add/change the extension. Find the produced file."""
    directory = os.path.dirname(temp_out)
    stem = os.path.splitext(os.path.basename(temp_out))[0]
    if not os.path.isdir(directory):
        return None
    for f in os.listdir(directory):
        if f.startswith(stem) and not f.endswith(".info.json"):
            return os.path.join(directory, f)
    return None


# -------------------------------------------------------------------
# Orchestration
# -------------------------------------------------------------------


async def download_clip(
    media: MediaRead,
    url: str,
    _stop_event: threading.Event | None = None,
) -> ClipRead | None:
    """Download a clip for a media item from any yt-dlp-supported URL.

    Downloads as-is (no transcode), stores it in the central clips dir
    named '<Media title (year)> - <N>.mp4', records it in the DB, fires a
    CLIP_DOWNLOADED event and broadcasts over the WebSocket.

    Returns:
        ClipRead | None: The created clip, or None if it already existed.
    Raises:
        DownloadFailedError: If the URL is not a valid http(s) URL.
    """
    # 0. Reject anything that isn't a well-formed http(s) URL. Prevents argv
    #    flag smuggling into yt-dlp (e.g. a "--exec=..." pseudo-URL).
    if not is_valid_clip_url(url):
        raise DownloadFailedError(f"Invalid clip URL: {url!r}")

    # 1. Dedup guard
    existing = clip_manager.read_by_media_url(media.id, url)
    if existing is not None:
        logger.info(
            f"Clip already exists for media [{media.id}] url={url}, skipping"
        )
        return None

    # 2. Number + final path
    number = clip_manager.next_clip_number(media.id)
    clips_dir = resolve_clips_dir()
    os.makedirs(clips_dir, exist_ok=True)
    final_path = build_clip_path(clips_dir, media.title, media.year, number)

    # 3. Download to temp
    tmp_dir = Path(tempfile.gettempdir()) / "trailarr"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_out = str(tmp_dir / f"clip-{media.id}-{number}.mp4")
    try:
        info = _download_clip_file(url, temp_out, _stop_event=_stop_event)
        produced = _find_temp_output(temp_out) or temp_out
        if not os.path.exists(produced):
            raise DownloadFailedError("Clip file not produced by yt-dlp")

        # 4. Probe metadata (best-effort)
        meta = _probe_clip(produced)

        # 5. Move to final path (keep native extension if not mp4).
        #    Use shutil.move, not os.replace — the temp dir and the clips dir
        #    are often on different filesystems (e.g. /tmp vs a /media mount),
        #    and os.replace fails cross-device with "Invalid cross-device link".
        ext = os.path.splitext(produced)[1].lstrip(".").lower() or "mp4"
        if ext != "mp4":
            final_path = os.path.splitext(final_path)[0] + f".{ext}"
        if os.path.exists(final_path):
            os.remove(final_path)
        shutil.move(produced, final_path)

        # 6. Insert record
        clip_create = ClipCreate(
            media_id=media.id,
            clip_number=number,
            url=url,
            title=str(info.get("title") or os.path.basename(final_path)),
            file_name=os.path.basename(final_path),
            path=final_path,
            size=meta["size"],
            duration=meta["duration"],
            resolution=meta["resolution"],
            file_format=ext,
            source=str(info.get("extractor") or "unknown"),
            source_id=str(info.get("id") or "unknown"),
            uploader=str(
                info.get("uploader") or info.get("channel") or "unknown"
            ),
            downloaded_at=datetime.now(timezone.utc),
        )
        clip = clip_manager.create(clip_create)

        # 7. Event + broadcast
        event_manager.track_clip_downloaded(
            media_id=media.id,
            url=url,
            source=EventSource.USER,
            source_detail="ClipDownload",
        )
        msg = f"Clip downloaded for {media.title} [{media.id}]"
        logger.info(msg)
        await websockets.ws_manager.broadcast(msg, "Success", reload="media")
        return clip
    finally:
        # Clean up any stray temp files for this media/number
        for f in tmp_dir.glob(f"clip-{media.id}-{number}*"):
            try:
                f.unlink()
            except OSError:
                pass
