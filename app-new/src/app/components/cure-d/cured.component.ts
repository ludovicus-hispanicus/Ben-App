import { AfterViewInit, Component, EventEmitter, HostListener, OnInit, OnDestroy, Output, ViewChild } from '@angular/core';
import { MatMenuTrigger } from '@angular/material/menu';
import { Image as FabricImage, Rect } from 'fabric/fabric-impl';
import { PDFDocumentProxy } from 'ng2-pdf-viewer';
import { Dimensions, Index, Letter, LetterHover, RectData, TeiEntryResult } from 'src/app/models/letter';
import { CuredService, TranslationLookupResult } from 'src/app/services/cured.service';
import { NotificationService } from 'src/app/services/notification.service';
import { CanvasMode, CanvasType, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';
import { saveAs } from 'file-saver';
import { TextEditorComponent } from './text-editor/text-editor.component';
import { MatDialog } from '@angular/material/dialog';
import { TextCreatorComponent } from '../common/text-creator/text-creator.component';
import { SaveDialogComponent, SaveDialogResult } from '../common/save-dialog/save-dialog.component';
import { ConfirmDialogComponent } from '../common/confirm-dialog/confirm-dialog.component';
import { LabelDialogComponent } from '../common/label-dialog/label-dialog.component';
import { IdentifierDialogComponent, IdentifierDialogResult } from '../common/identifier-dialog/identifier-dialog.component';
import { ImageBrowserDialogComponent } from '../common/image-browser-dialog/image-browser-dialog.component';
import { SelectedPage } from '../../models/pages';
import { HttpClient } from '@angular/common/http';
import { AuthService } from 'src/app/auth/auth.service';
import { Location } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { ToolbarService } from 'src/app/services/toolbar.service';
import { AtfConverterService } from 'src/app/services/atf-converter.service';
import { TextService } from 'src/app/services/text.service';
import { ProjectService } from 'src/app/services/project.service';
import { TextPreview, ProjectPreview } from 'src/app/models/cured';
import { DomSanitizer } from '@angular/platform-browser';

export interface ModelInfo {
  name: string;
  isPretrained: boolean;
  sizeMb: number;
  lastModified: string | null;
}

export interface TrainingStatus {
  curatedTexts: number;
  previousLines: number;
  newLines: number;
  totalLines: number;
  requiredForNextTraining: number;
  progress: number; // percentage towards next training
  isReady: boolean;
  lastTraining: string | null;
  currentTraining: any | null;
}

export class SelectedPdf {
  constructor(public pdf: File,
    public page: number) { }
}

@Component({
  selector: 'cured',
  templateUrl: './cured.component.html',
  styleUrls: ['./cured.component.scss']
})
export class CuredComponent implements OnInit, AfterViewInit, OnDestroy {
  // Expose CanvasMode enum for use in template
  public CanvasMode = CanvasMode;

  public options = {
    density: 100,
    saveFilename: "untitled",
    savePath: "./images",
    format: "png",
    width: 600,
    height: 600
  };

  @Output() stageChange = new EventEmitter<number>();
  private _stage = 0;
  get stage(): number { return this._stage; }
  set stage(value: number) {
    this._stage = value;
    this.stageChange.emit(value);
  }

  public pdfSrc = null;
  public pdfFile = null;

  public currentpage = 1;
  public totalPages = 0;
  public pageNumbers: number[] = [];
  public visiblePageNumbers: number[] = [];  // Only the pages currently displayed
  public goToPageInput: number = 1;  // Input field for jumping to a page
  public readonly PAGE_WINDOW_SIZE = 10;  // Number of pages to show at once
  public isCropImage = false;
  public result: SelectedPdf

  public boundingBoxes: Rect[] = [];

  public canvasType: CanvasType = CanvasType.SingleSelection;
  public selectedBox: Rect = null;
  public backgroundImage: string;
  public isLoading: boolean = false;
  public transliterationResult: string[] = null;
  // Stores the crop area used during OCR so Detect Lines can use the same region
  private ocrCropArea: { left: number; top: number; width: number; height: number } | null = null;
  // Reference to the selection box kept on canvas after OCR (non-interactive)
  private ocrSelectionBox: Rect | null = null;
  public isCuratedKraken: boolean = false;
  public isCuratedVlm: boolean = false;

  public goToPage: number = 1;
  public uploadedImageBlob: File = null;

  public textId: number = null;
  public transliterationId: number = null;

  public isLoadedFromServer: boolean = false;

  // Auto-save
  private autoSaveTimer: any = null;
  private readonly AUTO_SAVE_DEBOUNCE_MS = 2000;

  public takeTextId: number;
  public takeTransId: number;

  public viewOnly: boolean = false;
  public highlightQuery: string = null;
  public isDragOver: boolean = false;

  // TEI Lex-0 validation
  public teiValidationResults: TeiEntryResult[] = null;
  public selectedTeiEntry: TeiEntryResult = null;
  public showTeiValidation: boolean = false;

  private popStateSub: { unsubscribe: () => void } = null;
  private suppressPopState: boolean = false;

  // Save dialog
  public isSaving: boolean = false;
  public existingLabels: string[] = [];
  public existingParts: number[] = [];
  public currentLabel: string = '';
  public currentPart: string = '';

  // Resizable panels
  public leftPanelWidth: number = 60; // percentage
  private isResizing: boolean = false;
  private resizeHandler: (e: MouseEvent | TouchEvent) => void;
  private resizeEndHandler: () => void;
  private queryParamsSub: Subscription;

  // Dashboard list (stage 0)
  public curedTexts: TextPreview[] = [];
  public selectedLabelFilter: string | null = null;
  public searchQuery: string = '';
  public sortColumn: string = 'last_modified';
  public sortDirection: 'asc' | 'desc' = 'desc';

  // Project state (flat list)
  public projects: ProjectPreview[] = [];
  public selectedProject: ProjectPreview | null = null;
  public showProjectList: boolean = true;
  public newProjectName: string = '';

  // Translation state
  public hasLinkedTranslation: boolean = false;
  public linkedTranslationLines: string[] = [];
  public showTranslationView: boolean = false;
  public loadingTranslation: boolean = false;
  public currentMuseumName: string = '';
  public currentMuseumNumber: number = 0;
  public currentPNumber: string = '';
  public currentPublicationNumber: string = '';

  // Batch queue (sequential image loading)
  public pendingPages: SelectedPage[] = [];
  public pendingLocalFiles: File[] = [];
  public currentPageIndex: number = 0;

  get hasPendingPages(): boolean {
    const totalPending = this.pendingPages.length + this.pendingLocalFiles.length;
    return totalPending > 1 && this.currentPageIndex < totalPending - 1;
  }

  get batchTotal(): number {
    return this.pendingPages.length + this.pendingLocalFiles.length;
  }

  get isBatchActive(): boolean {
    return this.batchTotal > 1;
  }

  // Model info
  public modelInfo: ModelInfo = {
    name: 'Pre-trained (Default)',
    isPretrained: true,
    sizeMb: 0,
    lastModified: null
  };

  // OCR model selection for inference - organized by category
  private _selectedOcrModel: string = 'kraken_cusas';

  // API Key for cloud providers (GPT-4, Claude, Gemini)
  public apiKey: string = '';

  // Sub-model selection for API providers (e.g., gemini-2.0-flash vs gemini-3-pro)
  public selectedSubModel: string = '';

  // Available sub-models for each API provider
  public apiSubModels: { [key: string]: Array<{value: string; label: string; description: string}> } = {
    'gemini_vision': [
      { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash', description: 'Fast, free tier' },
      { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash-Lite', description: 'Cost efficient' },
      { value: 'gemini-3-flash', label: 'Gemini 3 Flash', description: 'Latest multimodal' },
      { value: 'gemini-3-pro', label: 'Gemini 3 Pro', description: 'Most capable' },
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

  get selectedOcrModel(): string {
    return this._selectedOcrModel;
  }

  set selectedOcrModel(value: string) {
    this._selectedOcrModel = value;
    // Load saved API key for this provider
    this.apiKey = localStorage.getItem('ocr_api_key_' + value) || '';
    // Load saved sub-model for this provider (default to first option)
    if (this.apiSubModels[value]) {
      this.selectedSubModel = localStorage.getItem('ocr_sub_model_' + value) || this.apiSubModels[value][0].value;
    } else {
      this.selectedSubModel = '';
    }
  }

  // Check if current model has sub-model options
  hasSubModels(): boolean {
    return !!this.apiSubModels[this._selectedOcrModel];
  }

  // Save sub-model selection
  onSubModelChange(): void {
    if (this._selectedOcrModel && this.selectedSubModel) {
      localStorage.setItem('ocr_sub_model_' + this._selectedOcrModel, this.selectedSubModel);
    }
  }

  // Get the full model identifier (provider:submodel if applicable)
  getEffectiveModel(): string {
    if (this.selectedSubModel && this.apiSubModels[this._selectedOcrModel]) {
      return `${this._selectedOcrModel}:${this.selectedSubModel}`;
    }
    return this._selectedOcrModel;
  }
  // OCR prompt/mode selection (for VLM models like Ollama)
  public selectedOcrPrompt: string = 'dictionary';
  public ocrPromptModes: Array<{value: string; label: string; description: string}> = [
    { value: 'plain', label: 'Plain', description: 'Simple text extraction' },
    { value: 'markdown', label: 'Markdown', description: 'Formatted with markdown' },
    { value: 'dictionary', label: 'Dictionary', description: 'Akkadian dictionary entries' },
    { value: 'tei_lex0', label: 'TEI Lex-0', description: 'Two-stage: OCR → TEI XML encoding (with XSD validation)' },
  ];

  // TEI encoding model selection (Stage 2 of the two-stage pipeline)
  public selectedTeiModel: string = 'gemini';
  public teiApiKey: string = '';
  public teiEncodingModels: Array<{value: string; label: string; provider: string; model: string; needsApiKey: boolean; description: string}> = [
    { value: 'gemini', label: 'Gemini Flash', provider: 'gemini', model: 'gemini-2.0-flash', needsApiKey: true, description: 'Fast, free tier' },
    { value: 'gemini_pro', label: 'Gemini Pro', provider: 'gemini', model: 'gemini-3-pro', needsApiKey: true, description: 'Most capable' },
    { value: 'claude_haiku', label: 'Claude Haiku', provider: 'anthropic', model: 'claude-haiku-4-5-20251001', needsApiKey: true, description: 'Fast, cheap' },
    { value: 'claude_sonnet', label: 'Claude Sonnet', provider: 'anthropic', model: 'claude-sonnet-4-5-20250929', needsApiKey: true, description: 'Balanced' },
    { value: 'gpt4o_mini', label: 'GPT-4o Mini', provider: 'openai', model: 'gpt-4o-mini', needsApiKey: true, description: 'Fast, cheap' },
    { value: 'qwen3_8b', label: 'Qwen3 8B (local)', provider: 'ollama', model: 'qwen3:8b', needsApiKey: false, description: 'Local, 6GB' },
    { value: 'llama3_8b', label: 'Llama 3.1 8B (local)', provider: 'ollama', model: 'llama3.1:8b', needsApiKey: false, description: 'Local, 5GB' },
  ];

  get selectedTeiModelInfo() {
    return this.teiEncodingModels.find(m => m.value === this.selectedTeiModel);
  }

  get teiModelNeedsApiKey(): boolean {
    return this.selectedTeiModelInfo?.needsApiKey ?? false;
  }

  onTeiModelChange(): void {
    // Load saved API key for this TEI model
    this.teiApiKey = localStorage.getItem('tei_api_key_' + this.selectedTeiModel) || '';
  }

  saveTeiApiKey(): void {
    if (this.teiApiKey && this.selectedTeiModel) {
      localStorage.setItem('tei_api_key_' + this.selectedTeiModel, this.teiApiKey);
    }
  }
  public ocrModelCategories: Array<{
    name: string;
    models: Array<{value: string; label: string; description?: string}>;
  }> = [
    {
      name: 'CPU',
      models: [
        { value: 'kraken_typewriter', label: 'Typewriter', description: 'Pennsylvania Sumerian Dictionary' },
        { value: 'kraken_base', label: 'Base (SAA)', description: 'SAA Corpus' },
        { value: 'kraken_cusas', label: 'CUSAS-18', description: 'CUSAS-18 trained model' },
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
      name: 'API',
      models: [
        { value: 'nemotron_cloud', label: 'Nemotron', description: 'NVIDIA Build' },
        { value: 'gpt4_vision', label: 'GPT-4 Vision', description: 'OpenAI' },
        { value: 'claude_vision', label: 'Claude Vision', description: 'Anthropic' },
        { value: 'gemini_vision', label: 'Gemini Vision', description: 'Google' },
      ]
    }
  ];

  // Available Ollama models from server (for Settings page)
  public availableOllamaModels: string[] = [];
  // Track which models are locally available
  public modelAvailability: { [key: string]: boolean } = {
    // Kraken models
    'kraken_typewriter': true,
    'kraken_base': true,
    'kraken_cusas': true,
    // GPU models - local inference
    'nemotron_local': true,
    'deepseek_ocr': true,
    // Ollama VLM models (need to be pulled)
    'llama4_vision': false,
    'qwen3_vl_32b': false,
    'qwen3_vl_8b': false,
    'qwen3_vl_4b': false,
    'mistral_small_vision': false,
    'llava_34b': false,
    // Ollama Cloud models (always available - runs on Ollama servers)
    'qwen3_vl_235b_cloud': true,
    'qwen3_vl_235b_thinking': true,
    // External API models (always available)
    'nemotron_cloud': true,
    'gpt4_vision': true,
    'claude_vision': true,
    'gemini_vision': true,
  };
  // Legacy support - flat array for backward compatibility
  public availableOcrModels: Array<{value: string; label: string}> = [];

  // Base model selection for training (fine-tune from)
  public selectedBaseModel: string = 'latest';
  public baseModelsMetadata: { [key: string]: { size_mb: number; best_accuracy: number; last_accuracy: number; completed_epochs: number; alphabet_size: number } } = {};

  public trainingStatus: TrainingStatus = {
    curatedTexts: 0,
    previousLines: 0,
    newLines: 0,
    totalLines: 0,
    requiredForNextTraining: 100,
    progress: 0,
    isReady: false,
    lastTraining: null,
    currentTraining: null
  };

  public curatedStats = {
    total: { lines: 0, texts: 0 },
    kraken: { lines: 0, texts: 0 },
    vlm: { lines: 0, texts: 0 },
  };

  // Training state
  public isTraining: boolean = false;
  public trainingProgress: any = null;
  private trainingProgressInterval: any = null;
  public trainingModelName: string = '';
  public epochHistory: Array<{epoch: number; accuracy: number; val_accuracy: number; loss: number}> = [];

  @ViewChild('canvas') canvas: FabricCanvasComponent;
  @ViewChild('lineEditor', { static: false }) lineEditor: TextEditorComponent;
  @ViewChild(MatMenuTrigger) exportMenuTrigger: MatMenuTrigger;
  public lines: Letter[];

  // Get dynamic canvas dimensions based on viewport
  getCanvasDimensions(): { width: number; height: number } {
    // Use almost all available height - just subtract navbar (~70px) and small margin
    const availableHeight = window.innerHeight - 100;

    // For stages 2-3 (full width canvas), use more width
    // For stage 5 (with line editor), use less width
    const availableWidth = this.stage >= 4
      ? Math.min(window.innerWidth * 0.5, 800) // When line editor is visible
      : Math.min(window.innerWidth * 0.92, 1400); // Full width mode

    console.log('Canvas dimensions:', {
      viewportHeight: window.innerHeight,
      calculatedHeight: availableHeight,
      viewportWidth: window.innerWidth,
      calculatedWidth: availableWidth,
      stage: this.stage
    });

    return {
      width: Math.max(availableWidth, 500),
      height: Math.max(availableHeight, 600)
    };
  }

  // Panel resizing methods
  startResize(event: MouseEvent | TouchEvent) {
    event.preventDefault();
    this.isResizing = true;

    const container = (event.target as HTMLElement).closest('.split-container') as HTMLElement;
    if (!container) return;

    const containerRect = container.getBoundingClientRect();

    this.resizeHandler = (e: MouseEvent | TouchEvent) => {
      if (!this.isResizing) return;

      const clientX = e instanceof MouseEvent ? e.clientX : e.touches[0].clientX;
      const newWidth = ((clientX - containerRect.left) / containerRect.width) * 100;

      // Clamp between 20% and 80%
      this.leftPanelWidth = Math.max(20, Math.min(80, newWidth));
    };

    this.resizeEndHandler = () => {
      this.isResizing = false;
      document.removeEventListener('mousemove', this.resizeHandler);
      document.removeEventListener('mouseup', this.resizeEndHandler);
      document.removeEventListener('touchmove', this.resizeHandler);
      document.removeEventListener('touchend', this.resizeEndHandler);

      // Update canvas size to fit new container width, keeping current zoom
      if (this.canvas) {
        setTimeout(() => {
          this.canvas.setCanvasSize();
        }, 100);
      }
    };

    document.addEventListener('mousemove', this.resizeHandler);
    document.addEventListener('mouseup', this.resizeEndHandler);
    document.addEventListener('touchmove', this.resizeHandler);
    document.addEventListener('touchend', this.resizeEndHandler);
  }

  // Generate lines from image - uses selected box if available, otherwise full image
  generateLines() {
    this.toolbarService.setLoading(true);
    this.isLoading = true;

    // Get the full background image
    const bgImage = this.canvas.getCanvas().backgroundImage as unknown as FabricImage;
    if (!bgImage) {
      this.notificationService.showError("No image loaded");
      this.toolbarService.setLoading(false);
      this.isLoading = false;
      return;
    }

    // Check if there's a selected box - if so, crop to that area
    let imageData: string;
    const box = this.selectedBox;

    if (box) {
      // Crop to selected box area
      imageData = bgImage.toDataURL({
        left: box.left,
        top: box.top,
        width: box.getScaledWidth(),
        height: box.getScaledHeight()
      });
      // Store crop area so Detect Lines can use the same region
      this.ocrCropArea = { left: box.left, top: box.top, width: box.getScaledWidth(), height: box.getScaledHeight() };
      // Replace uploadedImageBlob with the cropped image for correct training data
      this.uploadedImageBlob = this.dataUrlToFile(imageData, 'cropped-region.png');
    } else {
      // Use full image
      imageData = bgImage.toDataURL({});
      this.ocrCropArea = null;
    }

    // Save API key for this model if provided
    if (this.apiKey && this.requiresApiKey()) {
      localStorage.setItem('ocr_api_key_' + this.selectedOcrModel, this.apiKey);
    }

    // Save TEI API key if provided
    if (this.teiApiKey && this.teiModelNeedsApiKey) {
      this.saveTeiApiKey();
    }

    // Build TEI options for two-stage pipeline
    const teiOptions = this.selectedOcrPrompt === 'tei_lex0' && this.selectedTeiModelInfo
      ? {
          teiModel: this.selectedTeiModelInfo.model,
          teiProvider: this.selectedTeiModelInfo.provider,
          teiApiKey: this.teiApiKey || undefined
        }
      : undefined;

    this.curedService.getTransliterations(imageData, this.getEffectiveModel(), this.selectedOcrPrompt, this.apiKey || undefined, teiOptions).subscribe(data => {
      if (data.lines.length == 0) {
        this.notificationService.showWarning("AI failed to parse the image, please try again", 20000);
        this.isLoading = false;
        this.toolbarService.setLoading(false);
        return;
      }

      // Capture TEI validation results if present
      if (data.validation_results && data.validation_results.length > 0) {
        this.teiValidationResults = data.validation_results;
        this.showTeiValidation = true;
        const validCount = data.validation_results.filter(e => e.status === 'valid').length;
        const errorCount = data.validation_results.filter(e => e.status === 'error').length;
        if (errorCount > 0) {
          this.notificationService.showWarning(`TEI Validation: ${validCount} valid, ${errorCount} errors out of ${data.validation_results.length} entries`, 10000);
        } else {
          this.notificationService.showSuccess(`TEI Validation: All ${validCount} entries valid`);
        }
      } else {
        this.teiValidationResults = null;
        this.showTeiValidation = false;
      }

      // Set stage to 5 FIRST so lineEditor gets rendered
      this.stage = 5;
      this.updateUrl();
      this.isLoading = false;
      this.toolbarService.setLoading(false);

      // Wait for Angular to render the lineEditor component, then process results
      setTimeout(() => {
        // Process with box offset if box was selected
        this.fetchTransliterations(data.lines);
        this.fetchBoundingBoxes(data.dimensions, box);

        // Keep the selection box visible but make it non-interactive (stable)
        if (box) {
          box.set({
            selectable: false,
            evented: false,
            strokeDashArray: [8, 4],
            stroke: 'orange',
            strokeWidth: 2,
            fill: 'rgba(255, 165, 0, 0.03)',
          });
          this.canvas.getCanvas().renderAll();
          this.selectedBox = null;
          this.ocrSelectionBox = box;  // Keep reference for cleanup
        }

        this.updateToolbarButtons();
        this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.addMode];
        this.canvas.changeMode(CanvasMode.Pan);
      }, 50);
    });
  }

  constructor(
    public authService: AuthService,
    private curedService: CuredService,
    private notificationService: NotificationService,
    public dialog: MatDialog,
    private route: ActivatedRoute,
    private router: Router,
    private toolbarService: ToolbarService,
    private atfConverter: AtfConverterService,
    private textService: TextService,
    private projectService: ProjectService,
    private sanitizer: DomSanitizer,
    private location: Location,
    private http: HttpClient) {
    // set some stuff
    // this.stage = 5;
    // this.transliterationResult = ["hello therew world", "there are the test lines", "enjoy them while they least"];
    // this.lines = [new Letter("helhello therew worldloi"), new Letter("there are the test lines"),
    //               new Letter("enjoy them while they least")];
    // this.addIndexes(this.lines);
  }

  ngOnInit(): void {
    console.log(
      '%c CuReD Keyboard Shortcuts %c\n' +
      'Ctrl+Alt+N       New OCR process (restart)\n' +
      'Alt+Z            Pan mode\n' +
      'Alt+A            Add box mode\n' +
      'Alt+X            Adjust mode\n' +
      'Alt+D            Delete mode\n' +
      'Delete           Delete selected box\n' +
      'Double-click+hold Draw new box (in Pan mode)\n' +
      'Ctrl+H           Find & Replace (in text editor)',
      'background: #333; color: #fff; padding: 4px 8px; font-weight: bold;',
      'color: #333; font-family: monospace;'
    );

    // Load labels for save dialog
    this.textService.getLabels().subscribe(labels => {
      this.existingLabels = labels;
    });

    // Load flat project list
    this.loadProjects();

    // Load training status and models
    this.loadTrainingStatus();
    this.loadCuratedStats();
    this.loadModels();
    this.loadBaseModelsMetadata();
    this.loadAvailableOcrModels();
    this.loadAvailableOllamaModels();

    // Subscribe to query param changes to handle navigation within the same route
    this.queryParamsSub = this.route.queryParams.subscribe(params => {
      this.handleQueryParams(params);
    });

    // Listen for browser back/forward button
    this.popStateSub = this.location.subscribe((event) => {
      if (this.suppressPopState) {
        return;
      }
      const urlPath = (event.url || '').split('?')[0];
      const targetStage = this.stageFromPath(urlPath);
      if (targetStage < this.stage) {
        // Browser already changed the URL, so use replaceUrl mode to avoid pushing duplicates
        this.goBack(true);
      }
    });
  }

  private stageFromPath(urlPath: string): number {
    // CuReD is now embedded at /cured — all stages use the same path
    return 0;
  }

  /**
   * Handle query parameter changes (initial load and navigation)
   */
  private handleQueryParams(params: any) {
    const textId = params['textId'];
    const transId = params['transId'];
    const viewOnly = params['viewOnly'] === 'true';
    const query = params['query'];

    this.highlightQuery = query || null;

    if (textId && transId) {
      // Opening a specific transliteration
      this.takeTextId = +textId;
      this.takeTransId = +transId;
      this.viewOnly = viewOnly;
      if (this.viewOnly) {
        this.canvasType = CanvasType.ViewAmendment;
      }

      this.textId = this.takeTextId;
      this.transliterationId = this.takeTransId;
      this.isLoadedFromServer = true;
      this.stage = 5;

      // Wait for canvas to be rendered, then load content
      this.waitForCanvasAndLoad();
    } else if (textId) {
      // Text exists but no transliteration yet - pre-associate and show upload
      this.textId = +textId;
      this.loadTextMetadata();
      this.stage = 0;
    } else {
      // Dashboard
      this.resetToCleanState();
      this.stage = 0;
      this.loadProjects();
    }
  }

  /**
   * Wait for canvas ViewChild to be available, then load image and transliteration
   */
  private waitForCanvasAndLoad() {
    if (this.canvas) {
      // Canvas is ready, load content
      setTimeout(() => {
        this.loadImageFromServer();
        this.loadTransliteration();
      }, 50);
    } else {
      // Canvas not ready yet, wait for Angular to render it
      setTimeout(() => this.waitForCanvasAndLoad(), 50);
    }
  }

  /**
   * Sync the browser URL to match the current stage without triggering a full reload.
   * Uses Location.replaceState so Angular doesn't destroy/recreate the component.
   */
  private updateUrl(replace: boolean = false) {
    let path = '/cured';

    // For editor stage with a loaded transliteration, add query params for deep linking
    if ((this.stage === 2 || this.stage === 4 || this.stage === 5) &&
        this.isLoadedFromServer && this.textId != null && this.transliterationId != null) {
      const params = new URLSearchParams();
      params.set('textId', String(this.textId));
      params.set('transId', String(this.transliterationId));
      if (this.viewOnly) {
        params.set('viewOnly', 'true');
      }
      if (this.highlightQuery) {
        params.set('query', this.highlightQuery);
      }
      path += '?' + params.toString();
    }

    this.suppressPopState = true;
    if (replace) {
      this.location.replaceState(path);
    } else {
      this.location.go(path);
    }
    setTimeout(() => this.suppressPopState = false);
  }

  /**
   * Reset component to clean state for dashboard view
   */
  private resetToCleanState() {
    this.textId = null;
    this.transliterationId = null;
    this.takeTextId = null;
    this.takeTransId = null;
    this.isLoadedFromServer = false;
    this.isCuratedKraken = false;
    this.isCuratedVlm = false;
    this.viewOnly = false;
    this.lines = null;
    this.boundingBoxes = [];
    this.pdfSrc = null;
    this.pdfFile = null;
    this.backgroundImage = null;
    this.canvasType = CanvasType.SingleSelection;
    // Reset translation state
    this.hasLinkedTranslation = false;
    this.linkedTranslationLines = [];
    this.showTranslationView = false;
    this.currentMuseumName = '';
    this.currentMuseumNumber = 0;
    this.currentPNumber = '';
    this.currentPublicationNumber = '';
  }

  ngAfterViewInit() {
    // Only set canvas dimensions if canvas exists (stage >= 2)
    if (this.canvas) {
      const dims = this.getCanvasDimensions();
      this.canvas.props.canvasHeight = dims.height;
      this.canvas.props.canvasWidth = dims.width;
    }
    // Note: Loading is now handled by waitForCanvasAndLoad() called from handleQueryParams
  }

  ngOnDestroy() {
    this.toolbarService.clearButtons();
    this.toolbarService.setLoading(false);
    if (this.autoSaveTimer) {
      clearTimeout(this.autoSaveTimer);
    }
    if (this.queryParamsSub) {
      this.queryParamsSub.unsubscribe();
    }
    if (this.popStateSub) {
      this.popStateSub.unsubscribe();
    }
    this.stopTrainingProgressPolling();
  }

  updateToolbarButtons() {
    const canGoBack = !this.isLoadedFromServer && !this.viewOnly && this.stage >= 1;

    if (this.stage === 1) {
      this.toolbarService.setToolbar({
        buttons: [],
        message: 'Select a page',
        backAction: canGoBack ? () => this.goBack() : undefined
      });
    } else if (this.stage === 2) {
      // User can optionally draw a selection box, or process whole page
      const message = this.selectedBox
        ? 'Selection ready - click Generate'
        : 'Draw a box to select area (optional)';
      this.toolbarService.setToolbar({
        buttons: [],
        message: message,
        backAction: canGoBack ? () => this.goBack() : undefined
      });
    } else if (this.stage === 5) {
      const buttons = [];

      buttons.push({
        label: 'Export',
        icon: 'download',
        action: () => this.exportMenuTrigger.openMenu(),
        color: 'default'
      });

      if (!this.viewOnly) {
        buttons.push({
          label: 'Save',
          icon: 'save',
          action: () => this.openSaveDialog(),
          color: 'primary'
        });

        // Curate for Kraken: requires boxes === lines
        const krakenLabel = this.isCuratedKraken ? 'Kraken ✓' : 'Curate Kraken';
        buttons.push({
          label: krakenLabel,
          icon: 'grid_on',
          action: () => this.curateForKraken(),
          color: this.isCuratedKraken ? 'primary' : 'accent',
          disabled: this.textId == null || !this.canCurateKraken
        });

        // Curate for VLM: requires crop area or saved image + lines
        const vlmLabel = this.isCuratedVlm ? 'VLM ✓' : 'Curate VLM';
        buttons.push({
          label: vlmLabel,
          icon: 'crop',
          action: () => this.curateForVlm(),
          color: this.isCuratedVlm ? 'primary' : 'accent',
          disabled: this.textId == null || !this.canCurateVlm
        });

        // Detect Lines: when boxes are missing or mismatched with lines
        if (this.lines?.length > 0 && this.boundingBoxes.length !== this.lines.length) {
          buttons.push({
            label: this.isDetectingLines ? 'Detecting...' : 'Detect Lines',
            icon: this.isDetectingLines ? 'hourglass_empty' : 'auto_fix_high',
            action: () => this.detectLines(),
            color: 'pink',
            disabled: this.isDetectingLines
          });
        }

        // Clear all boxes
        if (this.boundingBoxes.length > 0) {
          buttons.push({
            label: 'Clear Boxes',
            icon: 'delete_sweep',
            action: () => this.clearAllBoxes(),
            color: 'warn'
          });
        }

        if (this.isLoadedFromServer && this.textId != null && this.transliterationId != null) {
          buttons.push({
            label: 'Delete',
            icon: 'delete',
            action: () => this.deleteCurrentTransliteration(),
            color: 'warn'
          });
        }
      }

      buttons.push({
        label: 'New',
        icon: 'refresh',
        action: () => this.restart(),
        color: 'warn'
      });

      this.toolbarService.setToolbar({
        buttons,
        message: undefined,
        backAction: canGoBack ? () => this.goBack() : undefined
      });
    } else {
      this.toolbarService.clearButtons();
    }
  }

  openSaveDialog() {
    // Build museum number string from name+number
    const museumStr = this.currentMuseumName
      ? (this.currentMuseumNumber ? `${this.currentMuseumName}-${this.currentMuseumNumber}` : this.currentMuseumName)
      : '';

    const dialogRef = this.dialog.open(SaveDialogComponent, {
      data: {
        textId: this.textId,
        existingLabels: this.existingLabels,
        existingParts: this.existingParts,
        currentLabel: this.currentLabel,
        currentPart: this.currentPart,
        museumNumber: museumStr,
        pNumber: this.currentPNumber,
        publicationNumber: this.currentPublicationNumber
      }
    });

    dialogRef.afterClosed().subscribe((result: SaveDialogResult | null) => {
      if (!result) { return; } // Cancelled

      this.isSaving = true;
      const { museumNumber, pNumber, publicationNumber, label, part } = result;

      // Store all fields locally for next open
      this.currentLabel = label;
      this.currentPart = part;
      // Parse museum number back into name + number for local state
      const parsedMuseum = this.parseIdentifierValue(museumNumber);
      this.currentMuseumName = parsedMuseum ? parsedMuseum.name : '';
      this.currentMuseumNumber = parsedMuseum ? parsedMuseum.number : 0;
      this.currentPNumber = pNumber;
      this.currentPublicationNumber = publicationNumber;

      // If we already have a textId, save directly
      if (this.textId != null) {
        this.doSaveWithLabelAndPart(false, label, part);
        return;
      }

      // Build identifiers by parsing "name-number" format (e.g., "BM-12345" or just "12345")
      const parseIdentifier = (value: string) => {
        if (!value) return null;
        // Split by last hyphen to handle names with hyphens (e.g., "K-1234")
        const lastHyphenIdx = value.lastIndexOf('-');
        if (lastHyphenIdx > 0) {
          const name = value.substring(0, lastHyphenIdx);
          const numStr = value.substring(lastHyphenIdx + 1);
          const num = parseInt(numStr, 10);
          if (!isNaN(num)) {
            return { name, number: num };
          }
        }
        // Try parsing as plain number
        const num = parseInt(value, 10);
        if (!isNaN(num)) {
          return { name: '', number: num };
        }
        // If not a number, treat entire string as name with 0
        return { name: value, number: 0 };
      };

      const identifiers = {
        museum: parseIdentifier(museumNumber),
        publication: parseIdentifier(publicationNumber),
        p_number: parseIdentifier(pNumber)
      };

      // Check if we have valid identifiers with actual numbers (number > 0)
      // Only these will generate MongoDB query items
      const hasValidIdentifiers =
        (identifiers.museum?.number > 0) ||
        (identifiers.publication?.number > 0) ||
        (identifiers.p_number?.number > 0);

      if (hasValidIdentifiers) {
        this.textService.getTextIdByIdentifiers(identifiers as any).subscribe(
          existingTextId => {
            if (existingTextId && existingTextId !== -1) {
              this.textId = existingTextId;
              this.doSaveWithLabelAndPart(false, label, part);
            } else {
              this.createTextAndSaveWithLabelAndPart(identifiers, label, part);
            }
          },
          () => {
            this.createTextAndSaveWithLabelAndPart(identifiers, label, part);
          }
        );
      } else {
        this.createTextAndSaveWithLabelAndPart(identifiers, label, part);
      }
    });
  }

  private createTextAndSaveWithLabelAndPart(identifiers: any, label: string, part: string) {
    const projectId = this.selectedProject?.project_id || null;
    this.textService.create(identifiers, [], projectId).subscribe(textId => {
      this.textId = textId;
      this.doSaveWithLabelAndPart(false, label, part);
    }, err => {
      this.notificationService.showError('Failed to create text');
      this.isSaving = false;
    });
  }

  private doSaveWithLabelAndPart(isFixed: boolean, label: string, part: string, curateTarget?: 'kraken' | 'vlm') {
    if (this.transliterationId == null && this.uploadedImageBlob) {
      this.curedService.saveImage(this.uploadedImageBlob, this.textId).subscribe(imageName => {
        this.createSubmissionWithLabelAndPart(isFixed, imageName, label, part, curateTarget);
      }, err => {
        this.notificationService.showError('Failed to upload image');
        this.isSaving = false;
      });
    } else {
      this.createSubmissionWithLabelAndPart(isFixed, null, label, part, curateTarget);
    }
  }

  private doSave(isFixed: boolean, curateTarget?: 'kraken' | 'vlm') {
    this.doSaveWithLabelAndPart(isFixed, this.currentLabel, this.currentPart, curateTarget);
  }

  createSubmissionWithLabelAndPart(isFixed: boolean, imageName: string = null, label: string = '', part: string = '',
                                   curateTarget?: 'kraken' | 'vlm') {
    let lines = this.lines.map(line => line.letter);
    // If image was cropped, adjust box coordinates to be relative to the crop (not full page)
    let dimensions: Dimensions[];
    if (this.ocrCropArea) {
      dimensions = this.boundingBoxes.map(box => new Dimensions(
        box.left - this.ocrCropArea.left,
        box.top - this.ocrCropArea.top,
        box.getScaledHeight(),
        box.getScaledWidth()
      ));
    } else {
      dimensions = this.boundingBoxes.map(box => new Dimensions(box.left, box.top, box.getScaledHeight(), box.getScaledWidth()));
    }

    // Determine curation flags: preserve existing + add new target
    let isKraken = this.isCuratedKraken;
    let isVlm = this.isCuratedVlm;
    if (curateTarget === 'kraken') isKraken = true;
    if (curateTarget === 'vlm') isVlm = true;

    this.curedService.createSubmission(this.textId, this.transliterationId, lines, dimensions, imageName, isKraken, isVlm).subscribe(result => {
      if (this.hasPendingPages) {
        this.notificationService.showSuccess(
          `Saved (${this.currentPageIndex + 1}/${this.batchTotal}). Click "Next" for the next image.`
        );
      } else {
        this.notificationService.showInfo("Successfully saved");
      }
      this.transliterationId = result;
      this.isCuratedKraken = isKraken;
      this.isCuratedVlm = isVlm;
      this.isSaving = false;

      // Update label if provided
      if (label && this.textId) {
        this.textService.updateLabel(this.textId, label).subscribe(
          () => {
            if (!this.existingLabels.includes(label)) {
              this.existingLabels.push(label);
              this.existingLabels.sort();
            }
          },
          () => { /* ignore label update errors */ }
        );
      }

      // Update part if provided
      if (part && this.textId) {
        this.textService.updatePart(this.textId, part).subscribe(
          () => {},
          () => { /* ignore part update errors */ }
        );
      }

      // Update identifiers if any were provided
      if (this.textId && (this.currentMuseumName || this.currentPNumber || this.currentPublicationNumber)) {
        const museumStr = this.currentMuseumName
          ? (this.currentMuseumNumber ? `${this.currentMuseumName}-${this.currentMuseumNumber}` : this.currentMuseumName)
          : '';
        this.textService.updateIdentifiers(this.textId, museumStr, this.currentPNumber, this.currentPublicationNumber).subscribe(
          () => {},
          () => { /* ignore identifier update errors */ }
        );
      }

      this.updateToolbarButtons();
    }, err => {
      this.notificationService.showError('Failed to save');
      this.isSaving = false;
    });
  }

  /** Check if the data shape allows Kraken curation (boxes === lines). */
  get canCurateKraken(): boolean {
    const lineCount = this.lines?.length || 0;
    const boxCount = this.boundingBoxes?.length || 0;
    return lineCount > 0 && boxCount === lineCount;
  }

  /** Check if the data shape allows VLM curation (crop area OR saved image + lines). */
  get canCurateVlm(): boolean {
    const lineCount = this.lines?.length || 0;
    return lineCount > 0 && (!!this.ocrCropArea || this.isLoadedFromServer);
  }

  /** Whether any curation has been done. */
  get isTextFixed(): boolean {
    return this.isCuratedKraken || this.isCuratedVlm;
  }

  /** Clear all bounding boxes from the canvas. */
  clearAllBoxes() {
    for (const box of this.boundingBoxes) {
      this.canvas.getCanvas().remove(box);
    }
    this.boundingBoxes = [];
    this.canvas.getCanvas().renderAll();
    this.notificationService.showInfo('All boxes removed');
    this.updateToolbarButtons();
  }

  curateForKraken() {
    if (this.textId == null) {
      this.notificationService.showError('Please save first before curating');
      return;
    }
    if (!this.canCurateKraken) {
      this.notificationService.showError(`Cannot curate for Kraken: need ${this.lines?.length || 0} boxes but have ${this.boundingBoxes?.length || 0}`);
      return;
    }
    this.notificationService.showInfo('Curating for Kraken');
    this.doSave(true, 'kraken');
  }

  curateForVlm() {
    if (this.textId == null) {
      this.notificationService.showError('Please save first before curating');
      return;
    }
    if (!this.canCurateVlm) {
      this.notificationService.showError('Cannot curate for VLM: need lines and an image');
      return;
    }
    this.notificationService.showInfo('Curating for VLM');
    this.doSave(true, 'vlm');
  }

  deleteCurrentTransliteration() {
    if (!confirm('Delete this transliteration? This will also delete the associated image and cannot be undone.')) {
      return;
    }
    this.curedService.deleteTransliteration(this.textId, this.transliterationId).subscribe(
      () => {
        this.notificationService.showSuccess('Transliteration deleted');
        this.router.navigate(['/']);
      },
      () => {
        this.notificationService.showError('Failed to delete transliteration');
      }
    );
  }

  openDialog() {
    const dialogRef = this.dialog.open(TextCreatorComponent);

    dialogRef.afterClosed().subscribe(textId => {
      console.log(`Dialog result: ${textId}`);
      this.textId = textId;
    });
  }

  findATransliteration() {
    this.stage = 5;
    this.updateUrl();
    const dialogRef = this.dialog.open(TextCreatorComponent);
    dialogRef.componentInstance.selectTransliteration = true;
    dialogRef.componentInstance.showCreateOnNoResult = false;
    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.textId = result[0];
        this.transliterationId = result[1];
        this.isLoadedFromServer = true;
        this.loadImageFromServer();
        this.loadTransliteration();
      } else {
        this.stage = 0;
        this.updateUrl();
        this.toolbarService.clearButtons();
      }

    });
  }

  loadTransliteration() {
    this.curedService.loadTransliteration(this.textId, this.transliterationId).subscribe(data => {
      this.processTransliteration(data.lines, data.boxes, true);
      this.isCuratedKraken = data.is_curated_kraken || false;
      this.isCuratedVlm = data.is_curated_vlm || false;
      if (this.highlightQuery) {
        this.setHighlightByQuery(this.highlightQuery);
      }
      // Load text metadata to enable translation lookup
      this.loadTextMetadata();
    });
  }

  loadImageFromServer() {
    let fileReader = new FileReader();
    fileReader.addEventListener("load", () => {
      let imageToShow: any = fileReader.result;
      this.setCanvasImage(imageToShow);
    }, false);

    this.curedService.getImage(this.textId, this.transliterationId).subscribe(data => {
      fileReader.readAsDataURL(data);
    }, err => {
      console.error('Failed to load image from server:', err);
      this.notificationService.showWarning('Image not available for this transliteration');
    })
  }

  // Drag and drop handlers
  onDragOver(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = true;
  }

  onDragLeave(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = false;
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver = false;

    const files = event.dataTransfer?.files;
    if (files && files.length > 1) {
      // Multiple files dropped - treat as batch
      this.handleMultipleFiles(files);
    } else if (files && files.length > 0) {
      this.processFile(files[0]);
    }
  }

  handleFileInput(event: any) {
    const file = event.target.files[0];
    if (file) {
      this.processFile(file);
    }
  }

  handleFolderInput(event: any): void {
    const files: FileList = event.target.files;
    if (!files || files.length === 0) return;
    this.handleMultipleFiles(files);
    // Reset input so the same folder can be selected again
    event.target.value = '';
  }

  private handleMultipleFiles(files: FileList): void {
    const supportedExts = ['.png', '.jpg', '.jpeg'];
    const imageFiles: File[] = [];

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const name = file.name.toLowerCase();
      if (supportedExts.some(ext => name.endsWith(ext))) {
        imageFiles.push(file);
      }
    }

    if (imageFiles.length === 0) {
      this.notificationService.showError('No supported image files found (PNG, JPG)');
      return;
    }

    // Sort by filename for consistent ordering
    imageFiles.sort((a, b) => a.name.localeCompare(b.name));

    // Set up batch queue with local files
    this.pendingPages = [];
    this.pendingLocalFiles = imageFiles;
    this.currentPageIndex = 0;

    this.notificationService.showInfo(`Loaded ${imageFiles.length} images as batch`);
    this.processFile(imageFiles[0]);
  }

  browseServer(): void {
    const dialogRef = this.dialog.open(ImageBrowserDialogComponent, {
      width: '850px', height: '600px'
    });
    dialogRef.afterClosed().subscribe((result: SelectedPage[] | null) => {
      if (!result || result.length === 0) return;

      // Store all selected pages as a batch queue
      this.pendingPages = result;
      this.pendingLocalFiles = [];
      this.currentPageIndex = 0;

      this.loadPageFromQueue(0);
    });
  }

  private loadPageFromQueue(index: number): void {
    if (index >= this.pendingPages.length) return;
    const page = this.pendingPages[index];
    this.http.get(page.image_url, { responseType: 'blob' }).subscribe(blob => {
      const file = new File([blob], page.filename, { type: 'image/png' });
      // Reset state for new image
      this.resetForNextBatchItem();
      this.processFile(file);
    });
  }

  loadNextPage(): void {
    if (!this.hasPendingPages) return;
    this.currentPageIndex++;
    if (this.currentPageIndex < this.pendingPages.length) {
      this.loadPageFromQueue(this.currentPageIndex);
    } else {
      // Local files start after server pages
      const localIdx = this.currentPageIndex - this.pendingPages.length;
      if (localIdx < this.pendingLocalFiles.length) {
        this.resetForNextBatchItem();
        this.processFile(this.pendingLocalFiles[localIdx]);
      }
    }
  }

  skipPage(): void {
    this.loadNextPage();
  }

  clearBatchQueue(): void {
    this.pendingPages = [];
    this.pendingLocalFiles = [];
    this.currentPageIndex = 0;
  }

  private resetForNextBatchItem(): void {
    this.textId = null;
    this.transliterationId = null;
    this.uploadedImageBlob = null;
    this.isCuratedKraken = false;
    this.isCuratedVlm = false;
    this.ocrCropArea = null;
    this.ocrSelectionBox = null;
    this.teiValidationResults = null;
    this.showTeiValidation = false;
    this.hasLinkedTranslation = false;
    this.linkedTranslationLines = [];
    this.showTranslationView = false;
    this.currentLabel = '';
    this.currentPart = '';
    this.currentMuseumName = '';
    this.currentMuseumNumber = 0;
    this.currentPNumber = '';
    this.currentPublicationNumber = '';
  }

  processFile(file: File) {
    const fileName = file.name.toLowerCase();
    if (fileName.endsWith('.pdf')) {
      this.loadPDFFile(file);
    } else if (fileName.endsWith('.png') || fileName.endsWith('.jpg') || fileName.endsWith('.jpeg')) {
      this.loadImage(null, file);
    } else {
      this.notificationService.showError("Unsupported file type. Please use PDF, PNG, or JPG.");
    }
  }

  loadPDFFile(file: File) {
    this.pdfFile = file;
    this.isLoading = true;
    this.totalPages = 0;
    this.pageNumbers = [];
    let fileReader = new FileReader();

    fileReader.addEventListener("load", () => {
      var typedarray = new Uint8Array(fileReader.result as ArrayBufferLike);
      this.pdfSrc = typedarray;
      this.stage = 1;
      this.updateUrl();
      this.updateToolbarButtons();
    });

    fileReader.readAsArrayBuffer(file);
  }

  userPasted(e) {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    let blob = null;
    for (const item of items) {
      if (item.type.indexOf('image') === 0) {
        blob = item.getAsFile();
        this.notificationService.showSuccess("Image loaded from paste!")
        this.loadImage(null, blob);
        return;
      }
    }
    this.notificationService.showError("That wasn't an image...");
  }

  loadImage(event = null, pasteImage = null) {
    const supportedTypes = ["image/png", "image/jpeg"]
    //  "image/tiff"]
    const file: File = event ? event.target.files[0] : pasteImage;
    if (!supportedTypes.includes(file.type)) {
      alert("Unsupported file extension. Please upload a .png, .jpg, .jpeg .tif or .tiff")
      return;
    }
    const fileSize = file.size / 1024 / 1024; // in MiB
    if (fileSize > 20) {
      alert("File is too big. Maximum supported is 5MB")
      return;
    }

    let fileReader = new FileReader();

    fileReader.addEventListener("load", () => {
      this.isLoading = false;
      let imageToShow: any = fileReader.result;
      this.uploadedImageBlob = file;
      // Set stage first so canvas gets rendered
      this.stage = 2;
      this.updateUrl();
      // Wait for Angular to render the canvas component
      setTimeout(() => {
        if (this.canvas) {
          this.setCanvasImage(imageToShow);
          this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode];
          this.canvas.changeMode(CanvasMode.Pan);
        }
        this.updateToolbarButtons();
      }, 100);
    }, false);

    this.isLoading = true;
    fileReader.readAsDataURL(file);
  }

  setCanvasImage(imageToShow) {
    this.backgroundImage = imageToShow;
    this.canvas.props.canvasImage = imageToShow;
    this.canvas.setCanvasImage();
    const dims = this.getCanvasDimensions();
    this.canvas.props.canvasHeight = dims.height;
    this.canvas.props.canvasWidth = dims.width;
    this.canvas.forceCanvasSize();
    this.canvas.forceZoomOut(0.5);  // 50% zoom
  }


  loadPDF(event) {
    const supportedTypes = ["application/pdf"]
    const file: File = event.target.files[0];
    if (!supportedTypes.includes(file.type)) {
      alert("Unsupported file extension. Please upload a .pdf")
    }

    this.pdfFile = file;
    let fileReader = new FileReader();

    fileReader.addEventListener("load", () => {
      var typedarray = new Uint8Array(fileReader.result as ArrayBufferLike);
      this.pdfSrc = typedarray;
      this.stage = 1;
      this.updateUrl();
      this.updateToolbarButtons();
    });

    fileReader.readAsArrayBuffer(file);
  }

  getResult() {
    return new SelectedPdf(this.pdfFile, this.currentpage)
  }

  selectPage() {
    this.isLoading = true;
    let selectedPdf = this.getResult()
    let reader = new FileReader();

    reader.addEventListener("load", () => {
      this.isLoading = false;
      let imageToShow: any = reader.result;
      this.backgroundImage = imageToShow;
      this.canvas.props.canvasImage = imageToShow;
      this.canvas.setCanvasImage();
      const dims = this.getCanvasDimensions();
      this.canvas.props.canvasHeight = dims.height;
      this.canvas.props.canvasWidth = dims.width;
      this.canvas.forceCanvasSize();
      this.canvas.forceZoomOut();
      this.stage = 2;
      this.updateUrl();
      this.updateToolbarButtons();
    }, false);

    this.curedService.convertPdf(selectedPdf).subscribe(result => {
      if (result) {
        this.uploadedImageBlob = new File([result], `page-${selectedPdf.page}.png`, { type: 'image/png' });
        reader.readAsDataURL(result);
      }
    });
  }

  modeChanged(val) {
    // if(val == CanvasMode.Adjust) {
    //   this.stage = 4;
    // }
  }

  cancel() {
    // this.matDialogRef.close();
  }

  afterLoadComplete(pdf: PDFDocumentProxy) {
    this.totalPages = pdf.numPages;
    this.pageNumbers = Array.from({ length: pdf.numPages }, (_, i) => i + 1);
    this.goToPageInput = 1;
    // Only show first PAGE_WINDOW_SIZE pages initially
    this.updateVisiblePages(1);
    this.isLoading = false;
  }

  /**
   * Update the visible pages window centered around a target page.
   * Shows 4 pages before and 5 pages after the target (10 total).
   */
  updateVisiblePages(targetPage: number) {
    if (this.totalPages === 0) return;

    // Calculate window: 4 before, target, 5 after (10 total)
    let startPage = Math.max(1, targetPage - 4);
    let endPage = Math.min(this.totalPages, startPage + this.PAGE_WINDOW_SIZE - 1);

    // Adjust start if we're near the end
    if (endPage - startPage + 1 < this.PAGE_WINDOW_SIZE) {
      startPage = Math.max(1, endPage - this.PAGE_WINDOW_SIZE + 1);
    }

    this.visiblePageNumbers = [];
    for (let i = startPage; i <= endPage; i++) {
      this.visiblePageNumbers.push(i);
    }
  }

  /**
   * Jump to a specific page (from input field)
   */
  jumpToPage() {
    const page = Math.max(1, Math.min(this.totalPages, this.goToPageInput || 1));
    this.goToPageInput = page;
    this.updateVisiblePages(page);
  }

  /**
   * Navigate to next window of pages
   */
  nextPageWindow() {
    const lastVisible = this.visiblePageNumbers[this.visiblePageNumbers.length - 1];
    if (lastVisible < this.totalPages) {
      this.updateVisiblePages(lastVisible + 1);
      this.goToPageInput = this.visiblePageNumbers[0];
    }
  }

  /**
   * Navigate to previous window of pages
   */
  prevPageWindow() {
    const firstVisible = this.visiblePageNumbers[0];
    if (firstVisible > 1) {
      const newTarget = Math.max(1, firstVisible - this.PAGE_WINDOW_SIZE);
      this.updateVisiblePages(newTarget);
      this.goToPageInput = this.visiblePageNumbers[0];
    }
  }

  selectPageFromThumbnail(page: number) {
    this.currentpage = page;
    this.isLoading = true;

    // Move to stage 2 first so the canvas component is rendered
    this.stage = 2;
    this.updateUrl();

    let selectedPdf = new SelectedPdf(this.pdfFile, page);

    this.curedService.convertPdf(selectedPdf).subscribe(result => {
      if (result) {
        // Store the converted PDF page image so it can be saved with the transliteration
        this.uploadedImageBlob = new File([result], `page-${page}.png`, { type: 'image/png' });
        let reader = new FileReader();
        reader.addEventListener("load", () => {
          // Wait for canvas to be available after stage change
          setTimeout(() => {
            this.isLoading = false;
            let imageToShow: any = reader.result;
            this.backgroundImage = imageToShow;
            if (this.canvas) {
              this.canvas.props.canvasImage = imageToShow;
              this.canvas.setCanvasImage();
              const dims = this.getCanvasDimensions();
              this.canvas.props.canvasHeight = dims.height;
              this.canvas.props.canvasWidth = dims.width;
              this.canvas.forceCanvasSize();
              this.canvas.forceZoomOut();
              this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode];
              this.canvas.changeMode(CanvasMode.Pan);
            }
            this.updateToolbarButtons();
          }, 100);
        }, false);
        reader.readAsDataURL(result);
      }
    });
  }

  public previous() {
    if (this.currentpage > 0) {
      if (this.currentpage == 1) {
        this.currentpage = this.totalPages;
      } else {
        this.currentpage--;
      }
    }
  }

  public next() {
    if (this.totalPages > this.currentpage) {
      this.currentpage = this.currentpage + 1;
    } else {
      this.currentpage = 1;
    }
  }

  public goToAPage() {
    if (this.totalPages >= this.goToPage) {
      this.currentpage = this.goToPage;
    } else {
      this.notificationService.showError("Bad page number");
    }
  }

  boxDeleted(index) {
    if (this.boundingBoxes) {
      this.boundingBoxes = this.boundingBoxes.filter(item => item.data.index.row != index.row);
      this.sortBoxes();
      this.updateBoundingBoxesIndexes();
      this.updateToolbarButtons();
    } else {
      this.selectedBox = null;
    }
  }

  lineDeleted(index) {
    // let boxToRemove = this.boundingBoxes.find(item => item.data.index.row == index);
    // this.canvas.getCanvas().remove(boxToRemove);
    // this.boundingBoxes = this.boundingBoxes.filter(item => item.data.index.row != index);
    // this.sortBoxes();
    // this.updateBoundingBoxesIndexes() 
  }

  sortBoxes() {
    this.boundingBoxes.sort((a: Rect, b: Rect) => a.top - b.top);
  }

  onLinesChanged(updatedLines: Letter[]) {
    this.lines = updatedLines;
    this.updateToolbarButtons();
    this.autoSave();
  }

  private autoSave(): void {
    // Only auto-save if we have an existing transliteration (already saved once)
    if (!this.transliterationId || !this.textId) return;

    if (this.autoSaveTimer) clearTimeout(this.autoSaveTimer);
    this.autoSaveTimer = setTimeout(() => {
      const lines = this.lines.map(line => line.letter);
      let dimensions: Dimensions[];
      if (this.ocrCropArea) {
        dimensions = this.boundingBoxes.map(box => new Dimensions(
          box.left - this.ocrCropArea.left,
          box.top - this.ocrCropArea.top,
          box.getScaledHeight(),
          box.getScaledWidth()
        ));
      } else {
        dimensions = this.boundingBoxes.map(box =>
          new Dimensions(box.left, box.top, box.getScaledHeight(), box.getScaledWidth())
        );
      }

      this.curedService.createSubmission(
        this.textId, this.transliterationId, lines, dimensions, null,
        this.isCuratedKraken, this.isCuratedVlm
      ).subscribe(
        result => { this.transliterationId = result; },
        () => {}
      );
    }, this.AUTO_SAVE_DEBOUNCE_MS);
  }

  updateTransliterationIndexes() {
    this.lines.forEach((line, row) => {
      line.index = new Index(row, 0);
    });
    this.updateToolbarButtons();
  }

  @HostListener('document:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent) {
    if (event.ctrlKey && event.key === 'n') {
      event.preventDefault();
      this.restart();
    }
  }

  restart() {
    if (!confirm("Are you sure you are done with this text?")) {
      return;
    }
    this.toolbarService.clearButtons();
    location.reload();
    return;

    this.stage = 0;
    this.textId = null;
    this.transliterationId = null;
    this.backgroundImage = null;
    this.isLoadedFromServer = false;
    this.isCuratedKraken = false;
    this.isCuratedVlm = false;
    this.boundingBoxes = [];
    this.lines = [];
    this.lineEditor.hardReset();
    this.canvas.hardReset();
  }

  fetchBoundingBoxes(allDimensions: Dimensions[] = [], selecteAreaBox = null) {
    let boundingBoxes = [];

    let row = 0;
    for (let dimensions of allDimensions) {
      let x = dimensions.x
      let y = dimensions.y
      if (selecteAreaBox) {
        x += selecteAreaBox.left
        y += selecteAreaBox.top
      }

      let rect = this.canvas.makeRectangle(x, y, dimensions.width, dimensions.height,
        this.canvas.DEFAULT_RECT_FILL, 'blue', true, new Index(row, 0), true)

      boundingBoxes.push(rect);
      row++;
    }

    this.boundingBoxes = boundingBoxes;

    if (selecteAreaBox) {
      this.canvas.getCanvas().remove(selecteAreaBox);
    }

    this.canvas.addRectangles(boundingBoxes);
    this.updateBoundingBoxesIndexes();
  }

  fetchTransliterations(lines: string[]) {
    this.transliterationResult = lines;
    this.lines = [];
    this.transliterationResult.forEach(line => {
      this.lines.push(new Letter(line));
    })
    this.lines = this.addIndexes(this.lines);
    if (this.lineEditor) {
      this.lineEditor.setLines(this.lines);
    }
  }

  processTransliteration(lines: string[], dimensions: Dimensions[], isBoxesFromServer: boolean = false) {
    this.fetchTransliterations(lines)

    if (isBoxesFromServer) {
      this.fetchBoundingBoxes(dimensions, null);
    } else {
      this.fetchBoundingBoxes(dimensions, this.selectedBox);
    }

    this.isLoading = false;
    this.toolbarService.setLoading(false);
    this.stage = 5;
    this.updateUrl();
    this.updateToolbarButtons();
    this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.addMode];
    this.canvas.changeMode(CanvasMode.Pan);
  }



  updateBoundingBoxesIndexes() {
    this.boundingBoxes.forEach((box, row) => {
      box.data = new RectData(new Index(row, 0));
    });
  }

  goBack(fromBrowser: boolean = false) {
    // When triggered by browser back button, URL is already correct — use replaceState
    const replace = fromBrowser;
    if (this.stage == 2) {
      // From visualizer back to thumbnails or upload
      this.backgroundImage = null;
      this.selectedBox = null;
      this.canvas.hardReset();
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode];
      if (this.pdfFile == null) {
        // Navigate to dashboard (clears query params)
        this.stage = 0;
        this.updateUrl(replace);
      } else {
        this.stage = 1;
        this.updateUrl(replace);
        this.updateToolbarButtons();
      }
    } else if (this.stage == 5) {
      // From results back to visualizer (stage 2)
      this.stage = 2;
      this.updateUrl(replace);
      this.canvas.removeAllRects();
      // Also remove the stable OCR selection box
      if (this.ocrSelectionBox) {
        this.canvas.getCanvas().remove(this.ocrSelectionBox);
        this.ocrSelectionBox = null;
      }
      this.ocrCropArea = null;
      this.boundingBoxes = [];
      this.lines = [];
      this.selectedBox = null;
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode];
      this.updateToolbarButtons();
    } else if (this.stage == 1) {
      // From thumbnails back to upload - navigate to dashboard
      this.stage = 0;
      this.updateUrl(replace);
    }
  }


  boxAdded(newRect: Rect) {
    if (this.stage == 2) {
      // In stage 2, store as selection box for cropping (replace previous selection)
      if (this.selectedBox) {
        this.canvas.getCanvas().remove(this.selectedBox);
      }
      this.selectedBox = newRect;
      this.updateToolbarButtons();
    } else if (this.stage == 5) {
      // In stage 5, allow adding new bounding boxes manually
      this.boundingBoxes.push(newRect);
      this.sortBoxes();
      this.updateBoundingBoxesIndexes();
      this.updateToolbarButtons();
    }
  }

  exportResult() {
    var lines = `Transliterations generated by CuReD (https://ben-digpasts.com/cured)\n\n`;
    this.lines.forEach(line => {
      lines += line.letter + "\n";
    })

    var transliteratinsBlob = new Blob([lines], { type: "text/plain;charset=utf-8" });
    saveAs(transliteratinsBlob, `CuReD-Result.txt`);
  }

  exportAtfEbl() {
    let content = "&P123456 = CuReD Export\n#project: ebl\n#atf: lang akk\n#atf: use unicode\n@tablet\n@obverse\n";

    this.lines.forEach((line, index) => {
      // Always start with the Raw text (because this.lines is kept raw by the editor)
      let text = line.letter;

      // Convert to ATF using the service (this handles all replacements)
      text = this.atfConverter.toAtf(text);

      // Clean up internal tags like @reading{...} for final export
      text = this.atfConverter.cleanForExport(text);

      // Ensure line numbering
      if (!/^\d+\.?\s+/.test(text) && !/^\d+\.'\s*/.test(text) && !/^\d+'\.?\s*/.test(text)) {
        content += `${index + 1}. ${text}\n`;
      } else {
        content += `${text}\n`;
      }
    });

    var blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    saveAs(blob, `CuReD-Export.atf`);
  }

  setHighlightByQuery(query: string) {
    let index = null;
    this.lines.forEach((line, lindeInex) => {
      if (line.letter.includes(query)) {
        index = new Index(lindeInex, 0);
        return;
      }
    })

    if (index == null) {
      return;
    }

    this.updateCanvasSelectedBox(index);
    this.updateTextViewerLetters(index);
  }

  transliterationLineHover(event: LetterHover) {
    if (event.active) {
      if (this.highlightQuery) { // first hover won't remove highlight
        this.highlightQuery = null;
        return;
      }
      this.updateCanvasSelectedBox(event.letterIndex);
      this.updateTextViewerLetters(event.letterIndex);
    }

  }

  boxSelectionChanged(index) {
    this.updateTextViewerLetters(index);
  }

  onRegexMatchLines(lineIndices: number[]) {
    // Reset all boxes to regular
    this.boundingBoxes.forEach(box => {
      this.canvas.fillBoxRegular(box);
    });
    // Highlight boxes at matching line indices
    lineIndices.forEach(idx => {
      if (idx < this.boundingBoxes.length) {
        this.canvas.markBoxForAction(this.boundingBoxes[idx], true);
      }
    });
  }

  updateCanvasSelectedBox(letterIndex: Index) {
    if (letterIndex == null) {
      return;
    }

    let row = letterIndex.row;
    let selectedRect = undefined;
    if (this.boundingBoxes.length > row) {
      selectedRect = this.boundingBoxes[row];
    }

    this.canvas.changeSelection(selectedRect);
  }

  updateTextViewerLetters(index: Index) {
    if (this.lines == null || this.lines.length == 0 || this.lineEditor == null) {
      return;
    }

    this.lineEditor.setNewSelectedLine(index);
  }

  addIndexes(letters: Letter[]) {
    for (let row = 0; row < letters.length; row++) {
      letters[row].index = new Index(row, 0);

    }
    return letters;
  }

  /** Convert a data URL (e.g. from canvas.toDataURL) to a File object. */
  private dataUrlToFile(dataUrl: string, filename: string): File {
    const arr = dataUrl.split(',');
    const mime = arr[0].match(/:(.*?);/)[1];
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    return new File([u8arr], filename, { type: mime });
  }

  // ============================================
  // Dashboard List Methods (moved from AdminPanel)
  // ============================================

  loadTransliterationList() {
    this.textService.list().subscribe(data => {
      this.curedTexts = data;
      this.collectExistingParts();
      this.loadTransliterationIds();
    });
  }

  // ============================================
  // Project Methods
  // ============================================

  // ============================================
  // Flat Project Methods
  // ============================================

  loadProjects() {
    this.projectService.list().subscribe(data => {
      this.projects = data;
    });
  }

  openProject(project: ProjectPreview) {
    this.selectedProject = project;
    this.showProjectList = false;
    this.projectService.getTexts(project.project_id).subscribe(data => {
      this.curedTexts = data;
      this.collectExistingParts();
      this.loadTransliterationIds();
    });
  }

  collectExistingParts() {
    const parts = new Set<number>();
    this.curedTexts.forEach(t => {
      if (t.part) {
        const match = t.part.match(/(\d+)/);
        if (match) parts.add(parseInt(match[1], 10));
      }
    });
    this.existingParts = Array.from(parts).sort((a, b) => a - b);
  }

  backToProjects() {
    this.selectedProject = null;
    this.showProjectList = true;
    this.curedTexts = [];
    this.loadProjects();
  }

  createProject() {
    const name = this.newProjectName.trim();
    if (!name) return;
    this.projectService.create(name).subscribe(() => {
      this.newProjectName = '';
      this.loadProjects();
    });
  }

  deleteProject(project: ProjectPreview, event: Event) {
    event.stopPropagation();
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: { message: `Delete project "${project.name}"? Texts will become unassigned.` }
    });
    dialogRef.afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.projectService.delete(project.project_id).subscribe(
          () => {
            if (this.selectedProject?.project_id === project.project_id) {
              this.backToProjects();
            } else {
              this.loadProjects();
            }
          },
          (err) => {
            this.notificationService.showError(err.error?.detail || 'Delete failed');
          }
        );
      }
    });
  }

  renameProject(project: ProjectPreview, event: Event) {
    event.stopPropagation();
    const newName = prompt('Rename project:', project.name);
    if (newName && newName.trim()) {
      this.projectService.rename(project.project_id, newName.trim()).subscribe(() => {
        project.name = newName.trim();
      });
    }
  }

  loadUnassignedTexts() {
    this.selectedProject = { project_id: -1, name: 'Unassigned' } as any;
    this.showProjectList = false;
    this.projectService.getUnassignedTexts().subscribe(data => {
      this.curedTexts = data;
      this.collectExistingParts();
      this.loadTransliterationIds();
    });
  }

  private loadTransliterationIds() {
    for (const item of this.curedTexts) {
      this.curedService.getTextTransliterations(item.text_id).subscribe(
        transliterations => {
          if (transliterations && transliterations.length > 0) {
            const latest = transliterations[transliterations.length - 1];
            item.latest_transliteration_id = latest.transliteration_id;
            this.loadListThumbnail(item);
          }
        },
        () => {}
      );
    }
  }

  private loadListThumbnail(item: TextPreview) {
    if (item.latest_transliteration_id) {
      this.curedService.getImage(item.text_id, item.latest_transliteration_id).subscribe(
        blob => {
          const url = URL.createObjectURL(blob);
          item._thumbnailUrl = this.sanitizer.bypassSecurityTrustUrl(url);
        },
        () => {}
      );
    }
  }

  get availableLabels(): string[] {
    const labels = new Set<string>();
    for (const item of this.curedTexts) {
      if (item.labels && item.labels.length > 0) {
        item.labels.forEach(l => { if (l) labels.add(l); });
      } else if (item.label) {
        labels.add(item.label);
      }
    }
    return Array.from(labels).sort();
  }

  get filteredTexts(): TextPreview[] {
    let items: TextPreview[];
    if (this.selectedLabelFilter === null) {
      items = [...this.curedTexts];
    } else {
      items = this.curedTexts.filter(item =>
        (item.labels && item.labels.includes(this.selectedLabelFilter)) ||
        (!item.labels?.length && (item.label || '') === this.selectedLabelFilter)
      );
    }

    if (this.sortColumn) {
      const dir = this.sortDirection === 'asc' ? 1 : -1;
      items.sort((a, b) => {
        let valA: any = a[this.sortColumn];
        let valB: any = b[this.sortColumn];

        // Handle identifier column specially
        if (this.sortColumn === 'identifier') {
          valA = this.getItemIdentifier(a).toLowerCase();
          valB = this.getItemIdentifier(b).toLowerCase();
        }

        if (valA == null) valA = '';
        if (valB == null) valB = '';

        if (typeof valA === 'number' && typeof valB === 'number') {
          return (valA - valB) * dir;
        }

        return String(valA).localeCompare(String(valB)) * dir;
      });
    }

    return items;
  }

  toggleSort(column: string): void {
    if (this.sortColumn === column) {
      this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortColumn = column;
      this.sortDirection = column === 'last_modified' ? 'desc' : 'asc';
    }
  }

  setLabelFilter(label: string | null) {
    this.selectedLabelFilter = label;
  }

  openListItem(item: TextPreview) {
    if (item.latest_transliteration_id) {
      this.router.navigate(['/cured'], {
        queryParams: {
          textId: item.text_id,
          transId: item.latest_transliteration_id
        }
      });
    } else {
      this.curedService.getTextTransliterations(item.text_id).subscribe(
        transliterations => {
          if (transliterations && transliterations.length > 0) {
            const latest = transliterations[transliterations.length - 1];
            this.router.navigate(['/cured'], {
              queryParams: {
                textId: item.text_id,
                transId: latest.transliteration_id
              }
            });
          } else {
            this.router.navigate(['/cured'], {
              queryParams: { textId: item.text_id }
            });
          }
        },
        () => {
          this.router.navigate(['/cured'], {
            queryParams: { textId: item.text_id }
          });
        }
      );
    }
  }

  getItemIdentifiers(item: TextPreview): string[] {
    const ids: string[] = [];
    if (item.text_identifiers) {
      if (item.text_identifiers.museum && item.text_identifiers.museum.name) {
        const fullName = item.text_identifiers.museum.name.trim();
        const abbr = fullName.split(' - ')[0] || fullName;
        const num = item.text_identifiers.museum.number || '';
        ids.push(num ? `${abbr}.${num}` : abbr);
      }
      if (item.text_identifiers.p_number &&
          (item.text_identifiers.p_number.name || item.text_identifiers.p_number.number)) {
        const name = item.text_identifiers.p_number.name || 'P';
        const num = item.text_identifiers.p_number.number;
        if (name === 'P' && num) {
          ids.push(`P-${num}`);
        } else if (num) {
          ids.push(`${name}-${num}`);
        } else {
          ids.push(name);
        }
      }
      if (item.text_identifiers.publication &&
          (item.text_identifiers.publication.name || item.text_identifiers.publication.number)) {
        const pubName = item.text_identifiers.publication.name ? item.text_identifiers.publication.name.trim() : '';
        const pubNum = item.text_identifiers.publication.number || '';
        ids.push(pubNum ? `${pubName} ${pubNum}` : pubName);
      }
    }
    return ids.length > 0 ? ids : ['-'];
  }

  getItemIdentifier(item: TextPreview): string {
    return this.getItemIdentifiers(item).join(' ');
  }

  private labelColorCache: Map<string, { bg: string; color: string; border: string }> = new Map();
  private readonly labelPalette = [
    { bg: '#e3f2fd', color: '#1565c0', border: '#90caf9' },  // blue
    { bg: '#fce4ec', color: '#c62828', border: '#ef9a9a' },  // red
    { bg: '#e8f5e9', color: '#2e7d32', border: '#a5d6a7' },  // green
    { bg: '#fff3e0', color: '#e65100', border: '#ffcc80' },  // orange
    { bg: '#f3e5f5', color: '#6a1b9a', border: '#ce93d8' },  // purple
    { bg: '#e0f7fa', color: '#00695c', border: '#80cbc4' },  // teal
    { bg: '#fff9c4', color: '#f57f17', border: '#fff176' },  // yellow
    { bg: '#fbe9e7', color: '#bf360c', border: '#ffab91' },  // deep orange
    { bg: '#e8eaf6', color: '#283593', border: '#9fa8da' },  // indigo
    { bg: '#efebe9', color: '#4e342e', border: '#bcaaa4' },  // brown
  ];

  getLabelColor(label: string): { bg: string; color: string; border: string } {
    if (!this.labelColorCache.has(label)) {
      let hash = 0;
      for (let i = 0; i < label.length; i++) {
        hash = label.charCodeAt(i) + ((hash << 5) - hash);
      }
      const index = Math.abs(hash) % this.labelPalette.length;
      this.labelColorCache.set(label, this.labelPalette[index]);
    }
    return this.labelColorCache.get(label);
  }

  openLabelDialog(item: TextPreview, event: Event) {
    event.stopPropagation();

    const dialogRef = this.dialog.open(LabelDialogComponent, {
      data: {
        currentLabels: item.labels || [],
        currentLabel: item.label || '',
        existingLabels: this.existingLabels
      }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result === null || result === undefined) { return; }
      const newLabels = result as string[];

      this.textService.updateLabels(item.text_id, newLabels).subscribe(
        () => {
          item.labels = newLabels;
          item.label = newLabels.length > 0 ? newLabels[0] : '';
          for (const l of newLabels) {
            if (l && !this.existingLabels.includes(l)) {
              this.existingLabels.push(l);
            }
          }
          this.existingLabels.sort();
          this.notificationService.showSuccess(newLabels.length > 0 ? `Labels: ${newLabels.join(', ')}` : 'Labels removed');
        },
        () => { this.notificationService.showError('Failed to update labels'); }
      );
    });
  }

  openIdentifierDialog(item: TextPreview, event: Event) {
    event.stopPropagation();

    // Reconstruct raw identifier strings from the parsed {name, number} objects
    const ids = item.text_identifiers;
    const museumRaw = ids && ids.museum && ids.museum.name
      ? (ids.museum.number ? `${ids.museum.name}-${ids.museum.number}` : ids.museum.name) : '';
    const pNumberRaw = ids && ids.p_number && (ids.p_number.name || ids.p_number.number)
      ? (ids.p_number.number ? `${ids.p_number.name}-${ids.p_number.number}` : ids.p_number.name) : '';
    const publicationRaw = ids && ids.publication && (ids.publication.name || ids.publication.number)
      ? (ids.publication.number ? `${ids.publication.name}-${ids.publication.number}` : ids.publication.name) : '';

    const dialogRef = this.dialog.open(IdentifierDialogComponent, {
      data: {
        museumNumber: museumRaw,
        pNumber: pNumberRaw,
        publicationNumber: publicationRaw
      }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result === null || result === undefined) { return; }
      const r = result as IdentifierDialogResult;

      this.textService.updateIdentifiers(
        item.text_id,
        r.museumNumber,
        r.pNumber,
        r.publicationNumber
      ).subscribe(
        () => {
          // Update local model to reflect changes immediately
          if (!item.text_identifiers) {
            item.text_identifiers = {} as any;
          }
          item.text_identifiers.museum = r.museumNumber
            ? this.parseIdentifierValue(r.museumNumber) : null;
          item.text_identifiers.p_number = r.pNumber
            ? this.parseIdentifierValue(r.pNumber) : null;
          item.text_identifiers.publication = r.publicationNumber
            ? this.parseIdentifierValue(r.publicationNumber) : null;
          this.notificationService.showSuccess('Identifiers updated');
        },
        () => { this.notificationService.showError('Failed to update identifiers'); }
      );
    });
  }

  private parseIdentifierValue(value: string): { name: string, number: number } {
    const idx = value.lastIndexOf('-');
    if (idx > 0) {
      const numPart = parseInt(value.substring(idx + 1), 10);
      if (!isNaN(numPart)) {
        return { name: value.substring(0, idx), number: numPart };
      }
    }
    return { name: value, number: 0 };
  }

  deleteListItem(item: TextPreview, event: Event) {
    event.stopPropagation();
    if (!item.latest_transliteration_id) {
      this.curedService.getTextTransliterations(item.text_id).subscribe(
        transliterations => {
          if (transliterations && transliterations.length > 0) {
            const latest = transliterations[transliterations.length - 1];
            item.latest_transliteration_id = latest.transliteration_id;
            this.performListDelete(item);
          } else {
            this.performListDeleteText(item);
          }
        },
        () => { this.performListDeleteText(item); }
      );
      return;
    }
    this.performListDelete(item);
  }

  private performListDelete(item: TextPreview) {
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Transliteration',
        message: `Delete transliteration for BEN ${item.text_id}? This will also delete the associated image.`,
        confirmText: 'Delete',
        warn: true
      }
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed) { return; }
      this.curedService.deleteTransliteration(item.text_id, item.latest_transliteration_id).subscribe(
        () => {
          this.curedTexts = this.curedTexts.filter(t => t !== item);
          this.notificationService.showSuccess('Transliteration deleted');
        },
        () => { this.notificationService.showError('Failed to delete transliteration'); }
      );
    });
  }

  private performListDeleteText(item: TextPreview) {
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Text Entry',
        message: `Delete text entry BEN ${item.text_id}? This entry has no saved transliteration.`,
        confirmText: 'Delete',
        warn: true
      }
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed) { return; }
      this.curedService.deleteText(item.text_id).subscribe(
        () => {
          this.curedTexts = this.curedTexts.filter(t => t !== item);
          this.notificationService.showSuccess('Text entry deleted');
        },
        () => { this.notificationService.showError('Failed to delete text entry'); }
      );
    });
  }

  // ============================================
  // Training Status Methods
  // ============================================

  loadTrainingStatus() {
    this.curedService.getTrainingStatus().subscribe(
      status => {
        this.trainingStatus = status;
        // Check if training is in progress
        if (status.currentTraining &&
            (status.currentTraining.status === 'training' || status.currentTraining.status === 'preparing')) {
          this.isTraining = true;
          this.trainingProgress = status.currentTraining;
          this.startTrainingProgressPolling();
        }
      },
      () => {
        // Use placeholder data if endpoint not available
        this.trainingStatus = {
          curatedTexts: 0,
          previousLines: 0,
          newLines: 0,
          totalLines: 0,
          requiredForNextTraining: 100,
          progress: 0,
          isReady: false,
          lastTraining: null,
          currentTraining: null
        };
      }
    );
  }

  loadCuratedStats() {
    this.curedService.getCuratedStats().subscribe(
      stats => { this.curatedStats = stats; },
      () => {}
    );
  }

  startTraining() {
    if (!this.trainingStatus.isReady) {
      this.notificationService.showError('Not enough training data. Need at least 1000 curated lines.');
      return;
    }

    if (this.isTraining) {
      this.notificationService.showWarning('Training is already in progress.');
      return;
    }

    if (!this.trainingModelName || !this.trainingModelName.trim()) {
      this.notificationService.showError('Please enter a name for this model (e.g. book name).');
      return;
    }

    // Build model name: {BaseModelKey}_{UserName}
    const baseKey = this.selectedBaseModel.charAt(0).toUpperCase() + this.selectedBaseModel.slice(1);
    const sanitizedName = this.trainingModelName.trim().replace(/[^a-zA-Z0-9_-]/g, '_');
    const modelName = `${baseKey}_${sanitizedName}`;

    this.isTraining = true;
    this.epochHistory = [];
    this.trainingProgress = { status: 'preparing', current_epoch: 0, total_epochs: 50, epoch_history: [] };

    this.curedService.startTraining(50, modelName, this.selectedBaseModel).subscribe(
      response => {
        this.notificationService.showSuccess('Training started!');
        this.startTrainingProgressPolling();
      },
      error => {
        this.isTraining = false;
        this.trainingProgress = null;
        const message = error.error?.detail || 'Failed to start training';
        this.notificationService.showError(message);
      }
    );
  }

  cancelTraining() {
    if (!this.isTraining) {
      return;
    }

    this.curedService.cancelTraining().subscribe(
      () => {
        this.notificationService.showInfo('Training cancelled');
        this.stopTrainingProgressPolling();
        this.isTraining = false;
        this.trainingProgress = null;
        this.loadTrainingStatus();
      },
      error => {
        const message = error.error?.detail || 'Failed to cancel training';
        this.notificationService.showError(message);
      }
    );
  }

  private startTrainingProgressPolling() {
    // Clear any existing interval
    this.stopTrainingProgressPolling();

    // Poll every 2 seconds
    this.trainingProgressInterval = setInterval(() => {
      this.curedService.getTrainingProgress().subscribe(
        progress => {
          this.trainingProgress = progress;

          // Update epoch history from backend
          if (progress.epoch_history && progress.epoch_history.length > 0) {
            this.epochHistory = progress.epoch_history;
          }

          if (progress.status === 'completed') {
            this.stopTrainingProgressPolling();
            this.isTraining = false;
            const earlyStopped = progress.early_stopped ? ' (early stopped)' : '';
            this.notificationService.showSuccess(`Training completed${earlyStopped}! Model: ${progress.model_name}`);
            this.loadTrainingStatus();
            this.loadModels();
            this.loadAvailableOcrModels(); // Refresh OCR dropdown with new model
          } else if (progress.status === 'failed') {
            this.stopTrainingProgressPolling();
            this.isTraining = false;
            this.notificationService.showError(`Training failed: ${progress.error || 'Unknown error'}`);
            this.loadTrainingStatus();
          } else if (progress.status === 'cancelled' || progress.status === 'idle') {
            this.stopTrainingProgressPolling();
            this.isTraining = false;
            this.trainingProgress = null;
          }
        },
        () => {
          // Silently ignore polling errors
        }
      );
    }, 2000);
  }

  private stopTrainingProgressPolling() {
    if (this.trainingProgressInterval) {
      clearInterval(this.trainingProgressInterval);
      this.trainingProgressInterval = null;
    }
  }

  loadModels() {
    this.curedService.getActiveModel().subscribe(
      response => {
        this.modelInfo = {
          name: response.name,
          isPretrained: response.is_pretrained,
          sizeMb: response.size_mb,
          lastModified: response.last_modified
        };
      },
      () => {
        // Keep default model info on error
      }
    );
  }

  loadBaseModelsMetadata() {
    this.curedService.getBaseModelsMetadata().subscribe(
      response => {
        this.baseModelsMetadata = response;
      },
      () => {
        // Keep empty metadata on error
      }
    );
  }

  loadAvailableOcrModels() {
    this.curedService.getAvailableOcrModels().subscribe(
      response => {
        this.availableOcrModels = response.models;
        // Kraken models are statically defined - no dynamic loading needed
      },
      () => {
        // Keep static defaults on error
      }
    );
  }

  // Select OCR model from category buttons
  selectOcrModel(modelValue: string) {
    // Only allow selection if model is available
    if (this.isModelAvailable(modelValue)) {
      this.selectedOcrModel = modelValue;
    }
  }

  // Check if the selected model requires an API key
  requiresApiKey(modelValue?: string): boolean {
    const model = modelValue || this.selectedOcrModel;
    const apiModels = ['nemotron_cloud', 'gpt4_vision', 'claude_vision', 'gemini_vision', 'qwen3_vl_cloud'];
    return apiModels.includes(model);
  }

  // Get placeholder text for API key input based on selected model
  getApiKeyPlaceholder(): string {
    if (this.selectedOcrModel === 'nemotron_cloud') {
      return 'nvapi-... (from build.nvidia.com)';
    }
    return 'Enter your API key...';
  }

  // Get selected model info for display
  getSelectedModelInfo(): {label: string; description?: string} | null {
    for (const category of this.ocrModelCategories) {
      const model = category.models.find(m => m.value === this.selectedOcrModel);
      if (model) {
        return model;
      }
    }
    return null;
  }

  getKrakenTrainingTarget(): number {
    return this.trainingStatus.requiredForNextTraining || 100;
  }

  getVlmTrainingTarget(): number {
    return 200;
  }

  getKrakenModels(): Array<{value: string; label: string}> {
    const cpuCategory = this.ocrModelCategories.find(c => c.name === 'CPU');
    return cpuCategory ? cpuCategory.models.filter(m => this.isModelAvailable(m.value)) : [];
  }

  getOllamaModels(): Array<{value: string; label: string}> {
    const gpuCategory = this.ocrModelCategories.find(c => c.name === 'Local GPU');
    return gpuCategory ? gpuCategory.models.filter(m => this.isModelAvailable(m.value)) : [];
  }

  getApiModels(): Array<{value: string; label: string}> {
    const result: Array<{value: string; label: string}> = [];
    const cloudCategory = this.ocrModelCategories.find(c => c.name === 'Ollama Cloud');
    if (cloudCategory) { result.push(...cloudCategory.models); }
    const apiCategory = this.ocrModelCategories.find(c => c.name === 'API');
    if (apiCategory) { result.push(...apiCategory.models.filter(m => m.value !== 'gpt4_vision')); }
    return result;
  }

  // Check if a model is locally available
  isModelAvailable(modelValue: string): boolean {
    return this.modelAvailability[modelValue] ?? false;
  }

  // Get tooltip for model button
  getModelTooltip(model: {value: string; label: string; description?: string}): string {
    if (this.isModelAvailable(model.value)) {
      return model.description || model.label;
    } else {
      return `Not installed - Run: ollama pull ${this.getOllamaModelName(model.value)}`;
    }
  }

  // Get Ollama model name for download instruction
  private getOllamaModelName(modelValue: string): string {
    const ollamaNames: { [key: string]: string } = {
      'deepseek_ocr': 'deepseek-ocr',
      'llama4_vision': 'llama4:scout',
      'qwen3_vl_32b': 'qwen3-vl:32b',
      'qwen3_vl_8b': 'qwen3-vl:8b',
      'qwen3_vl_4b': 'qwen3-vl:4b',
      'mistral_small_vision': 'mistral-small3.1',
      'llava_34b': 'llava:34b',
      // Cloud models (no download needed)
      'qwen3_vl_235b_cloud': 'qwen3-vl:235b-cloud',
      'qwen3_vl_235b_thinking': 'qwen3-vl:235b-thinking-cloud',
    };
    return ollamaNames[modelValue] || modelValue;
  }

  // Load available Ollama models from backend
  loadAvailableOllamaModels() {
    this.curedService.getOllamaModels().subscribe(
      models => {
        this.availableOllamaModels = models;
        // Update availability for preset models
        for (const model of models) {
          const normalizedName = model.toLowerCase();
          if (normalizedName.includes('deepseek')) {
            this.modelAvailability['deepseek_ocr'] = true;
          }
          if (normalizedName.includes('llama4')) {
            this.modelAvailability['llama4_vision'] = true;
          }
          if (normalizedName.includes('qwen3-vl:32b')) {
            this.modelAvailability['qwen3_vl_32b'] = true;
          }
          if (normalizedName.includes('qwen3-vl:8b') || normalizedName.includes('qwen3-vl:latest')) {
            this.modelAvailability['qwen3_vl_8b'] = true;
          }
          if (normalizedName.includes('qwen3-vl:4b')) {
            this.modelAvailability['qwen3_vl_4b'] = true;
          }
          if (normalizedName.includes('mistral-small')) {
            this.modelAvailability['mistral_small_vision'] = true;
          }
          if (normalizedName.includes('llava:34b') || normalizedName.includes('llava-v1.6:34b')) {
            this.modelAvailability['llava_34b'] = true;
          }
        }
      },
      () => {
        // Ollama not available
        this.availableOllamaModels = [];
      }
    );
  }

  // ============================================
  // Translation Methods
  // ============================================

  /**
   * Load metadata for the current text (museum number, etc.)
   * Called after loading a transliteration to enable translation lookup.
   */
  loadTextMetadata() {
    if (!this.textId) return;

    // getTextByBenId returns raw NewText with flat fields (museum_id, p_number, publication_id)
    this.textService.getTextByBenId(this.textId).subscribe(
      (text: any) => {
        // Identifiers are flat strings on NewText (e.g. "BM-123456")
        if (text?.museum_id) {
          const parsed = this.parseIdentifierValue(text.museum_id);
          this.currentMuseumName = parsed?.name || '';
          this.currentMuseumNumber = parsed?.number || 0;
        }
        this.currentPNumber = text?.p_number || '';
        this.currentPublicationNumber = text?.publication_id || '';

        // Label and part
        if (!this.currentLabel) {
          const labels = text?.labels || [];
          this.currentLabel = labels.length > 0 ? labels[0] : (text?.label || '');
        }
        if (!this.currentPart) {
          this.currentPart = text?.part || '';
        }

        // Check for linked translation
        this.checkForLinkedTranslation();
      },
      () => {
        // Silently fail - translation lookup just won't be available
      }
    );
  }

  /**
   * Check if there's a translation linked to this text by museum number.
   */
  checkForLinkedTranslation() {
    if (!this.currentMuseumName || !this.currentMuseumNumber) {
      this.hasLinkedTranslation = false;
      return;
    }

    this.loadingTranslation = true;
    this.curedService.findTranslation(this.currentMuseumName, this.currentMuseumNumber).subscribe(
      (result: TranslationLookupResult) => {
        this.loadingTranslation = false;
        if (result.found && result.lines) {
          this.hasLinkedTranslation = true;
          this.linkedTranslationLines = result.lines;
        } else {
          this.hasLinkedTranslation = false;
          this.linkedTranslationLines = [];
        }
      },
      () => {
        this.loadingTranslation = false;
        this.hasLinkedTranslation = false;
      }
    );
  }

  /**
   * Toggle the translation view panel.
   */
  toggleTranslationView() {
    this.showTranslationView = !this.showTranslationView;
  }

  /**
   * Insert translation lines into the editor with #tr.en: prefix.
   * Each translation line is inserted after the corresponding transliteration line.
   */
  insertTranslation() {
    if (!this.linkedTranslationLines || this.linkedTranslationLines.length === 0) {
      this.notificationService.showWarning('No translation lines to insert');
      return;
    }

    if (!this.lines || this.lines.length === 0) {
      this.notificationService.showWarning('No transliteration lines to merge with');
      return;
    }

    // Create new lines array with translations interleaved
    const mergedLines: Letter[] = [];
    const maxLen = Math.max(this.lines.length, this.linkedTranslationLines.length);

    for (let i = 0; i < maxLen; i++) {
      // Add transliteration line if exists
      if (i < this.lines.length) {
        mergedLines.push(this.lines[i]);
      }
      // Add translation line if exists (with ATF translation prefix)
      if (i < this.linkedTranslationLines.length) {
        const translationLine = this.linkedTranslationLines[i];
        // Format as ATF translation: #tr.en: [translation text]
        const formattedLine = translationLine.startsWith('#tr.')
          ? translationLine
          : `#tr.en: ${translationLine}`;
        mergedLines.push(new Letter(formattedLine));
      }
    }

    // Update lines and reindex
    this.lines = this.addIndexes(mergedLines);
    if (this.lineEditor) {
      this.lineEditor.setLines(this.lines);
    }

    this.showTranslationView = false;
    this.notificationService.showSuccess(`Inserted ${this.linkedTranslationLines.length} translation lines`);
  }

  // ─── Detect Lines (Kraken segmentation) ────────────────────

  public isDetectingLines: boolean = false;

  detectLines() {
    // Get the background image from canvas to respect any crop area
    const bgImage = this.canvas?.getCanvas().backgroundImage as unknown as FabricImage;
    if (!bgImage) {
      this.notificationService.showError('No image loaded');
      return;
    }

    // Determine the image region to send for line detection
    let imageData: string;
    let cropOffset: { left: number; top: number } | null = null;

    if (this.ocrCropArea) {
      // New images: use the stored crop area
      imageData = bgImage.toDataURL({
        left: this.ocrCropArea.left,
        top: this.ocrCropArea.top,
        width: this.ocrCropArea.width,
        height: this.ocrCropArea.height
      });
      cropOffset = { left: this.ocrCropArea.left, top: this.ocrCropArea.top };
    } else if (this.boundingBoxes.length > 0 && this.isLoadedFromServer) {
      // Old full-page images: infer text region from existing bounding boxes
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const box of this.boundingBoxes) {
        minX = Math.min(minX, box.left);
        minY = Math.min(minY, box.top);
        maxX = Math.max(maxX, box.left + box.getScaledWidth());
        maxY = Math.max(maxY, box.top + box.getScaledHeight());
      }
      const padding = 50;
      const left = Math.max(0, minX - padding);
      const top = Math.max(0, minY - padding);
      imageData = bgImage.toDataURL({
        left: left,
        top: top,
        width: (maxX - minX) + padding * 2,
        height: (maxY - minY) + padding * 2,
      });
      cropOffset = { left, top };
    } else {
      // No crop area and no boxes: send full image
      imageData = bgImage.toDataURL({});
    }

    this.isDetectingLines = true;

    this.curedService.detectLines(imageData).subscribe({
      next: (result) => {
        this.isDetectingLines = false;

        if (result.error) {
          this.notificationService.showError('Line detection failed: ' + result.error);
          return;
        }

        if (!result.dimensions || result.dimensions.length === 0) {
          this.notificationService.showWarning('No lines detected in the image');
          return;
        }

        // Remove existing bounding boxes from canvas
        if (this.boundingBoxes.length > 0) {
          for (const box of this.boundingBoxes) {
            this.canvas.getCanvas().remove(box);
          }
          this.boundingBoxes = [];
        }

        // Add detected boxes, offsetting by crop region
        this.fetchBoundingBoxes(result.dimensions, cropOffset);
        this.notificationService.showSuccess(`Detected ${result.dimensions.length} lines`);
        this.updateToolbarButtons();
      },
      error: (err) => {
        this.isDetectingLines = false;
        this.notificationService.showError('Line detection failed: ' + (err.error?.detail || err.message));
      }
    });
  }

  // ─── TEI Lex-0 Validation ──────────────────────────────────

  getTeiValidCount(): number {
    return this.teiValidationResults?.filter(e => e.status === 'valid').length || 0;
  }

  getTeiErrorCount(): number {
    return this.teiValidationResults?.filter(e => e.status === 'error').length || 0;
  }

  getTeiWarningCount(): number {
    return this.teiValidationResults?.filter(e => e.status === 'warning').length || 0;
  }

  selectTeiEntry(entry: TeiEntryResult): void {
    this.selectedTeiEntry = this.selectedTeiEntry === entry ? null : entry;
  }

  retryTeiEntry(entry: TeiEntryResult): void {
    if (!entry.errors.length) return;

    entry['retrying'] = true;
    this.curedService.retryTeiEntry(
      entry.xml,
      entry.errors,
      this.getEffectiveModel(),
      this.apiKey || undefined
    ).subscribe({
      next: (result) => {
        // Update the entry in the results list
        const idx = this.teiValidationResults.indexOf(entry);
        if (idx >= 0) {
          this.teiValidationResults[idx] = result;
          // Also update the corresponding line in the text editor
          if (this.lines && idx < this.lines.length) {
            this.lines[idx] = new Letter(result.xml);
          }
        }
        entry['retrying'] = false;
        this.notificationService.showSuccess(`Entry "${result.lemma}" ${result.status === 'valid' ? 'now valid' : 'still has errors'}`);
      },
      error: (err) => {
        entry['retrying'] = false;
        this.notificationService.showError('Retry failed: ' + (err.error?.detail || err.message));
      }
    });
  }

  closeTeiValidation(): void {
    this.showTeiValidation = false;
  }

}
