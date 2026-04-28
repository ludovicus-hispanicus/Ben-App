import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription, interval } from 'rxjs';
import { startWith, switchMap } from 'rxjs/operators';

import { DestitchService } from '../../services/destitch.service';
import { DestitchSessionService } from '../../services/destitch-session.service';
import {
  DestitchBatchJobSummary,
  DestitchBatchStatus,
  LocalFolderInfo,
} from '../../models/destitch';

type FolderPickerTarget = 'source' | 'destination';

@Component({
  selector: 'app-batch-destitch',
  templateUrl: './batch-destitch.component.html',
  styleUrls: ['./batch-destitch.component.scss'],
})
export class BatchDestitchComponent implements OnInit, OnDestroy {

  // Configuration ────────────────────────────────────────────────────
  sourceFolderPath = '';
  destinationFolderPath = '';
  sourceImageCount = 0;
  passthroughNonComposites = true;
  includeMasks = false;
  overwriteExisting = false;

  // Folder picker ────────────────────────────────────────────────────
  showFolderPicker = false;
  folderPickerTarget: FolderPickerTarget = 'source';
  folderPickerTitle = '';
  folderPickerInfo: LocalFolderInfo | null = null;
  folderPickerLoading = false;

  // Job state ────────────────────────────────────────────────────────
  activeJob: DestitchBatchStatus | null = null;
  activeJobId: string | null = null;
  recentJobs: DestitchBatchJobSummary[] = [];
  isStarting = false;
  startError = '';

  private pollSub?: Subscription;

  constructor(
    private destitch: DestitchService,
    private session: DestitchSessionService,
  ) {}

  ngOnInit(): void {
    this.refreshJobs();
    const preselected = this.session.consumePrefilledSource();
    if (preselected) {
      this.applyPrefilledSource(preselected);
    }
  }

  private applyPrefilledSource(path: string): void {
    this.sourceFolderPath = path;
    this.sourceImageCount = 0;
    this.destitch.browseLocalFolder(path).subscribe({
      next: (info) => {
        if (!info?.error) {
          this.sourceImageCount = info.image_count;
        }
      },
      error: () => {},
    });
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  // UI handlers ──────────────────────────────────────────────────────

  openFolderPicker(target: FolderPickerTarget): void {
    this.folderPickerTarget = target;
    this.folderPickerTitle = target === 'source'
      ? 'Select source folder (images to destitch)'
      : 'Select destination folder (output crops)';
    this.showFolderPicker = true;
    const startPath = target === 'source' ? this.sourceFolderPath : this.destinationFolderPath;
    this.loadFolderPicker(startPath);
  }

  closeFolderPicker(): void {
    this.showFolderPicker = false;
  }

  navigateFolder(path: string): void {
    this.loadFolderPicker(path);
  }

  selectFolder(): void {
    if (!this.folderPickerInfo) { return; }
    const path = this.folderPickerInfo.path;
    if (this.folderPickerTarget === 'source') {
      this.sourceFolderPath = path;
      this.sourceImageCount = this.folderPickerInfo.image_count;
    } else {
      this.destinationFolderPath = path;
    }
    this.closeFolderPicker();
  }

  clearSource(): void {
    this.sourceFolderPath = '';
    this.sourceImageCount = 0;
  }

  clearDestination(): void {
    this.destinationFolderPath = '';
  }

  get canStart(): boolean {
    return !!this.sourceFolderPath && !!this.destinationFolderPath && !this.isStarting &&
      !(this.activeJob && this.activeJob.status === 'running');
  }

  startJob(): void {
    if (!this.canStart) { return; }
    this.isStarting = true;
    this.startError = '';
    this.destitch.startBatch({
      source_folder_path: this.sourceFolderPath,
      destination_folder_path: this.destinationFolderPath,
      passthrough_non_composites: this.passthroughNonComposites,
      include_masks: this.includeMasks,
      overwrite_existing: this.overwriteExisting,
    }).subscribe({
      next: (r) => {
        this.isStarting = false;
        if (r.success && r.job_id) {
          this.activeJobId = r.job_id;
          this.beginPolling(r.job_id);
        } else {
          this.startError = r.error || r.message || 'Failed to start job.';
        }
      },
      error: (err) => {
        this.isStarting = false;
        this.startError = err?.error?.message || err?.message || 'Failed to start job.';
      },
    });
  }

  cancelJob(): void {
    if (!this.activeJobId) { return; }
    this.destitch.cancelJob(this.activeJobId).subscribe(() => {
      this.pollSub?.unsubscribe();
      this.refreshJobs();
    });
  }

  openRecentJob(jobId: string): void {
    this.activeJobId = jobId;
    this.beginPolling(jobId);
  }

  // Internals ────────────────────────────────────────────────────────

  private loadFolderPicker(path: string): void {
    this.folderPickerLoading = true;
    this.destitch.browseLocalFolder(path).subscribe({
      next: (info) => {
        this.folderPickerInfo = info;
        this.folderPickerLoading = false;
      },
      error: () => {
        this.folderPickerLoading = false;
      },
    });
  }

  private beginPolling(jobId: string): void {
    this.pollSub?.unsubscribe();
    this.pollSub = interval(1500).pipe(
      startWith(0),
      switchMap(() => this.destitch.getBatchStatus(jobId)),
    ).subscribe({
      next: (status) => {
        this.activeJob = status;
        if (status.status === 'completed' || status.status === 'failed' ||
            status.status === 'cancelled') {
          this.pollSub?.unsubscribe();
          this.refreshJobs();
        }
      },
      error: () => {
        this.pollSub?.unsubscribe();
      },
    });
  }

  private refreshJobs(): void {
    this.destitch.listJobs(20).subscribe({
      next: (jobs) => { this.recentJobs = jobs; },
      error: () => {},
    });
  }
}
