import { Component, OnInit, OnDestroy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { MatDialog } from '@angular/material/dialog';
import { Subject, Subscription, interval } from 'rxjs';
import { switchMap, takeUntil } from 'rxjs/operators';

import { environment } from '../../../environments/environment';
import { BatchRecognitionService } from '../../services/batch-recognition.service';
import { CuredService } from '../../services/cured.service';
import { PagesService } from '../../services/pages.service';
import { DatasetService } from '../../services/dataset.service';
import { NotificationService } from '../../services/notification.service';
import { FolderPickerDialogComponent, FolderPickerResult } from '../common/folder-picker-dialog/folder-picker-dialog.component';
import { ConfirmDialogComponent } from '../common/confirm-dialog/confirm-dialog.component';
import {
  BatchRecognitionRequest,
  BatchRecognitionStatus,
  BatchRecognitionJobSummary,
  VllmStatus,
} from '../../models/batch-recognition';
import { DatasetPreview } from '../../models/cured';

type SourceMode = 'library' | 'local';
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

  // Local folder source (via Upload Folder button)
  localFolderPath: string = '';
  localFolderName: string = '';
  localFolderImageCount: number = 0;

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

  apiSubModels: { [key: string]: Array<{value: string; label: string; description: string}> } = {
    'gemini_vision': [
      { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash', description: 'Fast, free tier' },
      { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite', description: 'Cost efficient' },
      { value: 'gemini-3.1-flash-lite-preview', label: 'Gemini 3.1 Flash-Lite', description: 'Latest multimodal' },
      { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro', description: 'Most capable' },
    ],
    'claude_vision': [
      { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5', description: 'Fastest, cheapest' },
      { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5', description: 'Balanced' },
      { value: 'claude-opus-4-6', label: 'Claude Opus 4.6', description: 'Most intelligent' },
    ],
    'gpt4_vision': [
      { value: 'gpt-4o', label: 'GPT-4o', description: 'Omni, vision capable' },
      { value: 'gpt-4o-mini', label: 'GPT-4o Mini', description: 'Faster, cheaper' },
      { value: 'gpt-4.1', label: 'GPT-4.1', description: 'Best for coding' },
    ],
  };

  ocrModelCategories: Array<{
    name: string;
    models: Array<{value: string; label: string; description?: string}>;
  }> = [
    {
      name: 'CPU',
      models: [
        { value: 'kraken_typewriter', label: 'Typewriter', description: 'Pennsylvania Sumerian Dictionary' },
        { value: 'kraken_base', label: 'Base (SAA)', description: 'SAA Corpus' },
        { value: 'kraken_cusas', label: 'CUSAS-18', description: 'CUSAS-18 trained model' },
        { value: 'trocr', label: 'TrOCR Base', description: 'Line-level handwritten OCR' },
        // Additional trained models are loaded dynamically from the backend
      ]
    },
    {
      name: 'Local GPU',
      models: [
        { value: 'nemotron_local', label: 'Nemotron', description: 'Document parsing (8GB)' },
        { value: 'deepseek_ocr', label: 'DeepSeek', description: 'Fast OCR' },
        { value: 'qwen3_vl_4b', label: 'Qwen3 VL 4B', description: '2.5GB, fast' },
        { value: 'qwen3_vl_8b', label: 'Qwen3 VL 8B', description: '6GB, best OCR' },
        { value: 'qwen3_vl_32b', label: 'Qwen3 VL 32B', description: '21GB, highest quality' },
        { value: 'llama4_vision', label: 'Llama 4', description: '12GB, most capable' },
        { value: 'mistral_small_vision', label: 'Mistral Small', description: '15GB, vision' },
        { value: 'llava_34b', label: 'LLaVA 34B', description: '20GB, specialist' },
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
      name: 'vLLM',
      models: []  // Populated dynamically from vLLM server
    },
    {
      name: 'API',
      models: [
        { value: 'nemotron_cloud', label: 'Nemotron', description: 'NVIDIA Build' },
        { value: 'gpt4_vision', label: 'GPT-4 Vision', description: 'OpenAI' },
        { value: 'claude_vision', label: 'Claude Vision', description: 'Anthropic' },
        { value: 'gemini_vision', label: 'Gemini Vision', description: 'Google' },
      ]
    }
  ];

  modelAvailability: { [key: string]: boolean } = {
    'kraken_typewriter': true,
    'kraken_base': true,
    'kraken_cusas': true,
    'trocr': true,
    'nemotron_local': true,
    'deepseek_ocr': true,
    'llama4_vision': false,
    'qwen3_vl_32b': false,
    'qwen3_vl_8b': false,
    'qwen3_vl_4b': false,
    'mistral_small_vision': false,
    'llava_34b': false,
    'qwen3_vl_235b_cloud': true,
    'qwen3_vl_235b_thinking': true,
    'nemotron_cloud': true,
    'gpt4_vision': true,
    'claude_vision': true,
    'gemini_vision': true,
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

  // Image scale (null = use global setting from Settings)
  imageScale: number | null = null;
  imageScaleOptions: Array<{value: number | null; label: string}> = [
    { value: null, label: 'Global Setting' },
    { value: 1.0, label: '600 DPI (Full)' },
    { value: 0.75, label: '450 DPI' },
    { value: 0.5, label: '300 DPI' },
    { value: 0.33, label: '200 DPI' },
  ];

  // Batch config — "dynamic" = size-based batching, "fixed" = user-specified batch size
  batchMode: 'dynamic' | 'fixed' = 'fixed';
  batchSize: number = 0;

  // Right panel tab
  rightTab: 'settings' | 'report' = 'settings';

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
    this.loadVllmModels();
    this.loadPrompts();
    this.loadCuredDatasets();
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
        this.localFolderPath = '';
        this.localFolderName = '';
        this.localFolderImageCount = 0;
        this.detectClassesFromLibrary(result.project_id);
      }
    });
  }

  handleFolderInput(event: any): void {
    const files: FileList = event.target.files;
    if (!files || files.length === 0) return;

    const supportedExts = ['.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp'];
    let imageCount = 0;
    let folderPath = '';
    const imageNames: string[] = [];

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const name = file.name.toLowerCase();
      if (supportedExts.some(ext => name.endsWith(ext))) {
        imageCount++;
        imageNames.push(file.name);
        // In Electron, File objects have a .path property with the full filesystem path
        if (!folderPath && (file as any).path) {
          const fullPath: string = (file as any).path;
          // Extract the folder path (parent of the file)
          const sep = fullPath.includes('\\') ? '\\' : '/';
          folderPath = fullPath.substring(0, fullPath.lastIndexOf(sep));
        }
      }
    }

    // Reset the input so the same folder can be re-selected
    event.target.value = '';

    if (imageCount === 0) {
      this.notificationService.showError('No supported image files found (PNG, JPG, TIFF, BMP, WebP)');
      return;
    }

    if (!folderPath) {
      this.notificationService.showError('Could not determine folder path. This feature requires the desktop app.');
      return;
    }

    this.sourceMode = 'local';
    this.localFolderPath = folderPath;
    this.localFolderName = folderPath.split(/[/\\]/).pop() || folderPath;
    this.localFolderImageCount = imageCount;
    this.sourceProjectId = '';
    this.sourceProjectName = '';
    this.detectClassesFromFilenames(imageNames);

    this.notificationService.showInfo(`Selected folder: ${this.localFolderName} (${imageCount} images)`);
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
    this.localFolderPath = '';
    this.localFolderName = '';
    this.localFolderImageCount = 0;
    this.availableClasses = [];
    this.selectedClasses = new Set();
    this.allFilenames = [];
    this.selectedFilenames = new Set();
    this.showFileSelector = false;
    this.fileFilter = '';
  }

  get hasSource(): boolean {
    return !!this.sourceProjectId || !!this.localFolderPath;
  }

  get sourceDisplayName(): string {
    if (this.sourceMode === 'library') return this.sourceProjectName;
    return this.localFolderName;
  }

  // ============== Class Filtering ==============

  private extractClassName(filename: string): string {
    // Extract class from YOLO snippet filename: "ahw-d-0001-005-mainEntry.png" → "mainEntry"
    const stem = filename.replace(/\.[^/.]+$/, ''); // remove extension
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
    return this.allFilenames.filter(f => f.toLowerCase().includes(q));
  }

  toggleFileSelector(): void {
    this.showFileSelector = !this.showFileSelector;
    if (!this.showFileSelector) {
      // When hiding, reset to all selected
      this.selectedFilenames = new Set(this.allFilenames);
      this.fileFilter = '';
    }
  }

  toggleFile(filename: string): void {
    if (this.selectedFilenames.has(filename)) {
      this.selectedFilenames.delete(filename);
    } else {
      this.selectedFilenames.add(filename);
    }
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
    }
  }

  isModelAvailable(modelValue: string): boolean {
    return this.modelAvailability[modelValue] ?? false;
  }

  requiresApiKey(): boolean {
    const apiModels = ['nemotron_cloud', 'gpt4_vision', 'claude_vision', 'gemini_vision'];
    return apiModels.includes(this.selectedModel) && !this.selectedModel.startsWith('vllm');
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

        // Base models already hardcoded (typewriter, base, cusas)
        const hardcodedValues = new Set(cpuCategory.models.map(m => m.value));

        for (const model of response.models) {
          // Add Kraken, Qwen LoRA, and TrOCR models that aren't already in the list
          if ((model.value.startsWith('kraken:') || model.value.startsWith('qwen_lora:') || model.value.startsWith('trocr:')) && !hardcodedValues.has(model.value)) {
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
    this.curedService.getOllamaModels().subscribe({
      next: (models) => {
        const ollamaModelMap: { [key: string]: string } = {
          'llama4_vision': 'x/llama4-maverick',
          'qwen3_vl_32b': 'qwen3-vl:32b',
          'qwen3_vl_8b': 'qwen3-vl:8b',
          'qwen3_vl_4b': 'qwen3-vl:4b',
          'mistral_small_vision': 'mistral-small3.1',
          'llava_34b': 'llava:34b',
        };
        for (const [key, ollamaName] of Object.entries(ollamaModelMap)) {
          this.modelAvailability[key] = models.some(m => m.includes(ollamaName));
        }
      },
      error: () => {}
    });
  }

  private loadVllmModels(): void {
    this.batchService.getVllmStatus().subscribe({
      next: (status: VllmStatus) => {
        const vllmCategory = this.ocrModelCategories.find(c => c.name === 'vLLM');
        if (!vllmCategory || !status.available) return;

        vllmCategory.models = status.models.map(modelId => ({
          value: `vllm:${modelId}`,
          label: modelId,
          description: 'vLLM server',
        }));

        for (const model of vllmCategory.models) {
          this.modelAvailability[model.value] = true;
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
      'tei_lex0': 'TEI Lex-0',
    };
    return labels[key] || key.charAt(0).toUpperCase() + key.slice(1);
  }

  getPromptDescription(key: string): string {
    const descriptions: {[k: string]: string} = {
      'plain': 'Simple text extraction',
      'markdown': 'Formatted with markdown',
      'dictionary': 'Akkadian dictionary entries',
      'tei_lex0': 'TEI Lex-0 XML encoding',
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

  get canStart(): boolean {
    return this.hasSource
      && !!this.selectedModel
      && !this.isStarting
      && this.activeJobIds.size < 3
      && (!this.requiresApiKey() || !!this.apiKey)
      && (this.selectedPrompt !== 'custom' || !!this.customPromptText.trim());
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

    const request: BatchRecognitionRequest = {
      source_project_id: this.sourceMode === 'library' ? this.sourceProjectId : undefined,
      source_folder_path: this.sourceMode === 'local' ? this.localFolderPath : undefined,
      include_classes: includeClasses,
      include_filenames: includeFilenames,
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
      image_scale: this.imageScale ?? undefined,
    };

    this.batchService.startBatch(request).subscribe({
      next: (response) => {
        this.isStarting = false;
        if (response.success) {
          this.activeJobIds.add(response.job_id);
          this.selectedJobId = response.job_id;
          this.rightTab = 'report';
          this.notificationService.showInfo(
            `Batch started: ${response.total_images} images with ${this.selectedModel}`
          );
          this.startPoll(response.job_id);
        } else {
          this.notificationService.showError(response.message);
        }
      },
      error: (err) => {
        this.isStarting = false;
        this.notificationService.showError('Failed to start batch: ' + (err.error?.message || err.message));
      }
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
    const sub = interval(2000).pipe(
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

        // Auto-resume polling for any running/pending jobs (e.g. after page reload)
        if (this.activeJobIds.size === 0 && this.pollSubs.size === 0) {
          const activeJobs = jobs.filter(j => j.status === 'running' || j.status === 'pending');
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
        // If still running/pending, start polling
        if (status.status === 'running' || status.status === 'pending') {
          this.activeJobIds.add(jobId);
          this.startPoll(jobId);
        }
      },
      error: () => {
        this.notificationService.showError('Failed to load job report');
      }
    });
  }

  getStatusIcon(status: string): string {
    switch (status) {
      case 'completed': return 'check_circle';
      case 'failed': return 'error';
      case 'cancelled': return 'cancel';
      case 'running': return 'hourglass_empty';
      case 'pending': return 'schedule';
      default: return 'help';
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
      case 'cancelled': return '#ff9800';
      case 'running': return '#2196f3';
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

  getDynamicTotal(report: Array<{ image_count: number; chunks: number }>, field: 'image_count' | 'chunks'): number {
    return report.reduce((sum, cat) => sum + cat[field], 0);
  }

  getCuredLink(r: { text_id: number; transliteration_id: number }): string {
    return `/cured?textId=${r.text_id}&transId=${r.transliteration_id}`;
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
      exclude_filenames: processedFilenames.length > 0 ? processedFilenames : undefined,
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
