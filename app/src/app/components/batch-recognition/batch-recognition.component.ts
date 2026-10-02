import { Component, OnInit, OnDestroy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { MatDialog } from '@angular/material/dialog';
import { Subject, Subscription, interval } from 'rxjs';
import { filter, switchMap, takeUntil, tap } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import { BatchRecognitionService } from '../../services/batch-recognition.service';
import { CuredService } from '../../services/cured.service';
import { PagesService } from '../../services/pages.service';
import { DatasetService } from '../../services/dataset.service';
import { NotificationService } from '../../services/notification.service';
import { FolderPickerDialogComponent, FolderPickerResult } from '../common/folder-picker-dialog/folder-picker-dialog.component';
import { ConfirmDialogComponent } from '../common/confirm-dialog/confirm-dialog.component';
import { LocalFileBrowserDialogComponent, LocalBrowseResult } from './local-file-browser-dialog/local-file-browser-dialog.component';
import { rangeToggle } from './local-file-browser-dialog/range-toggle';
import {
  BatchRecognitionRequest,
  BatchRecognitionStatus,
  BatchRecognitionJobSummary,
  LatestModelAlias,
  ProviderBatch,
  ProviderModel,
  VllmStatus,
} from '../../models/batch-recognition';
import { DatasetPreview } from '../../models/cured';

type SourceMode = 'library' | 'local';

/** One folder on this computer and the image files chosen in it. */
interface LocalSource {
  path: string;
  name: string;
  files: string[];       // image filenames (not paths) inside `path`
  wholeFolder: boolean;  // added via "Folder…" (vs. picked file by file)
}
type DestinationMode = 'library' | 'export';

@Component({
  selector: 'app-batch-recognition',
  templateUrl: './batch-recognition.component.html',
  styleUrls: ['./batch-recognition.component.scss']
})
export class BatchRecognitionComponent implements OnInit, OnDestroy {
  // Source mode
  sourceMode: SourceMode = 'library';

  // Library source
  sourceProjectId: string = '';
  sourceProjectName: string = '';

  // Local source ("Browse Computer"): folders and/or individual files, read in place
  // from disk and never copied into the Library. One entry per folder.
  localSources: LocalSource[] = [];

  // Class filtering (extracted from source filenames)
  availableClasses: Array<{ name: string; count: number }> = [];
  selectedClasses: Set<string> = new Set();

  // File selection (selective batch)
  allFilenames: string[] = [];
  selectedFilenames: Set<string> = new Set();
  showFileSelector: boolean = false;
  fileFilter: string = '';

  // Destination mode
  destinationMode: DestinationMode = 'library';
  destinationDatasetId: number | null = null;
  destinationDatasetName: string = '';
  destinationFolderPath: string = '';
  destinationFolderName: string = '';

  // Export options
  exportImages: boolean = false;

  // CuReD dataset list (for destination badges)
  curedDatasets: DatasetPreview[] = [];
  newDatasetName: string = '';
  isCreatingDataset: boolean = false;

  // Model selection (replicated from CuReD)
  selectedModel: string = 'kraken_cusas';
  apiKey: string = '';
  selectedSubModel: string = '';

  // Processing mode: 'live' (synchronous, real-time) or 'batch_api' (async provider
  // Batch API — 50% cheaper, no per-minute throttling, results within ~24h).
  // Only valid for cloud providers (see supportsBatchApi()).
  executionMode: 'live' | 'batch_api' = 'live';

  // Recovering provider batches whose local job record was lost
  showRecoverPanel = false;
  providerBatches: ProviderBatch[] = [];
  loadingProviderBatches = false;
  recoveringBatchId: string | null = null;

  // Live model lists fetched from each provider's /models endpoint (keyed by selectedModel).
  // When present they replace the static apiSubModels fallback below in the dropdown.
  liveSubModels: { [key: string]: { latest: LatestModelAlias[]; models: ProviderModel[] } } = {};
  subModelsLoading = false;
  subModelsError = '';

  // Offline fallback, shown until a live list loads (or if the fetch fails).
  apiSubModels: { [key: string]: Array<{value: string; label: string; description: string}> } = {
    'gemini_vision': [
      { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite', description: 'Cost efficient' },
      { value: 'gemini-3.1-flash-lite-preview', label: 'Gemini 3.1 Flash-Lite', description: 'Fast multimodal' },
      { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro', description: 'Most capable' },
    ],
    'claude_vision': [
      { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5', description: 'Fastest, cheapest' },
      { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', description: 'Balanced' },
      { value: 'claude-opus-4-8', label: 'Claude Opus 4.8', description: 'Most intelligent' },
    ],
    'gpt4_vision': [
      { value: 'gpt-4o', label: 'GPT-4o', description: 'Omni, vision capable' },
      { value: 'gpt-4o-mini', label: 'GPT-4o Mini', description: 'Faster, cheaper' },
      { value: 'gpt-4.1', label: 'GPT-4.1', description: 'Best for coding' },
    ],
    'grok_xai': [
      { value: 'grok-4-1-fast-non-reasoning', label: 'Grok 4.1 Fast', description: 'Cheap, quick' },
      { value: 'grok-4-1-fast-reasoning', label: 'Grok 4.1 Fast (Reasoning)', description: 'Reasoning' },
    ],
  };

  ocrModelCategories: Array<{
    name: string;
    models: Array<{value: string; label: string; description?: string}>;
  }> = [
    {
      name: 'CPU',
      models: [
        // Trained Kraken, Qwen LoRA, and TrOCR models are loaded dynamically from the backend
      ]
    },
    {
      name: 'Local GPU',
      models: [
        { value: 'nemotron_local', label: 'Nemotron', description: 'Document parsing (1.7GB VRAM)' },
        // Additional models populated dynamically from Ollama
      ]
    },
    {
      name: 'Ollama Cloud',
      models: [
        { value: 'qwen3_vl_235b_cloud', label: 'Qwen3 VL 235B', description: 'Free, best quality' },
        { value: 'qwen3_vl_235b_thinking', label: 'Qwen3 VL 235B Thinking', description: 'STEM/math reasoning' },
      ]
    },
    {
      name: 'API',
      models: [
        { value: 'nemotron_cloud', label: 'Nemotron', description: 'NVIDIA Build' },
        { value: 'gpt4_vision', label: 'GPT-4 Vision', description: 'OpenAI' },
        { value: 'claude_vision', label: 'Claude Vision', description: 'Anthropic' },
        { value: 'gemini_vision', label: 'Gemini Vision', description: 'Google' },
        { value: 'grok_xai', label: 'Grok', description: 'xAI' },
      ]
    }
  ];

  modelAvailability: { [key: string]: boolean } = {
    'nemotron_local': true,
    'qwen3_vl_235b_cloud': true,
    'qwen3_vl_235b_thinking': true,
    'nemotron_cloud': true,
    'gpt4_vision': true,
    'claude_vision': true,
    'gemini_vision': true,
    'grok_xai': true,
  };

  // Post-OCR correction rules
  correctionRules: string = '';
  correctionRulesOptions: Array<{value: string; label: string; description: string}> = [
    { value: '', label: 'None', description: 'No post-OCR corrections' },
    { value: 'akkadian', label: 'Akkadian', description: 'Fix glottal stops (ʾ), reference signs (↑), special chars' },
  ];

  // Prompt selection
  selectedPrompt: string = 'dictionary';
  ocrPromptModes: Array<{value: string; label: string; description: string}> = [
    { value: 'plain', label: 'Plain', description: 'Simple text extraction' },
    { value: 'markdown', label: 'Markdown', description: 'Formatted with markdown' },
    { value: 'dictionary', label: 'Dictionary', description: 'Akkadian dictionary entries' },
  ];
  customPromptText: string = '';
  loadedPrompts: Array<{key: string; value: string; builtin?: boolean}> = [];
  editingPrompt: boolean = false;
  editPromptValue: string = '';
  showNewPromptForm: boolean = false;
  newPromptName: string = '';
  newPromptText: string = '';
  creatingPrompt: boolean = false;

  // Image resize — target DPI (0 = no resize / full resolution)
  targetDpi: number = 0;
  targetDpiOptions: Array<{value: number; label: string}> = [
    { value: 0, label: 'Full Resolution' },
    { value: 600, label: '600 DPI' },
    { value: 450, label: '450 DPI' },
    { value: 300, label: '300 DPI' },
    { value: 200, label: '200 DPI' },
  ];

  // Image scale — applied after DPI resize (1.0 = no additional scaling)
  imageScale: number = 1.0;
  imageScaleOptions: Array<{value: number; label: string}> = [
    { value: 1.0, label: '100%' },
    { value: 0.75, label: '75%' },
    { value: 0.5, label: '50%' },
    { value: 0.33, label: '33%' },
    { value: 0.25, label: '25%' },
  ];

  // Box detection mode
  boxMode: string = 'estimate';
  boxModeOptions: Array<{value: string; label: string; description: string}> = [
    { value: 'none', label: 'None', description: 'No line boxes — text only' },
    { value: 'estimate', label: 'Estimate', description: 'Evenly divide image height by line count' },
    { value: 'predict', label: 'Predict (Kraken)', description: 'Kraken segmentation for line boundaries' },
  ];

  // Tiling Mode
  tilingMode: string = 'none';
  tilingModeOptions: Array<{value: string; label: string; description: string}> = [
    { value: 'none', label: 'None', description: 'Process full page image natively' },
    { value: 'full_page_clipped', label: 'Full Page (Clipped)', description: 'Aggressive margin reduction, single column' },
    { value: 'two_columns', label: '2 Columns', description: 'Split vertically into Left & Right halves (plus margins)' },
    { value: 'four_quadrants', label: '4 Quadrants', description: 'Split into 2x2 grid (optimizes OCR resolution)' },
  ];

  // Batch config — "dynamic" = size-based batching, "fixed" = user-specified batch size
  batchMode: 'dynamic' | 'fixed' = 'fixed';
  batchSize: number = 0;

  // Right panel tab
  rightTab: 'settings' | 'report' | 'usage' = 'settings';

  // Usage stats
  usageData: Array<{ date: string; models: { [model: string]: { inferences: number; input_tokens: number; output_tokens: number; data_bytes: number; cost_usd?: number | null } } }> = [];

  // Job tracking (supports multiple concurrent jobs)
  activeJobIds: Set<string> = new Set();
  jobStatuses: Map<string, BatchRecognitionStatus> = new Map();
  selectedJobId: string | null = null;  // Which job is focused for the report view
  recentJobs: BatchRecognitionJobSummary[] = [];
  isStarting: boolean = false;

  private pollSubs: Map<string, Subscription> = new Map();
  private destroy$ = new Subject<void>();

  constructor(
    private http: HttpClient,
    private batchService: BatchRecognitionService,
    private curedService: CuredService,
    private pagesService: PagesService,
    private datasetService: DatasetService,
    private notificationService: NotificationService,
    private dialog: MatDialog,
  ) {}

  ngOnInit(): void {
    this.loadRecentJobs();
    this.loadOllamaModels();
    this.loadKrakenModels();
    this.loadPrompts();
    this.loadCuredDatasets();
    this.loadUsage();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.stopAllPolls();
  }

  // ============== Folder Selection ==============

  browseSource(): void {
    const dialogRef = this.dialog.open(FolderPickerDialogComponent, {
      width: '500px',
      data: { title: 'Select Source Folder' }
    });
    dialogRef.afterClosed().subscribe((result: FolderPickerResult) => {
      if (result) {
        this.sourceMode = 'library';
        this.sourceProjectId = result.project_id;
        this.sourceProjectName = result.project_name;
        this.localSources = [];
        this.detectClassesFromLibrary(result.project_id);
      }
    });
  }

  // ============== Browse Computer (local folders / files) ==============

  /** "Browse Computer": pick any mix of folders and image files in one window. */
  openLocalBrowser(): void {
    const startPath = this.localSources.length ? this.localSources[this.localSources.length - 1].path : undefined;
    this.dialog.open(LocalFileBrowserDialogComponent, {
      width: '640px',
      maxWidth: '95vw',
      data: { startPath },
    }).afterClosed().subscribe((result?: LocalBrowseResult) => {
      if (!result) return;
      result.folders.forEach(folder => this.addLocalFolder(folder));
      this.addLocalFilePaths(result.files);
    });
  }

  /** Add a whole folder; the backend lists its images (non-recursive). */
  private addLocalFolder(folderPath: string): void {
    this.batchService.browseLocalFolder(folderPath).subscribe({
      next: (info) => {
        const name = info.path.split(/[/\\]/).pop() || info.path;
        if (info.error) {
          this.notificationService.showError(`Cannot read folder: ${info.error}`);
          return;
        }
        if (!info.image_count) {
          this.notificationService.showError(`No supported images in "${name}" (PNG, JPG, TIFF, BMP, WebP)`);
          return;
        }
        this.mergeLocalSource(info.path, info.image_files || [], true);
        this.notificationService.showInfo(`Added folder: ${name} (${info.image_count} images)`);
      },
      error: () => this.notificationService.showError('Failed to read the selected folder')
    });
  }

  /** Add individual files, grouped by the folder they live in. */
  private addLocalFilePaths(paths: string[]): void {
    if (!paths || paths.length === 0) return;  // cancelled
    const images = paths.filter(p => this.isImageFile(p));
    if (images.length === 0) {
      this.notificationService.showError('No supported image files selected (PNG, JPG, TIFF, BMP, WebP)');
      return;
    }
    const byFolder = new Map<string, string[]>();
    for (const p of images) {
      const cut = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'));
      const folder = p.substring(0, cut);
      byFolder.set(folder, [...(byFolder.get(folder) || []), p.substring(cut + 1)]);
    }
    byFolder.forEach((files, folder) => this.mergeLocalSource(folder, files, false));
    const skipped = paths.length - images.length;
    this.notificationService.showInfo(
      `Added ${images.length} file(s)` + (skipped ? ` — ${skipped} non-image file(s) skipped` : '')
    );
  }

  private isImageFile(name: string): boolean {
    return /\.(png|jpe?g|tiff?|bmp|webp)$/i.test(name);
  }

  /** Add files of one folder to the local source list, merging with an existing entry. */
  private mergeLocalSource(folder: string, files: string[], wholeFolder: boolean): void {
    if (this.sourceMode !== 'local') {  // switching away from a Library source
      this.sourceProjectId = '';
      this.sourceProjectName = '';
      this.localSources = [];
      this.sourceMode = 'local';
    }
    const existing = this.localSources.find(src => src.path === folder);
    if (existing) {
      existing.files = Array.from(new Set([...existing.files, ...files])).sort();
      existing.wholeFolder = existing.wholeFolder || wholeFolder;
    } else {
      this.localSources.push({
        path: folder,
        name: folder.split(/[/\\]/).pop() || folder,
        files: [...files].sort(),
        wholeFolder,
      });
    }
    this.localSources = [...this.localSources];
    this.refreshLocalFileList();
  }

  removeLocalSource(source: LocalSource): void {
    this.localSources = this.localSources.filter(src => src !== source);
    if (this.localSources.length) {
      this.refreshLocalFileList();
    } else {
      this.clearSource();
    }
  }

  get localImageCount(): number {
    return this.localSources.reduce((n, src) => n + src.files.length, 0);
  }

  /** Rebuild the class/file lists from all local sources, keeping earlier checklist choices. */
  private refreshLocalFileList(): void {
    const previousSelected = this.showFileSelector ? new Set(this.selectedFilenames) : null;
    const previousAll = new Set(this.allFilenames);
    const keys: string[] = [];
    for (const src of this.localSources) {
      for (const f of src.files) { keys.push(this.localKey(src.path, f)); }
    }
    this.detectClassesFromFilenames(keys);
    if (previousSelected) {
      // Deselected files stay deselected; newly added files start selected
      this.selectedFilenames = new Set(keys.filter(k => previousSelected.has(k) || !previousAll.has(k)));
    }
  }

  /** File-list key for a local file: its full path, unique across folders. */
  private localKey(folder: string, file: string): string {
    return folder + (folder.includes('\\') ? '\\' : '/') + file;
  }

  /** Name shown in the file checklist: "folder/file" once several folders are involved. */
  fileLabel(key: string): string {
    if (this.sourceMode !== 'local') return key;
    const parts = key.split(/[/\\]/);
    return this.localSources.length > 1 ? parts.slice(-2).join('/') : parts[parts.length - 1];
  }

  // ============== Destination ==============

  setDestinationMode(mode: DestinationMode): void {
    this.destinationMode = mode;
    this.clearDestination();
  }

  onDestinationDatasetChange(datasetId: number): void {
    this.destinationDatasetId = datasetId;
    const dataset = this.curedDatasets.find(p => p.dataset_id === datasetId);
    this.destinationDatasetName = dataset ? dataset.name : '';
  }

  /** Select a local export folder — native dialog first, hidden input fallback. */
  async pickDestinationFolder(inputEl?: HTMLInputElement): Promise<void> {
    const api = (window as any).electronAPI;
    if (api && typeof api.pickDirectory === 'function') {
      try {
        const folderPath: string | null = await api.pickDirectory();
        if (!folderPath) return; // cancelled
        this.destinationFolderPath = folderPath;
        this.destinationFolderName = folderPath.split(/[/\\]/).pop() || folderPath;
        this.notificationService.showInfo(`Export folder: ${this.destinationFolderName}`);
        return;
      } catch {
        // fall through to input fallback
      }
    }
    if (inputEl) { inputEl.click(); }
  }

  handleDestinationFolderInput(event: any): void {
    const files: FileList = event.target.files;
    if (!files || files.length === 0) return;

    let folderPath = '';
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (!folderPath && (file as any).path) {
        const fullPath: string = (file as any).path;
        const sep = fullPath.includes('\\') ? '\\' : '/';
        folderPath = fullPath.substring(0, fullPath.lastIndexOf(sep));
        break;
      }
    }

    event.target.value = '';

    if (!folderPath) {
      this.notificationService.showError('Could not determine folder path. This feature requires the desktop app.');
      return;
    }

    this.destinationFolderPath = folderPath;
    this.destinationFolderName = folderPath.split(/[/\\]/).pop() || folderPath;
    this.notificationService.showInfo(`Export folder: ${this.destinationFolderName}`);
  }

  clearDestination(): void {
    this.destinationDatasetId = null;
    this.destinationDatasetName = '';
    this.destinationFolderPath = '';
    this.destinationFolderName = '';
    this.newDatasetName = '';
  }

  get hasDestination(): boolean {
    if (this.destinationMode === 'library') return !!this.destinationDatasetId;
    return !!this.destinationFolderPath;
  }

  // ============== Inline Dataset Creation ==============

  createNewDataset(): void {
    const name = this.newDatasetName.trim();
    if (!name) return;

    this.isCreatingDataset = true;
    this.datasetService.create(name).subscribe({
      next: (datasetId: number) => {
        this.isCreatingDataset = false;
        this.newDatasetName = '';
        this.destinationDatasetId = datasetId;
        this.destinationDatasetName = name;
        this.loadCuredDatasets();
        this.notificationService.showSuccess(`Dataset "${name}" created`);
      },
      error: (err) => {
        this.isCreatingDataset = false;
        this.notificationService.showError('Failed to create dataset: ' + (err.error?.detail || err.message));
      }
    });
  }

  private loadCuredDatasets(): void {
    this.datasetService.list().subscribe({
      next: (datasets) => {
        this.curedDatasets = datasets;
      },
      error: () => {}
    });
  }

  clearSource(): void {
    this.sourceProjectId = '';
    this.sourceProjectName = '';
    this.localSources = [];
    this.availableClasses = [];
    this.selectedClasses = new Set();
    this.allFilenames = [];
    this.selectedFilenames = new Set();
    this.showFileSelector = false;
    this.fileFilter = '';
  }

  get hasSource(): boolean {
    return !!this.sourceProjectId || this.localSources.length > 0;
  }

  get sourceDisplayName(): string {
    if (this.sourceMode === 'library') return this.sourceProjectName;
    return this.localSources.length === 1 ? this.localSources[0].name : `${this.localSources.length} folders`;
  }

  // ============== Class Filtering ==============

  private extractClassName(filename: string): string {
    // Extract class from YOLO snippet filename: "ahw-d-0001-005-mainEntry.png" → "mainEntry"
    const base = filename.split(/[/\\]/).pop() || filename;  // local keys are full paths
    const stem = base.replace(/\.[^/.]+$/, ''); // remove extension
    const lastHyphen = stem.lastIndexOf('-');
    return lastHyphen >= 0 ? stem.substring(lastHyphen + 1) : '';
  }

  private detectClassesFromFilenames(filenames: string[]): void {
    const counts: { [cls: string]: number } = {};
    for (const f of filenames) {
      const cls = this.extractClassName(f);
      if (cls) {
        counts[cls] = (counts[cls] || 0) + 1;
      }
    }
    this.availableClasses = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }));
    // Select all by default
    this.selectedClasses = new Set(this.availableClasses.map(c => c.name));
    // Populate file list for selective batch
    this.allFilenames = [...filenames].sort();
    this.selectedFilenames = new Set(this.allFilenames);
  }

  private detectClassesFromLibrary(projectId: string): void {
    this.pagesService.getProject(projectId).subscribe({
      next: (project) => {
        const filenames = project.pages.map(p => p.filename);
        this.detectClassesFromFilenames(filenames);
      },
      error: () => {
        this.availableClasses = [];
        this.selectedClasses = new Set();
      }
    });
  }

  toggleClass(className: string): void {
    if (this.selectedClasses.has(className)) {
      this.selectedClasses.delete(className);
    } else {
      this.selectedClasses.add(className);
    }
    // Trigger change detection
    this.selectedClasses = new Set(this.selectedClasses);
  }

  isClassSelected(className: string): boolean {
    return this.selectedClasses.has(className);
  }

  get selectedImageCount(): number {
    if (this.availableClasses.length === 0) return 0;
    return this.availableClasses
      .filter(c => this.selectedClasses.has(c.name))
      .reduce((sum, c) => sum + c.count, 0);
  }

  // ============== File Selection ==============

  get filteredFilenames(): string[] {
    if (!this.fileFilter) return this.allFilenames;
    const q = this.fileFilter.toLowerCase();
    return this.allFilenames.filter(f => this.fileLabel(f).toLowerCase().includes(q));
  }

  toggleFileSelector(): void {
    this.showFileSelector = !this.showFileSelector;
    if (!this.showFileSelector) {
      // When hiding, reset to all selected
      this.selectedFilenames = new Set(this.allFilenames);
      this.fileFilter = '';
    }
  }

  /** Last clicked checklist entry: anchor for Shift+click ranges. */
  private fileAnchor: string | null = null;

  toggleFile(filename: string, event?: MouseEvent): void {
    this.fileAnchor = rangeToggle(this.filteredFilenames, filename, this.fileAnchor, !!event?.shiftKey, this.selectedFilenames);
    this.selectedFilenames = new Set(this.selectedFilenames);
  }

  selectAllFiles(): void {
    this.selectedFilenames = new Set(this.allFilenames);
  }

  deselectAllFiles(): void {
    this.selectedFilenames = new Set();
  }

  isFileSelected(filename: string): boolean {
    return this.selectedFilenames.has(filename);
  }

  // ============== Model Selection ==============

  selectModel(modelValue: string): void {
    if (this.isModelAvailable(modelValue)) {
      this.selectedModel = modelValue;
      this.apiKey = localStorage.getItem('ocr_api_key_' + modelValue) || '';
      if (this.apiSubModels[modelValue]) {
        this.selectedSubModel = localStorage.getItem('ocr_sub_model_' + modelValue) || this.apiSubModels[modelValue][0].value;
      } else {
        this.selectedSubModel = '';
      }
      this.syncExecutionMode();
      this.loadProviderModels();
    }
  }

  /** Fetch the provider's current model list live (needs the API key). */
  loadProviderModels(refresh = false): void {
    const provider = this.selectedModel;
    if (!this.hasSubModels() || !this.apiKey) {
      return;
    }
    if (this.liveSubModels[provider] && !refresh) {
      return;
    }
    this.subModelsLoading = true;
    this.subModelsError = '';
    this.batchService.getProviderModels(provider, this.apiKey, refresh)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (res) => {
          this.subModelsLoading = false;
          if (!res.success || !res.models.length) {
            this.subModelsError = res.message || 'No vision models returned';
            return;
          }
          this.liveSubModels[provider] = { latest: res.latest, models: res.models };
          // Keep the saved choice if the provider still offers it, else track the newest model.
          const valid = [...res.latest, ...res.models].some(m => m.value === this.selectedSubModel);
          if (provider === this.selectedModel && !valid && res.latest.length) {
            this.selectedSubModel = res.latest[0].value;
            this.onSubModelChange();
          }
        },
        error: () => {
          this.subModelsLoading = false;
          this.subModelsError = 'Could not reach the provider — showing built-in list';
        },
      });
  }

  onApiKeyChange(): void {
    delete this.liveSubModels[this.selectedModel];
    this.loadProviderModels();
  }

  isModelAvailable(modelValue: string): boolean {
    return this.modelAvailability[modelValue] ?? false;
  }

  requiresApiKey(): boolean {
    const apiModels = ['nemotron_cloud', 'gpt4_vision', 'claude_vision', 'gemini_vision', 'grok_xai'];
    return apiModels.includes(this.selectedModel) && !this.selectedModel.startsWith('vllm');
  }

  /** Models that expose an async Batch API (50% off, ~24h). Drives the Live/Batch toggle. */
  supportsBatchApi(): boolean {
    return ['gpt4_vision', 'claude_vision', 'gemini_vision', 'grok_xai'].includes(this.selectedModel);
  }

  /** Force Live mode whenever the selected model has no Batch API. Call on model change. */
  syncExecutionMode(): void {
    if (!this.supportsBatchApi()) {
      this.executionMode = 'live';
    }
  }

  hasSubModels(): boolean {
    return !!this.apiSubModels[this.selectedModel];
  }

  onSubModelChange(): void {
    if (this.selectedModel && this.selectedSubModel) {
      localStorage.setItem('ocr_sub_model_' + this.selectedModel, this.selectedSubModel);
    }
  }

  getModelTooltip(model: {value: string; label: string; description?: string}): string {
    if (this.isModelAvailable(model.value)) {
      return model.description || model.label;
    }
    return 'Not installed';
  }

  getApiKeyPlaceholder(): string {
    if (this.selectedModel === 'nemotron_cloud') {
      return 'nvapi-... (from build.nvidia.com)';
    }
    return 'Enter your API key...';
  }

  private loadKrakenModels(): void {
    this.curedService.getAvailableOcrModels().subscribe({
      next: (response) => {
        const cpuCategory = this.ocrModelCategories.find(c => c.name === 'CPU');
        if (!cpuCategory) return;

        const existingValues = new Set(cpuCategory.models.map(m => m.value));

        for (const model of response.models) {
          // Add trained Kraken, Qwen LoRA, and TrOCR models that aren't already in the list
          if ((model.value.startsWith('kraken:') || model.value.startsWith('qwen_lora:') || model.value.startsWith('trocr:')) && !existingValues.has(model.value)) {
            let description = 'Trained Kraken model';
            if (model.value.startsWith('qwen_lora:')) description = 'Qwen QLoRA fine-tuned';
            else if (model.value.startsWith('trocr:')) description = 'TrOCR fine-tuned (line-level)';
            cpuCategory.models.push({
              value: model.value,
              label: model.label.replace(' (Kraken)', '').replace(/ \(Qwen QLoRA.*\)/, '').replace(/ \(TrOCR.*\)/, ''),
              description,
            });
            this.modelAvailability[model.value] = true;
          }
        }
      },
      error: () => {}
    });
  }

  private loadOllamaModels(): void {
    this.curedService.getRecommendedModels().subscribe({
      next: (response) => {
        const gpuCategory = this.ocrModelCategories.find(c => c.name === 'Local GPU');
        if (!gpuCategory) return;

        // Append installed Ollama models to existing entries (e.g. Nemotron)
        const existingValues = new Set(gpuCategory.models.map(m => m.value));
        for (const m of response.models) {
          if (!m.installed) continue;
          const value = m.id.replace(/[-:]/g, '_');
          if (existingValues.has(value)) continue;
          gpuCategory.models.push({
            value,
            label: m.name,
            description: m.description,
          });
          this.modelAvailability[value] = true;
        }
      },
      error: () => {}
    });
  }

  private loadPrompts(): void {
    this.http.get<{ prompts: Array<{key: string; value: string}> }>(
      `${environment.apiUrl}/cured/ollama/prompts`
    ).subscribe({
      next: (response) => {
        this.loadedPrompts = response.prompts;
        // Update ocrPromptModes with loaded prompts
        this.ocrPromptModes = response.prompts.map(p => ({
          value: p.key,
          label: this.getPromptLabel(p.key),
          description: this.getPromptDescription(p.key),
        }));
      },
      error: () => {} // Fallback to hardcoded modes
    });
  }

  getPromptLabel(key: string): string {
    const labels: {[k: string]: string} = {
      'plain': 'Plain',
      'markdown': 'Markdown',
      'dictionary': 'Dictionary',
      'cad': 'CAD',
    };
    return labels[key] || key.charAt(0).toUpperCase() + key.slice(1);
  }

  getPromptDescription(key: string): string {
    const descriptions: {[k: string]: string} = {
      'plain': 'Simple text extraction',
      'markdown': 'Formatted with markdown',
      'dictionary': 'Akkadian dictionary entries',
      'cad': 'Chicago Assyrian Dictionary',
    };
    return descriptions[key] || '';
  }

  getSelectedPromptText(): string {
    if (this.selectedPrompt === 'custom') {
      return this.customPromptText;
    }
    const found = this.loadedPrompts.find(p => p.key === this.selectedPrompt);
    return found ? found.value : '';
  }

  startEditingPrompt(): void {
    this.editingPrompt = true;
    this.editPromptValue = this.getSelectedPromptText();
  }

  cancelEditingPrompt(): void {
    this.editingPrompt = false;
  }

  savePrompt(): void {
    if (!this.editPromptValue) return;

    if (this.selectedPrompt === 'custom') {
      this.customPromptText = this.editPromptValue;
      this.editingPrompt = false;
      return;
    }

    this.http.put<any>(
      `${environment.apiUrl}/cured/ollama/prompts/${this.selectedPrompt}`,
      { value: this.editPromptValue }
    ).subscribe({
      next: () => {
        // Update local cache
        const found = this.loadedPrompts.find(p => p.key === this.selectedPrompt);
        if (found) {
          found.value = this.editPromptValue;
        }
        this.editingPrompt = false;
        this.notificationService.showSuccess('Prompt saved');
      },
      error: () => {
        this.notificationService.showError('Failed to save prompt');
      }
    });
  }

  createPrompt(): void {
    const key = this.newPromptName.trim().toLowerCase().replace(/\s+/g, '_');
    const value = this.newPromptText.trim();
    if (!key || !value) return;

    this.creatingPrompt = true;
    this.http.post<any>(
      `${environment.apiUrl}/cured/ollama/prompts`, { key, value }
    ).subscribe({
      next: () => {
        this.loadedPrompts.push({ key, value, builtin: false });
        this.ocrPromptModes.push({
          value: key,
          label: this.getPromptLabel(key),
          description: '',
        });
        this.selectedPrompt = key;
        this.newPromptName = '';
        this.newPromptText = '';
        this.showNewPromptForm = false;
        this.creatingPrompt = false;
        this.notificationService.showSuccess('Prompt created');
      },
      error: (err) => {
        this.creatingPrompt = false;
        this.notificationService.showError(err.error?.detail || 'Failed to create prompt');
      }
    });
  }

  deletePrompt(): void {
    const prompt = this.loadedPrompts.find(p => p.key === this.selectedPrompt);
    if (!prompt || prompt.builtin) return;

    this.http.delete<any>(
      `${environment.apiUrl}/cured/ollama/prompts/${this.selectedPrompt}`
    ).subscribe({
      next: () => {
        this.loadedPrompts = this.loadedPrompts.filter(p => p.key !== this.selectedPrompt);
        this.ocrPromptModes = this.ocrPromptModes.filter(m => m.value !== this.selectedPrompt);
        this.selectedPrompt = 'dictionary';
        this.editingPrompt = false;
        this.notificationService.showSuccess('Prompt deleted');
      },
      error: (err) => {
        this.notificationService.showError(err.error?.detail || 'Failed to delete prompt');
      }
    });
  }

  isCustomPromptSelected(): boolean {
    const prompt = this.loadedPrompts.find(p => p.key === this.selectedPrompt);
    return !!prompt && !prompt.builtin;
  }

  // ============== Batch Job Control ==============

  // Keep in sync with server's ThreadPoolExecutor(max_workers=...) in
  // batch_recognition_handler.py. Server-side is the real cap; this only
  // guards the UI against queueing past the worker pool size.
  public static readonly MAX_CONCURRENT_BATCHES = 20;

  get canStart(): boolean {
    return !this.startBlockedReason && !this.isStarting;
  }

  /** Why the Start button is disabled (shown under it), or '' when ready. */
  get startBlockedReason(): string {
    if (!this.hasSource) return 'Select a source: Browse Server or Browse Computer (left panel)';
    if (!this.selectedModel) return 'Select a model';
    if (this.requiresApiKey() && !this.apiKey) return 'Enter an API key';
    if (this.selectedPrompt === 'custom' && !(this.customPromptText || '').trim()) return 'Enter a custom prompt';
    if (this.activeJobIds.size >= BatchRecognitionComponent.MAX_CONCURRENT_BATCHES) {
      return `${BatchRecognitionComponent.MAX_CONCURRENT_BATCHES} jobs already running`;
    }
    return '';
  }

  get isRunning(): boolean {
    return this.activeJobIds.size > 0;
  }

  get activeJobCount(): number {
    return this.activeJobIds.size;
  }

  startBatch(): void {
    if (!this.canStart) return;

    if (!this.hasDestination) {
      const dialogRef = this.dialog.open(ConfirmDialogComponent, {
        data: {
          title: 'No Destination Dataset',
          message: 'No destination dataset selected. Resulting texts will be unassigned and won\'t appear under any dataset in CuReD. Continue anyway?',
          confirmText: 'Start Anyway',
          cancelText: 'Cancel',
          warn: true
        }
      });
      dialogRef.afterClosed().subscribe(confirmed => {
        if (confirmed) {
          this._doStartBatch();
        }
      });
      return;
    }

    this._doStartBatch();
  }

  private _doStartBatch(): void {
    // Save API key if provided
    if (this.apiKey && this.requiresApiKey()) {
      localStorage.setItem('ocr_api_key_' + this.selectedModel, this.apiKey);
    }

    this.isStarting = true;

    // Only send include_classes if not all classes are selected (i.e., user filtered some out)
    const includeClasses = this.availableClasses.length > 0 && this.selectedClasses.size < this.availableClasses.length
      ? Array.from(this.selectedClasses)
      : undefined;

    // Only send include_filenames if user selected specific files (not all)
    const includeFilenames = this.showFileSelector && this.selectedFilenames.size < this.allFilenames.length
      ? Array.from(this.selectedFilenames)
      : undefined;

    const base: BatchRecognitionRequest = {
      destination_dataset_id: this.destinationMode === 'library' && this.destinationDatasetId ? this.destinationDatasetId : undefined,
      destination_folder_path: this.destinationMode === 'export' && this.destinationFolderPath ? this.destinationFolderPath : undefined,
      export_images: this.destinationMode === 'export' ? this.exportImages : undefined,
      model: this.selectedModel,
      prompt: this.selectedPrompt === 'custom' ? 'plain' : this.selectedPrompt,
      custom_prompt: this.selectedPrompt === 'custom' ? this.customPromptText : undefined,
      api_key: this.apiKey || undefined,
      sub_model: this.selectedSubModel || undefined,
      batch_size: this.batchMode === 'dynamic' ? -1 : Math.max(1, this.batchSize || 1),
      correction_rules: this.correctionRules || undefined,
      image_scale: this.imageScale < 1.0 ? this.imageScale : undefined,
      target_dpi: this.targetDpi || undefined,
      box_mode: this.boxMode || undefined,
      tiling_mode: this.tilingMode,
      execution_mode: this.supportsBatchApi() ? this.executionMode : 'live',
    };

    const requests = this.sourceMode === 'library'
      ? [{ ...base, source_project_id: this.sourceProjectId, include_classes: includeClasses, include_filenames: includeFilenames }]
      : this.buildLocalRequests(base);
    this.submitBatchRequests(requests);
  }

  /** One request per local folder, limited to the files left after the class and checklist filters. */
  private buildLocalRequests(base: BatchRecognitionRequest): BatchRecognitionRequest[] {
    const classFiltered = this.availableClasses.length > 0 && this.selectedClasses.size < this.availableClasses.length;
    const requests: BatchRecognitionRequest[] = [];
    for (const src of this.localSources) {
      const files = src.files.filter(f =>
        (!classFiltered || this.selectedClasses.has(this.extractClassName(f)))
        && (!this.showFileSelector || this.selectedFilenames.has(this.localKey(src.path, f))));
      // Never send an empty list: the backend reads "no include_filenames" as "whole folder"
      if (files.length) {
        requests.push({ ...base, source_folder_path: src.path, include_filenames: files });
      }
    }
    return requests;
  }

  private submitBatchRequests(requests: BatchRecognitionRequest[]): void {
    if (requests.length === 0) {
      this.isStarting = false;
      this.notificationService.showError('No files selected');
      return;
    }
    let pending = requests.length;
    const done = () => { if (--pending === 0) { this.isStarting = false; } };
    for (const request of requests) {
      const folder = request.source_folder_path ? request.source_folder_path.split(/[/\\]/).pop() + ': ' : '';
      const prefix = requests.length > 1 ? folder : '';
      this.batchService.startBatch(request).subscribe({
        next: (response) => {
          done();
          if (response.success) {
            this.activeJobIds.add(response.job_id);
            this.selectedJobId = response.job_id;
            this.rightTab = 'report';
            this.notificationService.showInfo(
              `${prefix}Batch started: ${response.total_images} images with ${this.selectedModel}`
            );
            this.startPoll(response.job_id);
          } else {
            this.notificationService.showError(prefix + response.message);
          }
        },
        error: (err) => {
          done();
          this.notificationService.showError(`${prefix}Failed to start batch: ` + (err.error?.message || err.message));
        }
      });
    }
  }

  // ============== Recover provider batches ==============

  toggleRecoverPanel(): void {
    this.showRecoverPanel = !this.showRecoverPanel;
    if (this.showRecoverPanel) {
      this.loadProviderBatches();
    }
  }

  loadProviderBatches(): void {
    if (!this.apiKey) return;
    this.loadingProviderBatches = true;
    this.batchService.listProviderBatches(this.selectedModel, this.apiKey)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (res) => {
          this.loadingProviderBatches = false;
          this.providerBatches = res.batches;
          if (!res.success) {
            this.notificationService.showError('Could not list provider batches: ' + res.message);
          }
        },
        error: (err) => {
          this.loadingProviderBatches = false;
          this.notificationService.showError('Could not list provider batches: ' + (err.error?.message || err.message));
        },
      });
  }

  /** Re-attach a provider batch as a local job, using the source/destination selected on the left. */
  recoverProviderBatch(batch: ProviderBatch): void {
    if (!this.hasSource) {
      this.notificationService.showError('First select the source the batch was submitted from (Browse Server or Browse Computer)');
      return;
    }
    if (this.sourceMode === 'local' && this.localSources.length !== 1) {
      this.notificationService.showError('Recovery needs exactly one source folder (the one the batch was submitted from)');
      return;
    }
    this.recoveringBatchId = batch.id;
    this.batchService.recoverBatch({
      model: this.selectedSubModel && !this.selectedSubModel.startsWith('latest:')
        ? `${this.selectedModel}:${this.selectedSubModel}` : this.selectedModel,
      api_key: this.apiKey,
      provider_batch_ids: [batch.id],
      source_project_id: this.sourceMode === 'library' ? this.sourceProjectId : undefined,
      source_folder_path: this.sourceMode === 'local' ? this.localSources[0].path : undefined,
      destination_dataset_id: this.destinationMode === 'library' && this.destinationDatasetId ? this.destinationDatasetId : undefined,
      destination_folder_path: this.destinationMode === 'export' && this.destinationFolderPath ? this.destinationFolderPath : undefined,
      export_images: this.destinationMode === 'export' ? this.exportImages : undefined,
      box_mode: this.boxMode || undefined,
      correction_rules: this.correctionRules || undefined,
    }).subscribe({
      next: (res) => {
        this.recoveringBatchId = null;
        if (!res.success) {
          this.notificationService.showError(res.message);
          return;
        }
        this.notificationService.showInfo(res.message);
        this.activeJobIds.add(res.job_id);
        this.selectedJobId = res.job_id;
        this.rightTab = 'report';
        this.startPoll(res.job_id);
        this.loadRecentJobs();
        this.loadProviderBatches();
      },
      error: (err) => {
        this.recoveringBatchId = null;
        this.notificationService.showError('Recovery failed: ' + (err.error?.message || err.message));
      },
    });
  }

  cancelBatch(jobId?: string): void {
    const id = jobId || this.selectedJobId;
    if (!id) return;
    this.batchService.cancelJob(id).subscribe({
      next: (result) => {
        if (result.success) {
          this.notificationService.showInfo('Cancellation requested');
        } else {
          this.notificationService.showError(result.message);
        }
      },
      error: () => {
        this.notificationService.showError('Failed to cancel job');
      }
    });
  }

  // ============== Polling ==============

  private startPoll(jobId: string): void {
    // Stop existing poll for this job if any
    this.stopPoll(jobId);
    let lastFetch = 0;
    const sub = interval(2000).pipe(
      // A provider batch can wait for hours: check it every 30s instead of every 2s.
      filter(() => this.jobStatuses.get(jobId)?.status !== 'batch_submitted' || Date.now() - lastFetch >= 30000),
      tap(() => lastFetch = Date.now()),
      switchMap(() => this.batchService.getJobStatus(jobId)),
      takeUntil(this.destroy$),
    ).subscribe({
      next: (status) => {
        this.jobStatuses.set(jobId, status);
        if (status.status === 'completed') {
          this.stopPoll(jobId);
          this.activeJobIds.delete(jobId);
          this.notificationService.showSuccess(
            `Batch complete: ${status.processed_images} pages processed, ${status.failed_images} failed`
          );
          this.loadRecentJobs();
        } else if (status.status === 'rate_limited') {
          this.stopPoll(jobId);
          this.activeJobIds.delete(jobId);
          const resetMsg = status.rate_limit_reset
            ? ` Try again after ${new Date(status.rate_limit_reset).toLocaleTimeString()}.`
            : '';
          this.notificationService.showError(
            `Batch stopped: API rate limit reached (${status.processed_images} pages processed).${resetMsg}`
          );
          this.loadRecentJobs();
        } else if (status.status === 'failed') {
          this.stopPoll(jobId);
          this.activeJobIds.delete(jobId);
          this.notificationService.showError(`Batch failed: ${status.error}`);
          this.loadRecentJobs();
        } else if (status.status === 'cancelled') {
          this.stopPoll(jobId);
          this.activeJobIds.delete(jobId);
          this.notificationService.showInfo(
            `Batch cancelled: ${status.processed_images} pages processed before cancellation`
          );
          this.loadRecentJobs();
        }
      },
      error: () => {
        this.stopPoll(jobId);
        this.activeJobIds.delete(jobId);
      }
    });
    this.pollSubs.set(jobId, sub);
  }

  private stopPoll(jobId: string): void {
    const sub = this.pollSubs.get(jobId);
    if (sub) {
      sub.unsubscribe();
      this.pollSubs.delete(jobId);
    }
  }

  private stopAllPolls(): void {
    this.pollSubs.forEach(sub => sub.unsubscribe());
    this.pollSubs.clear();
  }

  // ============== Recent Jobs ==============

  private loadRecentJobs(): void {
    this.batchService.listJobs(10).subscribe({
      next: (jobs) => {
        this.recentJobs = jobs;

        // Auto-resume polling for any active jobs (e.g. after page reload).
        // Includes async Batch API states so a submitted batch keeps updating.
        if (this.activeJobIds.size === 0 && this.pollSubs.size === 0) {
          const activeJobs = jobs.filter(j => this.isActiveStatus(j.status));
          for (const job of activeJobs) {
            this.activeJobIds.add(job.job_id);
            this.startPoll(job.job_id);
          }
          if (activeJobs.length > 0 && !this.selectedJobId) {
            this.selectedJobId = activeJobs[0].job_id;
          }
        }
      },
      error: () => {}
    });
  }

  viewJobReport(jobId: string): void {
    this.selectedJobId = jobId;
    this.rightTab = 'report';
    // If already tracking this job, just select it
    if (this.jobStatuses.has(jobId)) return;

    this.batchService.getJobStatus(jobId).subscribe({
      next: (status) => {
        this.jobStatuses.set(jobId, status);
        // If still active (incl. async batch states), start polling
        if (this.isActiveStatus(status.status)) {
          this.activeJobIds.add(jobId);
          this.startPoll(jobId);
        }
      },
      error: () => {
        this.notificationService.showError('Failed to load job report');
      }
    });
  }

  /** Active = still progressing; covers live (running/pending) and async Batch API states. */
  isActiveStatus(status: string): boolean {
    return ['running', 'pending', 'submitting', 'batch_submitted', 'collecting'].includes(status);
  }

  getStatusIcon(status: string): string {
    switch (status) {
      case 'completed': return 'check_circle';
      case 'failed': return 'error';
      case 'rate_limited': return 'speed';
      case 'cancelled': return 'cancel';
      case 'running': return 'hourglass_empty';
      case 'pending': return 'schedule';
      case 'submitting': return 'cloud_upload';
      case 'batch_submitted': return 'cloud_sync';
      case 'collecting': return 'cloud_download';
      default: return 'help';
    }
  }

  /** Human-readable label for a status chip. */
  getStatusLabel(status: string): string {
    switch (status) {
      case 'batch_submitted': return 'Waiting on provider';
      case 'submitting': return 'Submitting';
      case 'collecting': return 'Collecting';
      case 'rate_limited': return 'Rate limited';
      default: return status.charAt(0).toUpperCase() + status.slice(1);
    }
  }

  get selectedJobStatus(): BatchRecognitionStatus | null {
    if (!this.selectedJobId) return null;
    return this.jobStatuses.get(this.selectedJobId) || null;
  }

  getStatusColor(status: string): string {
    switch (status) {
      case 'completed': return '#4caf50';
      case 'failed': return '#f44336';
      case 'rate_limited': return '#ff5722';
      case 'cancelled': return '#ff9800';
      case 'running': return '#2196f3';
      case 'submitting': return '#7e57c2';
      case 'batch_submitted': return '#7e57c2';
      case 'collecting': return '#7e57c2';
      default: return '#9e9e9e';
    }
  }

  // ============== Report Tab ==============

  get reportStatus(): BatchRecognitionStatus | null {
    if (!this.selectedJobId) return null;
    return this.jobStatuses.get(this.selectedJobId) || null;
  }

  getDuration(startedAt: string, completedAt: string): string {
    const start = new Date(startedAt).getTime();
    const end = new Date(completedAt).getTime();
    const seconds = Math.round((end - start) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (minutes < 60) return `${minutes}m ${secs}s`;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m`;
  }

  getDynamicTotal(report: Array<any>, field: string): number {
    return report.reduce((sum: number, cat: any) => sum + (cat[field] || 0), 0);
  }

  getCuredLink(r: { text_id: number; transliteration_id: number }): string {
    return `/cured?textId=${r.text_id}&transId=${r.transliteration_id}`;
  }

  // ============== Usage Tab ==============

  loadUsage(): void {
    this.batchService.getUsage(14).subscribe({
      next: (data) => { this.usageData = data; },
      error: () => {}
    });
  }

  getUsageModels(entry: any): string[] {
    return Object.keys(entry.models || {});
  }

  /** Sum of the day's estimated costs (models without a known price are skipped). */
  getDayCost(entry: any): number {
    return Object.values(entry.models || {}).reduce((sum: number, m: any) => sum + (m.cost_usd || 0), 0) as number;
  }

  formatCost(usd: number): string {
    if (usd === 0) return '$0';
    if (usd < 0.01) return '<$0.01';
    return '$' + usd.toFixed(usd < 1 ? 3 : 2);
  }

  formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  formatTokens(tokens: number): string {
    if (tokens < 1000) return tokens.toString();
    if (tokens < 1000000) return (tokens / 1000).toFixed(1) + 'K';
    return (tokens / 1000000).toFixed(2) + 'M';
  }

  getTodayInferences(): number {
    const today = new Date().toISOString().slice(0, 10);
    const entry = this.usageData.find(d => d.date === today);
    if (!entry) return 0;
    return Object.values(entry.models).reduce((sum, m) => sum + m.inferences, 0);
  }

  // ============== Tile Marker Cleanup ==============

  removingMarkers = false;

  hasTiledResults(status: any): boolean {
    return status?.results?.some((r: any) => r.was_tiled) || false;
  }

  removeTileMarkers(status: any): void {
    if (!status?.results) { return; }
    const textIds = status.results
      .filter((r: any) => r.was_tiled)
      .map((r: any) => r.text_id);
    if (!textIds.length) { return; }

    this.removingMarkers = true;
    this.curedService.removeTileMarkers(undefined, textIds).subscribe({
      next: (result) => {
        this.removingMarkers = false;
        alert(`Cleaned ${result.cleaned} texts, removed ${result.total_markers_removed} marker lines.`);
      },
      error: (err) => {
        this.removingMarkers = false;
        console.error('Failed to remove tile markers:', err);
        alert('Failed to remove tile markers.');
      },
    });
  }

  // ============== Continue Truncated Batch ==============

  continueBatch(jobId: string): void {
    // Get job status (may need to fetch it)
    const status = this.jobStatuses.get(jobId);
    if (status) {
      this._doContinueBatch(status);
    } else {
      this.batchService.getJobStatus(jobId).subscribe({
        next: (s) => {
          this.jobStatuses.set(jobId, s);
          this._doContinueBatch(s);
        },
        error: () => {
          this.notificationService.showError('Failed to load job details');
        }
      });
    }
  }

  private _doContinueBatch(prevJob: BatchRecognitionStatus): void {
    const processedFilenames = (prevJob.results || []).map(r => r.filename);
    if (processedFilenames.length === 0 && prevJob.processed_images === 0) {
      this.notificationService.showInfo('No images were processed in the previous job — starting fresh');
    }

    // Parse model and sub_model from effective_model (format: "model:sub_model" or just "model")
    const effectiveModel = prevJob.effective_model || prevJob.model;
    const parts = effectiveModel.split(':');
    const model = parts[0];
    const subModel = parts.length > 1 ? parts.slice(1).join(':') : undefined;

    const remaining = prevJob.total_images - processedFilenames.length;

    const request: BatchRecognitionRequest = {
      source_project_id: prevJob.source_project_id,
      source_folder_path: prevJob.source_folder_path,
      include_classes: prevJob.include_classes,
      destination_dataset_id: prevJob.destination_dataset_id,
      destination_folder_path: prevJob.destination_folder_path,
      export_images: prevJob.export_images,
      model: model,
      prompt: prevJob.prompt,
      api_key: this.apiKey || localStorage.getItem('ocr_api_key_' + model) || undefined,
      sub_model: subModel,
      batch_size: prevJob.batch_size != null ? prevJob.batch_size : 1,
      correction_rules: prevJob.correction_rules,
      image_scale: prevJob.image_scale ?? undefined,
      target_dpi: prevJob.target_dpi ?? undefined,
      box_mode: prevJob.box_mode || undefined,
      exclude_filenames: processedFilenames.length > 0 ? processedFilenames : undefined,
      execution_mode: prevJob.execution_mode || 'live',
    };

    this.isStarting = true;
    this.batchService.startBatch(request).subscribe({
      next: (response) => {
        this.isStarting = false;
        if (response.success) {
          this.activeJobIds.add(response.job_id);
          this.selectedJobId = response.job_id;
          this.rightTab = 'report';
          this.notificationService.showInfo(
            `Continuing batch: ${response.total_images} remaining (${processedFilenames.length} already processed)`
          );
          this.startPoll(response.job_id);
        } else {
          this.notificationService.showError(response.message);
        }
      },
      error: (err) => {
        this.isStarting = false;
        this.notificationService.showError('Failed to continue batch: ' + (err.error?.message || err.message));
      }
    });
  }
}
