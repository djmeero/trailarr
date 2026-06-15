import {DatePipe} from '@angular/common';
import {ChangeDetectionStrategy, Component, effect, inject, input, signal} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {takeUntilDestroyed} from '@angular/core/rxjs-interop';
import {catchError, of} from 'rxjs';
import {DurationSecondsConvertPipe} from 'src/app/helpers/duration-seconds-pipe';
import {FileSizePipe} from 'src/app/helpers/file-size.pipe';
import {PlayVideoDialogComponent} from 'src/app/media/media-details/files/dialogs/play-video-dialog/play-video-dialog.component';
import {Clip} from 'src/app/models/clip';
import {ClipsService} from 'src/app/services/clips.service';
import {WebsocketService} from 'src/app/services/websocket.service';

@Component({
  selector: 'media-clips',
  imports: [DatePipe, DurationSecondsConvertPipe, FileSizePipe, FormsModule, PlayVideoDialogComponent],
  templateUrl: './clips.component.html',
  styleUrl: './clips.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClipsComponent {
  private readonly clipsService = inject(ClipsService);
  private readonly webSocketService = inject(WebsocketService);

  mediaId = input.required<number>();

  readonly clips = signal<Clip[]>([]);
  readonly isLoading = signal<boolean>(false);
  readonly isDownloading = signal<boolean>(false);
  /** Path of the clip currently being played (null = player closed). */
  readonly playingPath = signal<string | null>(null);
  clipUrl = '';

  constructor() {
    // Reload clips whenever the media id changes
    effect(() => {
      const id = this.mediaId();
      if (id) {
        this.loadClips(id);
      }
    });

    // Refresh the list when the backend broadcasts a media reload (e.g. after
    // a clip finishes downloading in the background).
    this.webSocketService.toastMessage.pipe(takeUntilDestroyed()).subscribe((msg) => {
      if (msg.reload?.includes('media') && this.mediaId()) {
        this.loadClips(this.mediaId());
      }
    });
  }

  private loadClips(mediaId: number): void {
    this.isLoading.set(true);
    this.clipsService
      .getMediaClips(mediaId)
      .then((clips) => this.clips.set(clips))
      .catch(() => this.clips.set([]))
      .finally(() => this.isLoading.set(false));
  }

  downloadClip(): void {
    const url = this.clipUrl.trim();
    if (!url) {
      this.webSocketService.showToast('Please paste a clip URL first.', 'Error');
      return;
    }
    this.isDownloading.set(true);
    this.clipsService
      .downloadClip(this.mediaId(), url)
      .pipe(
        catchError((error) => {
          this.webSocketService.showToast(error?.error?.detail || 'Failed to start clip download.', 'Error');
          this.isDownloading.set(false);
          return of(null);
        }),
      )
      .subscribe((res) => {
        if (res !== null) {
          this.webSocketService.showToast('Clip download started in background.');
          this.clipUrl = '';
        }
        this.isDownloading.set(false);
      });
  }

  playClip(clip: Clip): void {
    this.playingPath.set(clip.path);
  }

  deleteClip(clip: Clip): void {
    if (!confirm(`Delete clip "${clip.file_name}"? This removes the file from disk.`)) {
      return;
    }
    this.clipsService
      .deleteClip(clip.id)
      .pipe(
        catchError((error) => {
          this.webSocketService.showToast(error?.error?.detail || 'Failed to delete clip.', 'Error');
          return of(null);
        }),
      )
      .subscribe((res) => {
        if (res !== null) {
          this.webSocketService.showToast('Clip deleted.');
          this.clips.update((list) => list.filter((c) => c.id !== clip.id));
        }
      });
  }
}
