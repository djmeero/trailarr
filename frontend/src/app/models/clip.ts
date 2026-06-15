export interface Clip {
  id: number;
  media_id: number;
  clip_number: number;
  url: string;
  title: string;
  file_name: string;
  path: string;
  size: number;
  duration: number;
  resolution: number;
  file_format: string;
  source: string;
  source_id: string;
  uploader: string;
  file_exists: boolean;
  downloaded_at: string;
}

/** Map a raw API clip object to a typed Clip. */
export function mapClip(raw: any): Clip {
  return {
    id: raw.id,
    media_id: raw.media_id,
    clip_number: raw.clip_number,
    url: raw.url ?? '',
    title: raw.title ?? '',
    file_name: raw.file_name ?? '',
    path: raw.path ?? '',
    size: raw.size ?? 0,
    duration: raw.duration ?? 0,
    resolution: raw.resolution ?? 0,
    file_format: raw.file_format ?? '',
    source: raw.source ?? 'unknown',
    source_id: raw.source_id ?? 'unknown',
    uploader: raw.uploader ?? 'unknown',
    file_exists: raw.file_exists ?? true,
    downloaded_at: raw.downloaded_at ?? '',
  };
}
