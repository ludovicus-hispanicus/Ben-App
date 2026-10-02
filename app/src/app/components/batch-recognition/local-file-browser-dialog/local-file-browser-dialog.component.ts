import { Component, Inject, OnInit } from '@angular/core';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { BatchRecognitionService } from '../../../services/batch-recognition.service';
import { LocalFolderInfo } from '../../../models/batch-recognition';
import { rangeToggle } from './range-toggle';

/** What the user ticked: absolute paths of whole folders and of individual image files. */
export interface LocalBrowseResult {
  folders: string[];
  files: string[];
}

const LAST_PATH_KEY = 'batch_browse_computer_last_path';

/**
 * "Browse Computer": one window to tick any mix of folders and image files on this
 * computer (native Windows dialogs can't select both at once). Ticks survive
 * navigation, so files can be gathered from several folders in one go.
 * Uses the backend's /browse-local listing, so it works the same in dev and desktop.
 */
@Component({
  selector: 'app-local-file-browser-dialog',
  templateUrl: './local-file-browser-dialog.component.html',
  styleUrls: ['./local-file-browser-dialog.component.scss'],
})
export class LocalFileBrowserDialogComponent implements OnInit {
  info: LocalFolderInfo | null = null;
  pathInput = '';
  loading = false;
  filter = '';

  /** Ticked items, keyed by absolute path. */
  selectedFolders = new Set<string>();
  selectedFiles = new Set<string>();

  /** Last clicked folder / file (absolute paths): anchors for Shift+click ranges. */
  private folderAnchor: string | null = null;
  private fileAnchor: string | null = null;

  constructor(
    private dialogRef: MatDialogRef<LocalFileBrowserDialogComponent, LocalBrowseResult>,
    private batchService: BatchRecognitionService,
    @Inject(MAT_DIALOG_DATA) public data: { startPath?: string } | null,
  ) {}

  ngOnInit(): void {
    let last = '';
    try { last = localStorage.getItem(LAST_PATH_KEY) || ''; } catch { /* storage unavailable */ }
    this.open(this.data?.startPath || last);
  }

  open(path: string): void {
    this.loading = true;
    this.filter = '';
    this.folderAnchor = this.fileAnchor = null;
    this.batchService.browseLocalFolder(path || undefined).subscribe({
      next: (info) => {
        this.loading = false;
        if (info.error && path) {
          // Unreadable / vanished folder: fall back to the home folder
          this.open('');
          return;
        }
        this.info = info;
        this.pathInput = info.path;
        try { localStorage.setItem(LAST_PATH_KEY, info.path); } catch { /* ignore */ }
      },
      error: () => { this.loading = false; },
    });
  }

  goUp(): void {
    if (this.info?.parent) { this.open(this.info.parent); }
  }

  get separator(): string {
    return this.info && this.info.path.includes('\\') ? '\\' : '/';
  }

  filePath(name: string): string {
    const base = this.info ? this.info.path : '';
    return base.endsWith(this.separator) ? base + name : base + this.separator + name;
  }

  get visibleFolders() {
    const folders = this.info?.folders || [];
    const q = this.filter.toLowerCase();
    return q ? folders.filter(f => f.name.toLowerCase().includes(q)) : folders;
  }

  get visibleFiles(): string[] {
    const files = this.info?.image_files || [];
    const q = this.filter.toLowerCase();
    return q ? files.filter(f => f.toLowerCase().includes(q)) : files;
  }

  toggleFolder(path: string, event?: MouseEvent): void {
    // Only folders with images can be ticked
    const folders = this.visibleFolders.filter(f => f.image_count).map(f => f.path);
    this.folderAnchor = rangeToggle(folders, path, this.folderAnchor, !!event?.shiftKey, this.selectedFolders);
  }

  toggleFile(name: string, event?: MouseEvent): void {
    const files = this.visibleFiles.map(f => this.filePath(f));
    this.fileAnchor = rangeToggle(files, this.filePath(name), this.fileAnchor, !!event?.shiftKey, this.selectedFiles);
  }

  isFileSelected(name: string): boolean {
    return this.selectedFiles.has(this.filePath(name));
  }

  /** Tick / untick every visible image in the current folder. */
  get allVisibleFilesSelected(): boolean {
    const files = this.visibleFiles;
    return files.length > 0 && files.every(f => this.isFileSelected(f));
  }

  toggleAllVisibleFiles(): void {
    const select = !this.allVisibleFilesSelected;
    for (const f of this.visibleFiles) {
      const p = this.filePath(f);
      select ? this.selectedFiles.add(p) : this.selectedFiles.delete(p);
    }
  }

  /** Tick the folder being viewed as a whole. */
  get currentFolderSelected(): boolean {
    return !!this.info && this.selectedFolders.has(this.info.path);
  }

  toggleCurrentFolder(): void {
    const path = this.info?.path;
    if (path) {
      this.selectedFolders.has(path) ? this.selectedFolders.delete(path) : this.selectedFolders.add(path);
    }
  }

  get selectionCount(): number {
    return this.selectedFolders.size + this.selectedFiles.size;
  }

  get selectionSummary(): string {
    const parts: string[] = [];
    if (this.selectedFolders.size) {
      parts.push(`${this.selectedFolders.size} folder${this.selectedFolders.size === 1 ? '' : 's'}`);
    }
    if (this.selectedFiles.size) {
      parts.push(`${this.selectedFiles.size} file${this.selectedFiles.size === 1 ? '' : 's'}`);
    }
    return parts.length ? parts.join(' + ') + ' selected' : 'Nothing selected';
  }

  clearSelection(): void {
    this.selectedFolders.clear();
    this.selectedFiles.clear();
  }

  cancel(): void {
    this.dialogRef.close();
  }

  confirm(): void {
    this.dialogRef.close({
      folders: Array.from(this.selectedFolders),
      files: Array.from(this.selectedFiles),
    });
  }
}
