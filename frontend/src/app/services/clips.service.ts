import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {firstValueFrom, Observable} from 'rxjs';
import {environment} from '../../environment';
import {Clip, mapClip} from '../models/clip';

@Injectable({
  providedIn: 'root',
})
export class ClipsService {
  private readonly httpClient = inject(HttpClient);

  private readonly clipsUrl = environment.apiUrl + environment.clips;
  private readonly mediaUrl = environment.apiUrl + environment.media;

  /** Get all clips for a single media item. */
  async getMediaClips(mediaID: number): Promise<Clip[]> {
    const url = `${this.mediaUrl}${mediaID}/clips`;
    const clips = await firstValueFrom(this.httpClient.get<any[]>(url));
    return Array.isArray(clips) ? clips.map(mapClip) : [];
  }

  /** Get all clips across all media (for the global Clips page). */
  async getAllClips(): Promise<Clip[]> {
    const clips = await firstValueFrom(this.httpClient.get<any[]>(this.clipsUrl));
    return Array.isArray(clips) ? clips.map(mapClip) : [];
  }

  /** Schedule a background clip download for a media item from a pasted URL. */
  downloadClip(mediaID: number, url: string): Observable<any> {
    const endpoint = `${this.mediaUrl}${mediaID}/clips`;
    return this.httpClient.post(endpoint, {url});
  }

  /** Delete a clip record and its file on disk. */
  deleteClip(clipID: number): Observable<any> {
    const url = `${this.clipsUrl}${clipID}`;
    return this.httpClient.delete(url);
  }
}
