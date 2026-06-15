# Clips Feature — Design Spec

**Date:** 2026-06-15
**Status:** Approved (pending spec review)
**Origin:** Integrating the standalone `make-clips.ps1` script's capability into Trailarr as a first-class feature.

## Summary

Add a **Clips** feature to Trailarr: the ability to download arbitrary video clips from
user-pasted URLs and associate each clip with a specific media item (movie or series).
URLs may come from **any source yt-dlp supports** — TikTok, Instagram Reels, YouTube
(Shorts or regular videos), etc. — not just YouTube; yt-dlp handles site detection
natively, so no per-site code is needed.
Clips are downloaded *as-is* (native format/resolution, no transcode or vertical crop),
stored in a central configurable directory, named after the media item with an
incrementing per-item number, and tracked in Trailarr's database so the UI can show
which items have clips and how many — mirroring how trailer status is surfaced today.

This reuses Trailarr's existing yt-dlp/ffmpeg infrastructure and background-task
execution model. It does **not** modify the existing trailer pipeline.

### What `make-clips.ps1` did (for reference)

- Read a `clips.txt` of title lines followed by URL lines (grouped by title).
- Downloaded each URL via yt-dlp, transcoded to vertical 1080×1920 H.264 with
  loudness-normalized audio, rejected non-vertical sources.
- Named files `<title> - <N>.mp4` in a flat `C:\clips` dir for Jellyfin.
- Was resume-safe via a `downloads.txt` state file of completed URLs.

### What changes for Trailarr

| Aspect | Script | Trailarr Clips feature |
|---|---|---|
| Input | `clips.txt` batch | One URL pasted manually in the UI |
| Grouping label | Freeform title | An actual media item (`media_id`) |
| Processing | Forced vertical transcode + loudnorm | **Download as-is** (no crop/re-encode) |
| Output location | Flat `C:\clips` | Central configurable `clips_dir` |
| Naming | `<title> - <N>.mp4` | `<Media title (year)> - <N>.mp4` |
| Resume safety | `downloads.txt` | DB dedup on `(media_id, url)` |
| Evidence | Files on disk | DB-tracked, shown per-item + global page |

## Goals

- Download a clip from a manually pasted URL (any yt-dlp-supported source: TikTok,
  Instagram Reels, YouTube, etc.), attached to a chosen media item.
- Store clips in a central, configurable directory.
- Name clips `<Media title (year)> - <N>.mp4` with `N` incrementing per media item.
- Track clips in the DB so the media detail page shows clip count/evidence (like trailers).
- Provide a global Clips page to list/manage all clips.
- Reuse existing yt-dlp/ffmpeg infra, settings (ffmpeg path, cookies), and the
  background-task execution model.

## Non-Goals (YAGNI)

- No vertical 1080×1920 transcode / loudnorm / aspect-ratio rejection (download as-is).
- No batch/`clips.txt` ingestion — one URL at a time via the UI.
- No automatic clip discovery/search (URLs are user-provided).
- No per-clip processing profile (unlike `TrailerProfile`). Clips are downloaded as-is.
- No Plex/Jellyfin "extras" association (clips live outside the media folder by design).

## Architecture

Follows the existing Trailarr layering. New pieces, with the trailer-equivalent they mirror:

| New piece | Mirrors |
|---|---|
| `models/clip.py` (`Clip`, `ClipCreate`, `ClipRead`) | `models/download.py` |
| `manager/clip.py` (DB access) | `manager/download.py` |
| `core/download/clip.py` (download + probe + file move) | `core/download/trailer.py` + `video_v2.py` |
| `core/tasks/download_clips.py` (`download_clip_by_id`) | `core/tasks/download_trailers.py` |
| `api/v1/clips.py` (routes) | trailer routes in `api/v1/media.py` |
| Frontend Clips page + media-detail Clips section | trailer/downloads UI |

### Data model — `Clip`

New dedicated table (decision: a clean `Clip` table over reusing `Download`, to keep the
trailer pipeline untouched). Mirrors `DownloadBase` field conventions.

Fields:
- `id` — PK
- `media_id` — FK → `media.id`, `ondelete="CASCADE"`
- `clip_number` — int, per-media sequence (1, 2, 3…)
- `url` — source URL (used for dedup)
- `title` — clip title (best-effort from yt-dlp metadata; falls back to file base name)
- `file_name` — final file name on disk
- `path` — absolute final file path
- `size` — bytes
- `duration` — seconds (from ffprobe)
- `resolution` — int height, e.g. 1080 (from ffprobe; 0 if unknown)
- `file_format` — container, e.g. `mp4`
- `source` — yt-dlp extractor / site, e.g. `youtube`, `tiktok`, `instagram` (default `unknown`)
- `source_id` — best-effort source video id from yt-dlp (default `unknown`)
- `uploader` — best-effort uploader/channel/author from yt-dlp (default `unknown`)
- `file_exists` — bool, default True
- `downloaded_at` — datetime (UTC, validators like `Download`)

Read/Create variants (`ClipRead`, `ClipCreate`) follow the `Download` pattern.

### Storage & naming

- New setting **`clips_dir`** in `config/settings.py`, persisted to `.env` in `APP_DATA_DIR`.
  Default: `<APP_DATA_DIR>/clips`. User-configurable in Settings UI.
- Final path: `<clips_dir>/<clean media title (year)> - <N>.mp4`
- `clean` = media title sanitized with `[\\/:*?"<>|] → _` (same as the script).
- The `(year)` suffix is included when the media has a year; format matches existing
  Trailarr title/year display.
- `N` = `max(clip_number for media_id) + 1`, computed from the DB (not the filesystem).

### Download pipeline

`core/download/clip.py` — `download_clip(media, url, _stop_event=None) -> ClipRead`:

1. Dedup guard: if a `Clip` with this `(media_id, url)` exists, skip (return existing / no-op).
2. Compute next `clip_number` and final path.
3. Download to a temp file in `tempfile.gettempdir()/trailarr` via yt-dlp:
   - yt-dlp natively detects the source site (TikTok, Instagram Reels, YouTube, …) from
     the URL — no per-site handling required.
   - Reuses `app_settings.ffmpeg_path` and `app_settings.yt_cookies_path` (cookies file),
     consistent with `_get_ytdl_options`. The same cookies file covers sites that require
     auth (e.g. some TikTok/Instagram URLs).
   - Format: `-f b/best`, `--merge-output-format mp4` (or `--remux-video mp4`) — land an
     `.mp4` container with **no re-encode**. No vertical filter, no loudnorm. (TikTok is
     usually already h264/mp4; for sources whose codecs can't be remuxed into mp4
     losslessly, fall back to the native container extension rather than force a re-encode.)
   - Capture source metadata from the yt-dlp info dict: `extractor` → `source`,
     `id` → `source_id`, `uploader`/`channel` → `uploader` (all best-effort).
   - `--no-playlist`, `--restrict-filenames`, retries, `--force-overwrites` as in existing infra.
4. ffprobe the result for `duration`, `resolution`, `size`.
5. Move temp file → final path; create `clips_dir` if missing.
6. Insert `Clip` record; fire `CLIP_DOWNLOADED` event.
7. Broadcast success/failure over the existing WebSocket (`ws_manager.broadcast`).

Execution model mirrors `download_trailer_by_id`:
`core/tasks/download_clips.py::download_clip_by_id(media_id, url)` validates the media,
then `scheduler.add_task(run_once=True, delay=1, ...)` to run the download in the
background and returns a status message immediately.

### Events

- Add `CLIP_DOWNLOADED` to `EventType` in `models/event.py`.
  `EventType` is stored as VARCHAR (`native_enum=False`) → **no Alembic migration** for this.
- Add `track_clip_downloaded` helper in `manager/event/helpers.py` (mirrors
  `track_trailer_downloaded`).

### API (`api/v1/clips.py`)

- `POST /api/v1/media/{media_id}/clips` body `{ url }` → enqueue download, return message.
  - Validates media exists.
- `GET /api/v1/media/{media_id}/clips` → `list[ClipRead]` for one item.
- `GET /api/v1/clips` → global list for the Clips page (search/paginate as needed).
- `DELETE /api/v1/clips/{clip_id}` → delete the DB record **and** the file on disk.
- Regenerate the OpenAPI client after adding routes (project convention).

### Frontend (Angular, standalone + Signals + MD3 tokens)

- **Media detail page:** a "Clips" section alongside the existing trailer/downloads area:
  - Count badge ("3 clips") as evidence, like trailer status.
  - List of clips (name, duration/size, open file, delete).
  - A "Download clip" input to paste a URL + button → calls the POST endpoint; media_id implicit.
- **Global Clips page:** new lazy route in `app.routes.ts` + nav item:
  - Lists all clips across media (search by movie title, open file, delete).
  - Reuses existing list/card components and MD3 styling conventions (sticky header, cards,
    button shapes, etc. per CLAUDE.md).
- New typed service wrapper in `services/` using the regenerated client.

### Settings

- `clips_dir` surfaced in the Settings UI (path input), with the same validation/persistence
  pattern as other directory settings.

## Error Handling

- yt-dlp failure (sign-in/bot detection, network, bad/unsupported URL, login-walled
  TikTok/Instagram post): surface a clear error message over WebSocket and in logs; no
  `Clip` record created. Mirrors `_download_with_ytdlp` error parsing. Sites that require
  auth are handled via the existing cookies file (`yt_cookies_path`).
- ffprobe failure: still save the clip but with `resolution=0`/`duration=0` (best-effort metadata).
- Duplicate `(media_id, url)`: skip with an informational message.
- `clips_dir` not writable / missing: create it; if creation fails, error out clearly.
- Deleting a clip whose file is already gone: remove the DB record anyway, mark/log.

## Testing

Backend (pytest, mirroring existing trailer/download tests):
- Per-media `clip_number` increments correctly; independent across media items.
- Title sanitization (`[\\/:*?"<>|] → _`) and `(year)` inclusion.
- Dedup skip on `(media_id, url)`.
- Final path construction against `clips_dir`.
- Task enqueue path (`download_clip_by_id` validates media, schedules job).
- Delete removes both record and file.

Frontend:
- Clips service wrapper.
- Media-detail Clips section (count badge, download input).
- Global Clips page list/delete.

## Migration

- One Alembic migration: create `clip` table (autogenerated, reviewed).
- No migration for the new `EventType` value (VARCHAR enum).

## Open Items / Follow-ups

- After implementation, per CLAUDE.md: ask whether to add release notes
  (`docs/release-notes/2026.md`) and whether any docs pages need updating.

## Decisions (confirmed with user)

1. New dedicated `Clip` table (not reusing `Download`).
2. Clips work for **any media** (Sonarr series too), not just movies.
3. Deleting a clip removes the file from disk as well.
4. Download as-is — no vertical transcode/loudnorm.
5. Central configurable `clips_dir` storage.
6. Both per-item (media detail) and global Clips page UI.
7. Multi-source: any yt-dlp-supported site (TikTok, Instagram Reels, YouTube, …); model
   fields are source-agnostic (`source`/`source_id`/`uploader`, not YouTube-specific).
