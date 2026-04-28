import { Component, OnDestroy, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { Subscription, interval } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { DestitchService } from '../../services/destitch.service';
import {
  DestitchView,
  DestitchResult,
  LocalFolderInfo,
  DestitchBatchStatus,
} from '../../models/destitch';

export enum SegmentationViewMode {
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training',
  Batch = 'batch',
  Export = 'export',
}

interface SegmentationDataset {
  id: string;
  name: string;
  description: string;
  source_folder: string;
  /** Optional whitelist of filenames inside `source_folder`. When set, only these files are counted/listed. */
  image_filter?: string[];
  image_count?: number;
  /** Persisted count of images with saved line-segmentation annotations. Placeholder until saveAnnotations is wired. */
  annotated_count?: number;
  created_at?: string;
  updated_at?: string;
  images?: string[];
  loading?: boolean;
  detailsLoading?: boolean;
  error?: string;
}

interface ImageDestitchState {
  status: 'idle' | 'running' | 'done' | 'error';
  result?: DestitchResult;
  error?: string;
}

const STORAGE_KEY = 'segmentation.datasets.v3';

// 20 strictly-successive Neo-Assyrian SAA 19 administrative letters from
// P393645 (skipping only the two CDLI IDs in this range that don't exist:
// P393660, P393665). 13 have photo files, 7 are lineart-only.
const NA_TEST_P_NUMBERS = [
  'P393645', 'P393646', 'P393647', 'P393648', 'P393649',
  'P393650', 'P393651', 'P393652', 'P393653', 'P393654',
  'P393655', 'P393656', 'P393657', 'P393658', 'P393659',
  'P393661', 'P393662', 'P393663', 'P393664', 'P393666',
];

const SEED_TIMESTAMP = '2026-04-28T00:00:00.000Z';

const SEED_DATASETS: SegmentationDataset[] = [
  {
    id: 'si_test',
    name: 'Si_test',
    description: 'Sippar tablet stitched composites — used for development and regression testing.',
    source_folder: 'C:/Users/wende/Downloads/Sippar/Sippar Selection/_Final_JPG',
    annotated_count: 0,
    created_at: SEED_TIMESTAMP,
    updated_at: SEED_TIMESTAMP,
  },
  {
    id: 'na_test_photos',
    name: 'NA_test_photos',
    description: 'Neo-Assyrian SAA 19 administrative letters — 20 strictly-successive tablets from P393645 (13 photos + 7 lineart-only). Test set for line-segmentation training.',
    source_folder: 'C:/Users/wende/Documents/Shahar/file/photos',
    image_filter: NA_TEST_P_NUMBERS.map(p => `${p}.jpg`),
    annotated_count: 0,
    created_at: SEED_TIMESTAMP,
    updated_at: SEED_TIMESTAMP,
  },
];

interface SegModel {
  id: string;
  label: string;
  group: 'destitch' | 'line-segmentation' | 'view-classifier';
  available: boolean;
}

@Component({
  selector: 'app-segmentation',
  templateUrl: './segmentation.component.html',
  styleUrls: ['./segmentation.component.scss'],
})
export class SegmentationComponent implements OnInit, OnDestroy {

  viewMode: SegmentationViewMode = SegmentationViewMode.Datasets;
  SegmentationViewMode = SegmentationViewMode;

  datasets: SegmentationDataset[] = [];
  selectedDataset: SegmentationDataset | null = null;
  selectedImageName: string | null = null;

  // Top-level (grid) vs drill-down (single dataset detail)
  showDatasetList = true;
  datasetViewMode: 'grid' | 'list' = 'grid';
  datasetSearchQuery = '';

  // Create-dataset form (sidebar)
  newDatasetName = '';
  newDatasetPath = '';
  createError = '';
  isDragOver = false;

  // Folder picker modal (mirrors batch-destitch flow)
  showFolderPicker = false;
  folderPickerInfo: LocalFolderInfo | null = null;
  folderPickerLoading = false;

  // ── Auto-Annotate (mirrors yolo-training "Layout Detection") ──
  autoAnnotateFormVisible = false;
  autoAnnotateSourceDatasetId = '';
  autoAnnotateModelId = '';
  autoAnnotateDatasetName = '';
  autoAnnotateDestPath = '';
  autoAnnotateConfidence = 0.5;
  autoAnnotateIncludeMasks = false;
  autoAnnotateOverwrite = false;
  autoAnnotatePassthrough = true;
  autoAnnotateJobId: string | null = null;
  autoAnnotateStatus: DestitchBatchStatus | null = null;
  isAutoAnnotating = false;

  readonly autoAnnotateModels: SegModel[] = [
    { id: 'destitch',     label: 'Destitch (rule-based view splitter)', group: 'destitch',          available: true },
    { id: 'line-seg-v1',  label: 'Line segmentation — coming soon',     group: 'line-segmentation', available: false },
    { id: 'view-class-v1',label: 'View classifier — coming soon',       group: 'view-classifier',   available: false },
  ];

  // Per-image destitch state, keyed by absolute path.
  private imageStates: Map<string, ImageDestitchState> = new Map();
  private autoAnnotatePollSub?: Subscription;

  constructor(
    private destitch: DestitchService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.datasets = this.loadDatasets();
    for (const ds of this.datasets) {
      this.refreshDatasetCount(ds);
    }
  }

  ngOnDestroy(): void {
    this.stopAutoAnnotatePoll();
  }

  setViewMode(mode: SegmentationViewMode): void {
    this.viewMode = mode;
  }

  // ───── Persistence ─────
  private loadDatasets(): SegmentationDataset[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as SegmentationDataset[];
        if (Array.isArray(parsed) && parsed.length) {
          return parsed.map(d => ({ ...d, images: undefined, loading: false, detailsLoading: false, error: undefined }));
        }
      }
    } catch {}
    return SEED_DATASETS.map(d => ({ ...d }));
  }

  private saveDatasets(): void {
    try {
      const slim = this.datasets.map(d => ({
        id: d.id,
        name: d.name,
        description: d.description,
        source_folder: d.source_folder,
        image_filter: d.image_filter,
        annotated_count: d.annotated_count,
        created_at: d.created_at,
        updated_at: d.updated_at,
      }));
      localStorage.setItem(STORAGE_KEY, JSON.stringify(slim));
    } catch {}
  }

  // ───── Filtering ─────
  get filteredDatasets(): SegmentationDataset[] {
    const q = this.datasetSearchQuery.trim().toLowerCase();
    if (!q) { return this.datasets; }
    return this.datasets.filter(d =>
      d.name.toLowerCase().includes(q) ||
      (d.description || '').toLowerCase().includes(q));
  }

  clearDatasetSearch(): void {
    this.datasetSearchQuery = '';
  }

  // ───── Create / delete dataset ─────
  createDataset(): void {
    const name = this.newDatasetName.trim();
    const path = this.newDatasetPath.trim();
    this.createError = '';
    if (!name) { this.createError = 'Name required'; return; }
    if (!path) { this.createError = 'Folder path required'; return; }
    if (this.datasets.some(d => d.name.toLowerCase() === name.toLowerCase())) {
      this.createError = 'A dataset with that name already exists';
      return;
    }
    const now = new Date().toISOString();
    const ds: SegmentationDataset = {
      id: `${name.toLowerCase().replace(/[^a-z0-9_]+/g, '_')}_${Date.now()}`,
      name,
      description: '',
      source_folder: path,
      annotated_count: 0,
      created_at: now,
      updated_at: now,
    };
    this.datasets = [...this.datasets, ds];
    this.saveDatasets();
    this.newDatasetName = '';
    this.newDatasetPath = '';
    this.refreshDatasetCount(ds);
  }

  // ───── Drag-drop / folder upload (mirrors CuReD sidebar) ─────
  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = true;
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = false;
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = false;
    const items = event.dataTransfer?.items;
    if (items && items.length) {
      // Try to extract a folder name from the first dropped entry.
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        const entry = (item as any).webkitGetAsEntry?.();
        if (entry) {
          this.newDatasetName ||= entry.name;
          if (!this.newDatasetPath) {
            this.createError = 'Folder name captured. Click Server to pick the actual server-side path.';
          }
          return;
        }
      }
    }
    const files = event.dataTransfer?.files;
    if (files && files.length) {
      const f: any = files[0];
      // Electron exposes File.path on dropped files; in pure browser it's undefined.
      if (f.path) {
        const dirPath = String(f.path).replace(/[\\/][^\\/]+$/, '');
        const dirName = dirPath.split(/[\\/]/).pop() || '';
        this.newDatasetName ||= dirName;
        this.newDatasetPath = dirPath;
      } else {
        this.newDatasetName ||= (f.webkitRelativePath || f.name || '').split('/')[0] || f.name;
        this.createError = 'Drop captured. Click Server to pick the actual server-side path.';
      }
    }
  }

  handleFolderInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files;
    if (!files || !files.length) { return; }
    const first: any = files[0];
    const folderName = (first.webkitRelativePath || '').split('/')[0] || first.name;
    if (folderName) {
      this.newDatasetName ||= folderName;
    }
    if (first.path) {
      const dirPath = String(first.path).replace(/[\\/][^\\/]+$/, '');
      this.newDatasetPath = dirPath;
    } else if (!this.newDatasetPath) {
      this.createError = 'Folder name captured. Click Server to pick the actual server-side path.';
    }
    input.value = '';
  }

  // ───── Server folder picker modal ─────
  openFolderPicker(): void {
    this.showFolderPicker = true;
    this.loadFolderPicker(this.newDatasetPath || '');
  }

  closeFolderPicker(): void {
    this.showFolderPicker = false;
  }

  navigateFolder(path: string): void {
    this.loadFolderPicker(path);
  }

  selectPickedFolder(): void {
    if (!this.folderPickerInfo) { return; }
    this.newDatasetPath = this.folderPickerInfo.path;
    if (!this.newDatasetName) {
      const segs = this.folderPickerInfo.path.split(/[\\/]/).filter(Boolean);
      this.newDatasetName = segs[segs.length - 1] || '';
    }
    this.createError = '';
    this.closeFolderPicker();
  }

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

  deleteDataset(ds: SegmentationDataset, event?: Event): void {
    if (event) { event.stopPropagation(); }
    if (!confirm(`Delete dataset "${ds.name}"? (Images on disk are not affected.)`)) { return; }
    this.datasets = this.datasets.filter(d => d.id !== ds.id);
    this.saveDatasets();
    if (this.selectedDataset?.id === ds.id) {
      this.backToDatasets();
    }
  }

  // ───── Navigation ─────
  openDataset(ds: SegmentationDataset): void {
    this.selectedDataset = ds;
    this.selectedImageName = null;
    this.showDatasetList = false;
    if (ds.images === undefined && !ds.detailsLoading) {
      this.loadDatasetDetails(ds);
    }
  }

  backToDatasets(): void {
    this.selectedDataset = null;
    this.selectedImageName = null;
    this.showDatasetList = true;
  }

  /** Navigate to the line-segmentation canvas, loading the dataset's first tablet (by P-number when available). */
  openAnnotationCanvas(ds: SegmentationDataset): void {
    const firstImage = (ds.images && ds.images[0]) || (ds.image_filter && ds.image_filter[0]) || '';
    const match = firstImage.match(/P\d+/i);
    const queryParams = match ? { p: match[0].toUpperCase() } : {};
    this.router.navigate(['/line-segmentation'], { queryParams });
  }

  selectImage(name: string): void {
    this.selectedImageName = (this.selectedImageName === name) ? null : name;
  }

  // ───── Destitch per image ─────
  imagePath(name: string): string {
    if (!this.selectedDataset) { return ''; }
    return `${this.selectedDataset.source_folder.replace(/\/+$/, '')}/${name}`;
  }

  imageState(name: string): ImageDestitchState {
    return this.imageStates.get(this.imagePath(name)) || { status: 'idle' };
  }

  destitchImage(name: string): void {
    const path = this.imagePath(name);
    if (!path) { return; }
    this.imageStates.set(path, { status: 'running' });
    this.destitch.splitByPath({ path, include_crops: true }).subscribe({
      next: (result) => {
        if (result.error) {
          this.imageStates.set(path, { status: 'error', error: result.error });
          return;
        }
        this.imageStates.set(path, { status: 'done', result });
      },
      error: (err) => {
        this.imageStates.set(path, {
          status: 'error',
          error: err?.error?.detail || err?.message || 'Destitch failed.',
        });
      },
    });
  }

  resetDestitch(name: string): void {
    this.imageStates.delete(this.imagePath(name));
  }

  cropDataUri(view: DestitchView): string {
    return view.crop_base64 ? `data:image/png;base64,${view.crop_base64}` : '';
  }

  // ───── Stats (sidebar) ─────
  get totalImages(): number {
    return this.datasets.reduce((sum, d) => sum + (d.image_count || 0), 0);
  }

  get totalDestitched(): number {
    let n = 0;
    this.imageStates.forEach(s => { if (s.status === 'done') { n += 1; } });
    return n;
  }

  get datasetsWithErrors(): number {
    return this.datasets.filter(d => !!d.error).length;
  }

  /**
   * Number of images in this dataset that have been destitched in the current session.
   * Counts entries in `imageStates` whose path falls under the dataset's source folder.
   */
  destitchedCountFor(ds: SegmentationDataset): number {
    if (!ds.source_folder) { return 0; }
    const prefix = ds.source_folder.replace(/[\\/]+$/, '') + '/';
    let n = 0;
    this.imageStates.forEach((state, key) => {
      if (state.status === 'done' && key.startsWith(prefix)) { n += 1; }
    });
    return n;
  }

  /** True when at least one image is destitched and the count matches `image_count`. */
  isDatasetReady(ds: SegmentationDataset): boolean {
    if (!ds.image_count) { return false; }
    return this.destitchedCountFor(ds) >= ds.image_count;
  }

  annotatedCountFor(ds: SegmentationDataset): number {
    return ds.annotated_count || 0;
  }

  /**
   * Aggregate the view-codes across all destitched images in this dataset.
   * Returns rows like {name: 'obverse', count: 12}, sorted by count desc.
   * Used as the segmentation analog of yolo-training's "Class distribution".
   */
  viewDistributionFor(ds: SegmentationDataset): { name: string; count: number; color: string }[] {
    if (!ds.source_folder) { return []; }
    const prefix = ds.source_folder.replace(/[\\/]+$/, '') + '/';
    const counts = new Map<string, number>();
    this.imageStates.forEach((state, key) => {
      if (state.status !== 'done' || !key.startsWith(prefix)) { return; }
      for (const v of state.result?.views || []) {
        const label = this.viewLabel(v.code);
        counts.set(label, (counts.get(label) || 0) + 1);
      }
    });
    return Array.from(counts.entries())
      .map(([name, count]) => ({ name, count, color: this.viewColor(name) }))
      .sort((a, b) => b.count - a.count);
  }

  totalViewCountFor(ds: SegmentationDataset): number {
    return this.viewDistributionFor(ds).reduce((sum, c) => sum + c.count, 0);
  }

  private viewLabel(code: string): string {
    // Destitch view codes are like "_01_obverse" or "obv" — normalise to readable label.
    const lower = (code || '').toLowerCase();
    if (lower.includes('obverse') || lower === '_01' || lower === 'obv') { return 'obverse'; }
    if (lower.includes('reverse') || lower === '_02' || lower === 'rev') { return 'reverse'; }
    if (lower.includes('top')     || lower === '_03') { return 'top'; }
    if (lower.includes('bottom')  || lower === '_04') { return 'bottom'; }
    if (lower.includes('left')    || lower === '_05') { return 'left edge'; }
    if (lower.includes('right')   || lower === '_06') { return 'right edge'; }
    return code || 'unknown';
  }

  private viewColor(label: string): string {
    const colors: Record<string, string> = {
      'obverse':    '#1976d2',
      'reverse':    '#7b1fa2',
      'top':        '#0097a7',
      'bottom':     '#c2185b',
      'left edge':  '#388e3c',
      'right edge': '#f57c00',
    };
    return colors[label] || '#888';
  }

  /** Recommendations / warnings shown in the summary panel. */
  datasetIssues(ds: SegmentationDataset): string[] {
    const issues: string[] = [];
    if (ds.error) {
      issues.push(`Folder error: ${ds.error}`);
    }
    if (!ds.image_count) {
      issues.push('No images detected in this folder.');
      return issues;
    }
    const destitched = this.destitchedCountFor(ds);
    const annotated = this.annotatedCountFor(ds);
    if (destitched < ds.image_count) {
      issues.push(`Run Auto-Annotate or per-image Destitch — ${ds.image_count - destitched} of ${ds.image_count} images still need view-splitting.`);
    }
    if (annotated < ds.image_count) {
      issues.push(`Annotate line baselines — ${ds.image_count - annotated} of ${ds.image_count} images have no line-segmentation ground truth yet.`);
    }
    if (annotated > 0 && annotated < 50) {
      issues.push('Aim for ≥ 50 annotated images before training a line-segmentation model.');
    }
    return issues;
  }

  isReadyForTraining(ds: SegmentationDataset): boolean {
    if (!ds.image_count) { return false; }
    const annotated = this.annotatedCountFor(ds);
    return annotated >= Math.max(50, ds.image_count);
  }

  clearCapturedPath(): void {
    this.newDatasetPath = '';
    this.createError = '';
  }

  // ───── Auto-Annotate (Layout-style) ─────
  showAutoAnnotateForm(): void {
    this.autoAnnotateFormVisible = true;
    this.autoAnnotateSourceDatasetId = '';
    this.autoAnnotateModelId = 'destitch';
    this.autoAnnotateDatasetName = '';
    this.autoAnnotateDestPath = '';
    this.autoAnnotateConfidence = 0.5;
    this.autoAnnotateStatus = null;
    this.autoAnnotateJobId = null;
    this.isAutoAnnotating = false;
    this.stopAutoAnnotatePoll();
  }

  hideAutoAnnotateForm(): void {
    this.autoAnnotateFormVisible = false;
    this.stopAutoAnnotatePoll();
  }

  onAutoAnnotateSourceChange(): void {
    const src = this.datasets.find(d => d.id === this.autoAnnotateSourceDatasetId);
    if (!src) { return; }
    if (!this.autoAnnotateDatasetName) {
      this.autoAnnotateDatasetName = `${src.name}_auto`;
    }
    if (!this.autoAnnotateDestPath) {
      const base = src.source_folder.replace(/[\\/]+$/, '');
      this.autoAnnotateDestPath = `${base}_destitched`;
    }
  }

  startAutoAnnotate(): void {
    const src = this.datasets.find(d => d.id === this.autoAnnotateSourceDatasetId);
    if (!src) { return; }
    if (!this.autoAnnotateModelId) { return; }
    if (!this.autoAnnotateDatasetName.trim()) { return; }
    if (!this.autoAnnotateDestPath.trim()) { return; }
    if (this.autoAnnotateModelId !== 'destitch') { return; }

    this.isAutoAnnotating = true;
    this.autoAnnotateStatus = null;
    this.destitch.startBatch({
      source_folder_path: src.source_folder,
      destination_folder_path: this.autoAnnotateDestPath.trim(),
      passthrough_non_composites: this.autoAnnotatePassthrough,
      include_masks: this.autoAnnotateIncludeMasks,
      overwrite_existing: this.autoAnnotateOverwrite,
    }).subscribe({
      next: (resp) => {
        if (resp.success && resp.job_id) {
          this.autoAnnotateJobId = resp.job_id;
          this.startAutoAnnotatePoll(resp.job_id);
        } else {
          this.isAutoAnnotating = false;
        }
      },
      error: () => {
        this.isAutoAnnotating = false;
      },
    });
  }

  private startAutoAnnotatePoll(jobId: string): void {
    this.stopAutoAnnotatePoll();
    this.autoAnnotatePollSub = interval(1500).pipe(
      switchMap(() => this.destitch.getBatchStatus(jobId)),
    ).subscribe({
      next: (status) => {
        this.autoAnnotateStatus = status;
        if (status.status === 'completed') {
          this.isAutoAnnotating = false;
          this.stopAutoAnnotatePoll();
        } else if (status.status === 'failed' || status.status === 'cancelled') {
          this.isAutoAnnotating = false;
          this.stopAutoAnnotatePoll();
        }
      },
      error: () => {
        this.isAutoAnnotating = false;
        this.stopAutoAnnotatePoll();
      },
    });
  }

  private stopAutoAnnotatePoll(): void {
    this.autoAnnotatePollSub?.unsubscribe();
    this.autoAnnotatePollSub = undefined;
  }

  openAutoAnnotatedDataset(): void {
    if (!this.autoAnnotateStatus || !this.autoAnnotateDestPath) { return; }
    const name = this.autoAnnotateDatasetName.trim() || 'auto_destitched';
    if (this.datasets.some(d => d.name.toLowerCase() === name.toLowerCase())) {
      const existing = this.datasets.find(d => d.name.toLowerCase() === name.toLowerCase())!;
      this.hideAutoAnnotateForm();
      this.openDataset(existing);
      return;
    }
    const now = new Date().toISOString();
    const ds: SegmentationDataset = {
      id: `${name.toLowerCase().replace(/[^a-z0-9_]+/g, '_')}_${Date.now()}`,
      name,
      description: `Auto-annotated from "${this.datasets.find(d => d.id === this.autoAnnotateSourceDatasetId)?.name || ''}"`,
      source_folder: this.autoAnnotateDestPath.trim(),
      annotated_count: 0,
      created_at: now,
      updated_at: now,
    };
    this.datasets = [...this.datasets, ds];
    this.saveDatasets();
    this.refreshDatasetCount(ds);
    this.hideAutoAnnotateForm();
    this.openDataset(ds);
  }

  // ───── Backend folder browse ─────
  private refreshDatasetCount(ds: SegmentationDataset): void {
    if (!ds.source_folder) { return; }
    // Filtered datasets: count is the filter length (filenames assumed to exist).
    if (ds.image_filter && ds.image_filter.length) {
      ds.image_count = ds.image_filter.length;
      ds.loading = false;
      return;
    }
    ds.loading = true;
    this.destitch.browseLocalFolder(ds.source_folder).subscribe({
      next: (info) => {
        ds.image_count = info.image_count;
        ds.loading = false;
        if (info.error) { ds.error = info.error; }
      },
      error: () => {
        ds.loading = false;
        ds.error = 'Folder not reachable from server.';
      },
    });
  }

  private loadDatasetDetails(ds: SegmentationDataset): void {
    // Filtered datasets: skip the folder browse entirely — use the filter as the image list.
    if (ds.image_filter && ds.image_filter.length) {
      ds.images = [...ds.image_filter];
      ds.image_count = ds.image_filter.length;
      ds.detailsLoading = false;
      return;
    }
    ds.detailsLoading = true;
    this.destitch.browseLocalFolder(ds.source_folder, /* includeImages */ true).subscribe({
      next: (info) => {
        ds.images = info.images || [];
        ds.image_count = info.image_count;
        ds.detailsLoading = false;
        if (info.error) { ds.error = info.error; }
      },
      error: () => {
        ds.detailsLoading = false;
        ds.error = 'Failed to load dataset contents.';
      },
    });
  }
}
