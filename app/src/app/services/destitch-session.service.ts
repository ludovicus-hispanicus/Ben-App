import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

/**
 * Cross-tab state for the Segmentation feature.
 *
 * When a user picks a dataset on the Datasets tab and clicks "Open in Batch",
 * we publish the source folder path here. The BatchDestitchComponent
 * subscribes on init and prefills its source folder picker.
 */
@Injectable({ providedIn: 'root' })
export class DestitchSessionService {
  private readonly _prefilledSource$ = new BehaviorSubject<string | null>(null);
  readonly prefilledSource$ = this._prefilledSource$.asObservable();

  setPrefilledSource(path: string): void {
    this._prefilledSource$.next(path);
  }

  consumePrefilledSource(): string | null {
    const value = this._prefilledSource$.value;
    if (value !== null) {
      this._prefilledSource$.next(null);
    }
    return value;
  }
}
