import {DatePipe} from '@angular/common';
import {ChangeDetectionStrategy, Component, computed, inject, OnInit, signal} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {takeUntilDestroyed} from '@angular/core/rxjs-interop';
import {ActivatedRoute, Router, RouterLink} from '@angular/router';
import {catchError, of, take} from 'rxjs';
import {DurationSecondsConvertPipe} from 'src/app/helpers/duration-seconds-pipe';
import {FileSizePipe} from 'src/app/helpers/file-size.pipe';
import {Clip} from 'src/app/models/clip';
import {ClipsService} from 'src/app/services/clips.service';
import {MediaService} from 'src/app/services/media.service';
import {WebsocketService} from 'src/app/services/websocket.service';
import {RouteMedia} from 'src/routing';

const SEARCH_STORAGE_KEY = 'TrailarrClipsSearch';

@Component({
  selector: 'app-clips',
  imports: [DatePipe, DurationSecondsConvertPipe, FileSizePipe, FormsModule, RouterLink],
  templateUrl: './clips.component.html',
  styleUrl: './clips.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClipsComponent implements OnInit {
  private readonly clipsService = inject(ClipsService);
  private readonly mediaService = inject(MediaService);
  private readonly webSocketService = inject(WebsocketService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  RouteMedia = RouteMedia;

  readonly clips = signal<Clip[]>([]);
  readonly isLoading = signal<boolean>(false);
  readonly search = signal<string>('');

  /** Map of media_id -> "Title (year)" for labelling clips by movie. */
  readonly mediaTitles = computed(() => {
    const map = new Map<number, string>();
    for (const m of this.mediaService.combinedMedia()) {
      map.set(m.id, m.year ? `${m.title} (${m.year})` : m.title);
    }
    return map;
  });

  readonly filteredClips = computed(() => {
    const term = this.search().trim().toLowerCase();
    const titles = this.mediaTitles();
    const all = this.clips();
    if (!term) return all;
    return all.filter((c) => {
      const title = (titles.get(c.media_id) || '').toLowerCase();
      return c.file_name.toLowerCase().includes(term) || c.source.toLowerCase().includes(term) || title.includes(term);
    });
  });

  constructor() {
    // Refresh when the backend broadcasts a media reload (clip finished).
    this.webSocketService.toastMessage.pipe(takeUntilDestroyed()).subscribe((msg) => {
      if (msg.reload?.includes('media')) {
        this.loadClips();
      }
    });
  }

  ngOnInit(): void {
    // Priority: localStorage (low) -> URL params (high)
    const stored = localStorage.getItem(SEARCH_STORAGE_KEY);
    if (stored) this.search.set(stored);
    this.route.queryParams.pipe(take(1)).subscribe((params) => {
      if (params['search']) this.search.set(params['search']);
    });
    this.loadClips();
  }

  loadClips(): void {
    this.isLoading.set(true);
    this.clipsService
      .getAllClips()
      .then((clips) => this.clips.set(clips))
      .catch(() => this.clips.set([]))
      .finally(() => this.isLoading.set(false));
  }

  onSearchChange(value: string): void {
    this.search.set(value);
    const term = value.trim();
    localStorage.setItem(SEARCH_STORAGE_KEY, term);
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {search: term || null},
      replaceUrl: true,
    });
  }

  mediaTitle(mediaId: number): string {
    return this.mediaTitles().get(mediaId) || `Media #${mediaId}`;
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
