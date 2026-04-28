import { Injectable } from '@angular/core';

/**
 * Holds a File picked in production (via the "Add new linked page" dialog) so it can
 * be consumed by CuReD on the next route hop. Avoids serialising large image data
 * through query params or sessionStorage.
 */
@Injectable({ providedIn: 'root' })
export class LinkedPageService {
  private pendingFile: File | null = null;
  // Last source the user picked in the Add-text dialog (preserved across the
  // "Add another" flow so we can re-open the same picker without showing the
  // dialog or the in-CuReD source-picker card again).
  lastSource: 'local' | 'server' | null = null;
  // Dataset that the linked text should be saved to (so it joins the same
  // folder as the existing sources of the production text being edited).
  linkedDatasetId: number | null = null;

  setPendingFile(file: File): void {
    this.pendingFile = file;
  }

  consumePendingFile(): File | null {
    const file = this.pendingFile;
    this.pendingFile = null;
    return file;
  }

  hasPendingFile(): boolean {
    return this.pendingFile !== null;
  }

  clear(): void {
    this.pendingFile = null;
    this.lastSource = null;
    this.linkedDatasetId = null;
  }
}
