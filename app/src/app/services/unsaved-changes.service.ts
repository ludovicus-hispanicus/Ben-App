import { Injectable } from '@angular/core';

/**
 * Tracks whether the open editor has unsaved changes, so every way of leaving
 * it (back button, breadcrumb, top navigation, route change) asks the same
 * question before discarding them.
 */
@Injectable({ providedIn: 'root' })
export class UnsavedChangesService {
  hasUnsavedChanges = false;

  /** True when it is fine to leave: nothing unsaved, or the user agreed to discard. */
  confirmDiscard(): boolean {
    if (!this.hasUnsavedChanges) {
      return true;
    }
    if (!confirm('You have unsaved changes. Discard them?')) {
      return false;
    }
    this.hasUnsavedChanges = false;
    return true;
  }
}
