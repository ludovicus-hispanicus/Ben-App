import { AfterViewInit, Component, ElementRef, EventEmitter, HostListener, OnInit, OnDestroy, Output, QueryList, ViewChild, ViewChildren } from '@angular/core';
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
import { MoveTextDialogComponent, MoveTextDialogData, MoveTextDialogResult } from '../common/move-text-dialog/move-text-dialog.component';
import { PartDialogComponent, PartDialogResult } from '../common/part-dialog/part-dialog.component';
import { SelectedPage } from '../../models/pages';
import { HttpClient } from '@angular/common/http';
import { AuthService } from 'src/app/auth/auth.service';
import { Location } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { ToolbarService } from 'src/app/services/toolbar.service';
import { AtfConverterService } from 'src/app/services/atf-converter.service';
import { TextService } from 'src/app/services/text.service';
import { DatasetService } from 'src/app/services/dataset.service';
import { TextPreview, DatasetPreview, GuideLineData } from 'src/app/models/cured';
import { GuideLineService } from 'src/app/services/guide-line.service';
import { DomSanitizer } from '@angular/platform-browser';
import { ProductionService, KwicResult } from 'src/app/services/production.service';

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

  // Guide lines
  public guideColorPresets: { color: string; label: string }[] = [];
  public guideHexColor: string = '#ffa500';
  public guideOpacity: number = 40;
  private currentGuides: GuideLineData[] = [];

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
  public isCurated: boolean = false;

  public goToPage: number = 1;
  public uploadedImageBlob: File = null;

  public textId: number = null;
  public transliterationId: number = null;

  public isLoadedFromServer: boolean = false;

  // Dirty state tracking
  public hasUnsavedChanges: boolean = false;

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
  public leftPanelWidth: number = 50; // percentage
  private isResizing: boolean = false;
  private resizeHandler: (e: MouseEvent | TouchEvent) => void;
  private resizeEndHandler: () => void;
  private queryParamsSub: Subscription;

  // Dashboard list (stage 0)
  public curedTexts: TextPreview[] = [];
  public searchQuery: string = '';
  public sortColumn: string = 'last_modified';
  public sortDirection: 'asc' | 'desc' = 'desc';
  public textViewMode: 'grid' | 'list' = 'list';

  // Text list pagination
  public textsPage: number = 0;
  public textsPageSize: number = 500;
  public textsTotal: number = 0;

  // Multi-selection for batch operations
  public selectedTexts: Set<number> = new Set();
  public lastSelectedTextIndex: number = -1;
  public isBatchCurating: boolean = false;

  // Text context menu (grid view)
  public textContextMenuVisible: boolean = false;
  public textContextMenuX: number = 0;
  public textContextMenuY: number = 0;
  public textContextMenuItem: TextPreview | null = null;

  // KWIC concordance search
  public kwicResults: KwicResult[] = [];
  public kwicSearchActive: boolean = false;
  public kwicSearchQuery: string = '';
  public isSearchingKwic: boolean = false;

  // Dataset state (flat list)
  public datasets: DatasetPreview[] = [];
  public datasetSearchQuery: string = '';
  public selectedDataset: DatasetPreview | null = null;
  public showDatasetList: boolean = true;
  public newDatasetName: string = '';

  // Dataset card selection & inline rename
  public selectedDatasetCard: DatasetPreview | null = null;
  public editingDataset: DatasetPreview | null = null;
  public editingDatasetName: string = '';
  private datasetRenameTimer: any = null;
  private datasetRenameCancelled: boolean = false;

  // Dataset context menu
  public datasetContextMenuVisible: boolean = false;
  public datasetContextMenuX: number = 0;
  public datasetContextMenuY: number = 0;
  public datasetContextMenuNode: DatasetPreview | null = null;

  // Translation state
  public hasLinkedTranslation: boolean = false;
  public linkedTranslationLines: string[] = [];
  public showTranslationView: boolean = false;
  public loadingTranslation: boolean = false;
  public currentMuseumName: string = '';
  public currentMuseumNumber: number = 0;
  public currentPNumber: string = '';
  public currentPublicationNumber: string = '';

  // Text list navigation (for navigating between texts in editing mode)
  public textListNavActive: boolean = false;

  get currentTextListIndex(): number {
    if (!this.textListNavActive || !this.textId) return -1;
    return this.filteredTexts.findIndex(t => t.text_id === this.textId);
  }

  get canNavigatePrev(): boolean {
    return this.currentTextListIndex > 0;
  }

  get canNavigateNext(): boolean {
    const idx = this.currentTextListIndex;
    return idx >= 0 && idx < this.filteredTexts.length - 1;
  }

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

  // Sub-model selection for API providers (e.g., gemini-3.1-flash-preview vs gemini-3.1-pro-preview)
  public selectedSubModel: string = '';

  // Available sub-models for each API provider
  public apiSubModels: { [key: string]: Array<{value: string; label: string; description: string}> } = {
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
  // Post-OCR correction rules (e.g. "akkadian" for glottal stop, reference signs)
  public correctionRules: string = '';
  public correctionRulesOptions: Array<{value: string; label: string; description: string}> = [
    { value: '', label: 'None', description: 'No post-OCR corrections' },
    { value: 'akkadian', label: 'Akkadian', description: 'Fix glottal stops (ʾ), reference signs (↑), special chars' },
  ];

  // Line detection / box mode
  public boxMode: string = 'estimate';
  public boxModeOptions: Array<{value: string; label: string; description: string}> = [
    { value: 'none', label: 'None', description: 'No line boxes — text only' },
    { value: 'estimate', label: 'Estimate', description: 'Evenly divide image height by line count' },
    { value: 'predict', label: 'Predict (Kraken)', description: 'Kraken segmentation for line boundaries' },
  ];

  // OCR prompt/mode selection (for VLM models like Ollama)
  public selectedOcrPrompt: string = 'dictionary';
  public ocrPromptModes: Array<{value: string; label: string; description: string}> = [
    { value: 'plain', label: 'Plain', description: 'Simple text extraction' },
    { value: 'markdown', label: 'Markdown', description: 'Formatted with markdown' },
    { value: 'dictionary', label: 'Dictionary', description: 'Akkadian dictionary entries' },
    { value: 'ahw_refentry', label: 'AHw RefEntry', description: 'AHw cross-reference entries (plain text, special chars)' },
    { value: 'tei_lex0', label: 'TEI Lex-0', description: 'Two-stage: OCR → TEI XML encoding (with XSD validation)' },
  ];

  // TEI encoding model selection (Stage 2 of the two-stage pipeline)
  public selectedTeiModel: string = 'gemini';
  public teiApiKey: string = '';
  public teiEncodingModels: Array<{value: string; label: string; provider: string; model: string; needsApiKey: boolean; description: string}> = [
    { value: 'gemini', label: 'Gemini Flash-Lite', provider: 'gemini', model: 'gemini-3.1-flash-lite-preview', needsApiKey: true, description: 'Fast, free tier' },
    { value: 'gemini_pro', label: 'Gemini Pro', provider: 'gemini', model: 'gemini-3.1-pro-preview', needsApiKey: true, description: 'Most capable' },
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
    models: Array<{value: string; label: string; description?: string; trained?: boolean}>;
  }> = [
    {
      name: 'CPU',
      models: [
        // Populated dynamically from /available-models (kraken, trocr, qwen_lora trained models)
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
      ]
    },
  ];

  // Available Ollama models from server (for Settings page)
  public availableOllamaModels: string[] = [];
  // Track which models are locally available
  public modelAvailability: { [key: string]: boolean } = {
    'nemotron_local': true,
    'qwen3_vl_235b_cloud': true,
    'qwen3_vl_235b_thinking': true,
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
  @ViewChildren('datasetRenameInput') datasetRenameInputs!: QueryList<ElementRef>;
  public lines: Letter[];

  // Get dynamic canvas dimensions based on viewport
  getCanvasDimensions(): { width: number; height: number } {
    // Use almost all available height - just subtract navbar (~70px) and small margin
    const availableHeight = window.innerHeight - 100;

    // Canvas is always inside the split panel (leftPanelWidth% of container).
    // Subtract toolbar (~50px) and padding.
    const panelFraction = this.leftPanelWidth / 100;
    const availableWidth = window.innerWidth * panelFraction - 60;

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

    this.curedService.getTransliterations(imageData, this.getEffectiveModel(), this.selectedOcrPrompt, this.apiKey || undefined, teiOptions, this.correctionRules || undefined, this.boxMode || undefined).subscribe(data => {
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
        this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.addMode, this.canvas.guideMode];
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
    private datasetService: DatasetService,
    private sanitizer: DomSanitizer,
    private location: Location,
    private http: HttpClient,
    private productionService: ProductionService,
    public guideLineService: GuideLineService) {
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
      'Ctrl+S           Save\n' +
      'Ctrl+Shift+S     Save As (open dialog)\n' +
      'Ctrl+N           New text (restart)\n' +
      'Alt+Z            Pan mode\n' +
      'Alt+A            Add box mode\n' +
      'Alt+D            Delete mode\n' +
      'Ctrl+Shift+C     Crop image to selection box\n' +
      'Delete           Delete selected box\n' +
      'Double-click+hold Draw new box (in Pan mode)\n' +
      'Ctrl+H           Find & Replace (in text editor)\n' +
      'Enter            Replace + Find Next (in replace field)\n' +
      'Shift+Enter      Replace + Find Prev (in replace field)\n' +
      'Alt+Enter        Replace All (in replace field)',
      'background: #333; color: #fff; padding: 4px 8px; font-weight: bold;',
      'color: #333; font-family: monospace;'
    );

    // Load labels for save dialog
    this.textService.getLabels().subscribe(labels => {
      this.existingLabels = labels;
    });

    // Load flat dataset list
    this.loadDatasets();

    // Load training status and models
    this.loadTrainingStatus();
    this.loadCuratedStats();
    this.loadModels();
    this.loadBaseModelsMetadata();
    this.loadAvailableOcrModels();
    this.loadAvailableOllamaModels();

    // Guide line color presets
    this.guideColorPresets = this.guideLineService.COLOR_PRESETS;

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

      // Clear previous state when navigating between texts
      if (this.canvas) {
        this.canvas.removeAllRects();
        this.boundingBoxes = [];
      }
      this.uploadedImageBlob = null;
      this.currentMuseumName = '';
      this.currentMuseumNumber = 0;
      this.currentPNumber = '';
      this.currentPublicationNumber = '';
      this.currentLabel = '';
      this.currentPart = '';
      this.isCurated = false;
      this.hasUnsavedChanges = false;
      this.ocrCropArea = null;

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
      this.loadDatasets();
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
    this.textListNavActive = false;
    this.textId = null;
    this.transliterationId = null;
    this.takeTextId = null;
    this.takeTransId = null;
    this.isLoadedFromServer = false;
    this.isCurated = false;
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
    if (this.queryParamsSub) {
      this.queryParamsSub.unsubscribe();
    }
    if (this.popStateSub) {
      this.popStateSub.unsubscribe();
    }
    this.stopTrainingProgressPolling();
  }

  updateToolbarButtons() {
    if (this.stage >= 1 && this.stage <= 5) {
      this.toolbarService.setToolbar({
        buttons: [],
        message: undefined,
        backAction: undefined
      });
    } else {
      this.toolbarService.clearButtons();
    }
  }

  save() {
    // First save: need metadata from dialog
    if (!this.textId) {
      this.openSaveDialog();
      return;
    }
    // Subsequent saves: use stored label/part
    this.isSaving = true;
    this.doSaveWithLabelAndPart(false, this.currentLabel, this.currentPart);
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
    const projectId = this.selectedDataset?.dataset_id || null;
    this.textService.create(identifiers, [], projectId).subscribe(textId => {
      this.textId = textId;
      this.doSaveWithLabelAndPart(false, label, part);
    }, err => {
      this.notificationService.showError('Failed to create text');
      this.isSaving = false;
    });
  }

  private doSaveWithLabelAndPart(isFixed: boolean, label: string, part: string, curateTarget?: 'both') {
    if (this.uploadedImageBlob) {
      console.log('[Save] Uploading image:', this.uploadedImageBlob.name, 'size:', this.uploadedImageBlob.size, 'textId:', this.textId);
      this.curedService.saveImage(this.uploadedImageBlob, this.textId).subscribe(imageName => {
        console.log('[Save] Image uploaded, server returned name:', imageName);
        this.createSubmissionWithLabelAndPart(isFixed, imageName, label, part, curateTarget);
      }, err => {
        console.error('[Save] Image upload FAILED:', err);
        this.notificationService.showError('Failed to upload image');
        this.isSaving = false;
      });
    } else {
      console.log('[Save] No uploadedImageBlob — saving text only');
      this.createSubmissionWithLabelAndPart(isFixed, null, label, part, curateTarget);
    }
  }

  private doSave(isFixed: boolean, curateTarget?: 'both') {
    this.doSaveWithLabelAndPart(isFixed, this.currentLabel, this.currentPart, curateTarget);
  }

  createSubmissionWithLabelAndPart(isFixed: boolean, imageName: string = null, label: string = '', part: string = '',
                                   curateTarget?: 'both') {
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

    // Determine curation flags
    let isKraken = this.isCurated;
    let isVlm = this.isCurated;
    if (curateTarget === 'both') { isKraken = true; isVlm = true; }

    const guides = this.canvas ? this.canvas.getGuides() : [];
    console.log('[Save] guides:', guides.length, 'imageName:', imageName);
    this.curedService.createSubmission(this.textId, this.transliterationId, lines, dimensions, imageName, isKraken, isVlm, guides).subscribe(result => {
      if (this.hasPendingPages) {
        this.notificationService.showSuccess(
          `Saved (${this.currentPageIndex + 1}/${this.batchTotal}). Click "Next" for the next image.`
        );
      } else if (!this.selectedDataset) {
        this.notificationService.showInfo("Saved to Unassigned (no dataset selected)");
      } else {
        this.notificationService.showInfo("Successfully saved");
      }
      this.transliterationId = result;
      this.isCurated = isKraken || isVlm;
      this.isSaving = false;
      this.hasUnsavedChanges = false;
      this.uploadedImageBlob = null;  // Clear so it doesn't re-upload on next save

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

  /** Check if the data shape allows curation (boxes === lines). */
  get canCurate(): boolean {
    const lineCount = this.lines?.length || 0;
    const boxCount = this.boundingBoxes?.length || 0;
    return lineCount > 0 && boxCount === lineCount;
  }

  /** Whether curation has been done. */
  get isTextFixed(): boolean {
    return this.isCurated;
  }

  /** Clear all bounding boxes from the canvas. */
  clearAllBoxes() {
    for (const box of this.boundingBoxes) {
      this.canvas.getCanvas().remove(box);
    }
    this.boundingBoxes = [];
    this.canvas.getCanvas().renderAll();
    this.hasUnsavedChanges = true;
    this.notificationService.showInfo('All boxes removed');
    this.updateToolbarButtons();
  }

  curate() {
    if (this.textId == null) {
      this.notificationService.showError('Please save first before curating');
      return;
    }
    if (!this.canCurate) {
      this.notificationService.showError(`Cannot curate: need ${this.lines?.length || 0} boxes but have ${this.boundingBoxes?.length || 0}`);
      return;
    }
    this.notificationService.showInfo('Curating for training');
    this.doSave(true, 'both');
  }

  deleteCurrentEntry() {
    if (!confirm('Delete this text entry and all its transliterations? This cannot be undone.')) {
      return;
    }
    this.curedService.deleteText(this.textId).subscribe(
      () => {
        this.notificationService.showSuccess('Text entry deleted');
        this.curedTexts = this.curedTexts.filter(t => t.text_id !== this.textId);
        this.stage = 0;
        this.refreshCurrentDataset();
      },
      () => {
        this.notificationService.showError('Failed to delete text entry');
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
      this.isCurated = data.is_curated_kraken || data.is_curated_vlm || false;
      // Load guide lines
      console.log('[Load] guides from server:', data.guides);
      if (data.guides && data.guides.length && this.canvas) {
        this.canvas.loadGuides(data.guides);
        this.currentGuides = data.guides;
      }
      if (this.highlightQuery) {
        this.setHighlightByQuery(this.highlightQuery);
      }
      // Load text metadata to enable translation lookup
      this.loadTextMetadata();
      // Loading from server is not a user change — reset dirty flag
      this.hasUnsavedChanges = false;
      this.updateToolbarButtons();
    }, err => {
      console.error('Failed to load transliteration:', err);
      this.notificationService.showError('Failed to load transliteration data');
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
      width: '1000px', height: '720px'
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
    this.isCurated = false;
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
          this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.guideMode];
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

  onImageRotated(rotatedDataUrl: string): void {
    this.uploadedImageBlob = this.dataUrlToFile(rotatedDataUrl, 'rotated-image.png');
    this.hasUnsavedChanges = true;
    this.notificationService.showInfo('Image rotated — save to persist');
  }

  cropToSelectedBox() {
    const bgImage = this.canvas?.getCanvas().backgroundImage as unknown as FabricImage;
    if (!bgImage) {
      this.notificationService.showError('No image loaded');
      return;
    }

    // Use selectedBox (stage 2), the active canvas object, selectedRect, or first bounding box
    const box = this.selectedBox
      || this.canvas.getCanvas().getActiveObject() as any
      || this.canvas.selectedRect
      || (this.boundingBoxes.length === 1 ? this.boundingBoxes[0] : null);
    if (!box || box.left == null) {
      this.notificationService.showError('Select a box first, or draw one');
      return;
    }

    const croppedDataUrl = bgImage.toDataURL({
      left: box.left,
      top: box.top,
      width: box.getScaledWidth(),
      height: box.getScaledHeight()
    });

    // Update blob for saving
    this.uploadedImageBlob = this.dataUrlToFile(croppedDataUrl, 'manual-crop.png');

    // Remove the box from canvas
    this.canvas.getCanvas().remove(box);
    if (this.selectedBox === box) {
      this.selectedBox = null;
    }
    // Remove from boundingBoxes array if it was a bounding box (stage 5)
    this.boundingBoxes = this.boundingBoxes.filter(b => b !== box);
    this.ocrCropArea = null;  // Image IS the crop now — no offset needed

    // Clear all remaining bounding boxes (they won't match the cropped image)
    for (const b of this.boundingBoxes) {
      this.canvas.getCanvas().remove(b);
    }
    this.boundingBoxes = [];

    // Replace canvas background with cropped image
    this.setCanvasImage(croppedDataUrl);

    this.hasUnsavedChanges = true;
    this.notificationService.showSuccess('Image cropped to selection');
    this.updateToolbarButtons();
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
              this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.guideMode];
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
      this.hasUnsavedChanges = true;
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
    this.hasUnsavedChanges = true;
    this.updateToolbarButtons();
  }

  updateTransliterationIndexes() {
    this.lines.forEach((line, row) => {
      line.index = new Index(row, 0);
    });
    this.updateToolbarButtons();
  }

  @HostListener('window:beforeunload', ['$event'])
  onBeforeUnload(event: BeforeUnloadEvent) {
    if (this.hasUnsavedChanges) {
      event.preventDefault();
      event.returnValue = '';
    }
  }

  @HostListener('document:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent) {
    if (event.ctrlKey && !event.shiftKey && event.key === 's') {
      event.preventDefault();
      if (this.stage === 5 && !this.viewOnly) {
        this.save();
      }
    }
    if (event.ctrlKey && event.shiftKey && event.key === 'S') {
      event.preventDefault();
      if (this.stage === 5 && !this.viewOnly) {
        this.openSaveDialog();
      }
    }
    if (event.ctrlKey && event.shiftKey && event.key === 'C') {
      event.preventDefault();
      this.cropToSelectedBox();
    }
    if (event.ctrlKey && event.shiftKey && event.key === 'X') {
      event.preventDefault();
      if (this.stage === 5 && !this.viewOnly && this.textId != null) {
        if (this.isCurated) {
          this.curedService.batchCurate([this.textId], false).subscribe(
            () => {
              this.isCurated = false;
              this.notificationService.showSuccess('Curation removed');
              this.loadCuratedStats();
            },
            () => this.notificationService.showError('Failed to toggle curation')
          );
        } else {
          this.curate();
        }
      }
    }
    if (event.ctrlKey && event.key === 'a' && this.stage === 0 && this.selectedDataset) {
      event.preventDefault();
      this.selectAllTexts();
    }
    if (event.key === 'Delete' && this.stage === 0 && this.selectedTexts.size > 0) {
      this.deleteSelectedTexts();
    }
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
    this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.addMode, this.canvas.guideMode];
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
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.guideMode];
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
      if (this.hasUnsavedChanges) {
        if (!confirm('You have unsaved changes. Discard them?')) {
          return;
        }
        this.hasUnsavedChanges = false;
      }
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
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.guideMode];
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
      this.hasUnsavedChanges = true;
      this.updateToolbarButtons();
    }
  }

  downloadCurrentText(format: string) {
    const label = this.currentLabel || 'unlabeled';
    const fnameBase = this.currentLabel ? `${this.currentLabel}_${this.textId || 'new'}` : `CuReD-${this.textId || 'new'}`;
    const editorContent = this.lines.map(l => l.letter).join('\n');

    if (format === 'txt') {
      const header = `=== ${label} | text_id=${this.textId || 'unsaved'} ===\n`;
      const blob = new Blob([header + editorContent], { type: 'text/plain;charset=utf-8' });
      saveAs(blob, `${fnameBase}.txt`);
      return;
    }

    if (format === 'atf') {
      const atfContent = this.convertToAtf(editorContent, label, this.textId || 0);
      saveAs(new Blob([atfContent], { type: 'text/plain;charset=utf-8' }), `${fnameBase}.atf`);
      return;
    }

    // JSON and CSV: use backend if text is saved, otherwise build locally
    if (this.textId != null) {
      const ext = format === 'csv' ? 'csv' : 'json';
      this.datasetService.exportSingleText(this.textId, format).subscribe(
        blob => { saveAs(blob, `${fnameBase}.${ext}`); },
        () => { this.notificationService.showError('Download failed'); }
      );
    } else {
      // Text not yet saved — build locally
      if (format === 'json') {
        const data = { label: this.currentLabel, content: editorContent, text_id: null, part: this.currentPart || '' };
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
        saveAs(blob, `${fnameBase}.json`);
      } else if (format === 'csv') {
        const csvContent = `label,content,text_id,part\n"${(this.currentLabel || '').replace(/"/g, '""')}","${editorContent.replace(/"/g, '""')}","","${(this.currentPart || '').replace(/"/g, '""')}"`;
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
        saveAs(blob, `${fnameBase}.csv`);
      }
    }
  }

  private convertToAtf(content: string, label: string, textId: number): string {
    let atf = `&P${textId} = ${label}\n#project: ebl\n#atf: lang akk\n#atf: use unicode\n@tablet\n@obverse\n`;
    const lines = (content || '').split('\n');
    lines.forEach((line, i) => {
      let text = this.atfConverter.toAtf(line);
      text = this.atfConverter.cleanForExport(text);
      if (text.trim()) {
        if (!/^\d+\.?\s+/.test(text) && !/^\d+\.'\s*/.test(text) && !/^\d+'\.?\s*/.test(text)) {
          atf += `${i + 1}. ${text}\n`;
        } else {
          atf += `${text}\n`;
        }
      }
    });
    return atf;
  }

  exportDataset(format: string) {
    if (!this.selectedDataset || this.selectedDataset.dataset_id === -1) return;
    const datasetName = this.selectedDataset.name.replace(/\s+/g, '_');

    // ATF: fetch JSON data, convert client-side
    if (format === 'atf') {
      this.datasetService.exportDataset(this.selectedDataset.dataset_id, 'json').subscribe(
        blob => {
          blob.text().then(raw => {
            const texts: any[] = JSON.parse(raw);
            let content = '';
            texts.forEach(t => {
              content += this.convertToAtf(t.content, t.label || 'unlabeled', t.text_id) + '\n';
            });
            saveAs(new Blob([content], { type: 'text/plain;charset=utf-8' }), `${datasetName}.atf`);
          });
        },
        () => { this.notificationService.showError('Export failed'); }
      );
      return;
    }

    const ext = format.startsWith('zip_') ? 'zip' : format;
    const filename = `${datasetName}.${ext}`;
    this.datasetService.exportDataset(this.selectedDataset.dataset_id, format).subscribe(
      blob => { saveAs(blob, filename); },
      () => { this.notificationService.showError('Export failed'); }
    );
  }

  downloadSingleText(item: TextPreview, event: Event, format: string = 'txt') {
    event.stopPropagation();
    const label = (item.labels && item.labels.length > 0) ? item.labels[0] : (item.label || '');
    const fnameBase = label ? `${label}_${item.text_id}` : `${item.text_id}`;

    if (format === 'atf') {
      // ATF conversion is client-side — fetch raw JSON, convert, save
      this.datasetService.exportSingleText(item.text_id, 'json').subscribe(
        blob => {
          blob.text().then(raw => {
            const data = JSON.parse(raw);
            const atfContent = this.convertToAtf(data.content, label || 'unlabeled', item.text_id);
            saveAs(new Blob([atfContent], { type: 'text/plain;charset=utf-8' }), `${fnameBase}.atf`);
          });
        },
        () => { this.notificationService.showError('Download failed'); }
      );
      return;
    }

    const ext = format === 'csv' ? 'csv' : format;
    this.datasetService.exportSingleText(item.text_id, format).subscribe(
      blob => { saveAs(blob, `${fnameBase}.${ext}`); },
      () => { this.notificationService.showError('Download failed'); }
    );
  }

  // ─── CuReD Dataset Export / Import ─────────────────────────────

  exportDatasetCured(): void {
    if (!this.selectedDataset || this.selectedDataset.dataset_id === -1) return;
    this.curedService.exportDatasetCured(this.selectedDataset.dataset_id);
  }

  exportDatasetCuredFromMenu(): void {
    if (!this.datasetContextMenuNode) return;
    this.datasetContextMenuVisible = false;
    this.curedService.exportDatasetCured(this.datasetContextMenuNode.dataset_id);
  }

  exportSingleTextCured(item: TextPreview, event: Event): void {
    event.stopPropagation();
    this.curedService.exportTextCured(item.text_id);
  }

  handleImportZip(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files?.length) return;
    const file = input.files[0];
    input.value = '';  // reset so same file can be re-uploaded

    const projectId = this.selectedDataset?.dataset_id !== -1
      ? this.selectedDataset?.dataset_id
      : undefined;

    this.curedService.importCuredZip(file, projectId).subscribe({
      next: (result) => {
        if (result.errors?.length) {
          this.notificationService.showError(
            `Import partially failed: ${result.imported} imported, ${result.errors.length} errors`
          );
        } else {
          this.notificationService.showSuccess(
            `Imported ${result.imported} text${result.imported === 1 ? '' : 's'}`
          );
        }
        // Reload text list
        if (this.selectedDataset) {
          this.openDataset(this.selectedDataset);
        }
      },
      error: () => {
        this.notificationService.showError('Import failed');
      }
    });
  }

  handleImportFolder(event: any): void {
    const files = event.target?.files;
    if (!files || files.length === 0) return;

    // Extract folder path from Electron's File.path property
    let folderPath = '';
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if ((file as any).path) {
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

    const projectId = this.selectedDataset?.dataset_id !== -1
      ? this.selectedDataset?.dataset_id
      : undefined;

    this.curedService.importCuredFolder(folderPath, projectId).subscribe({
      next: (result) => {
        if (result.errors?.length) {
          this.notificationService.showError(
            `Import partially failed: ${result.imported} imported, ${result.errors.length} errors`
          );
        } else {
          this.notificationService.showSuccess(
            `Imported ${result.imported} text${result.imported === 1 ? '' : 's'} from folder`
          );
        }
        if (this.selectedDataset) {
          this.openDataset(this.selectedDataset);
        }
      },
      error: () => {
        this.notificationService.showError('Folder import failed');
      }
    });
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

  loadDatasets() {
    this.datasetService.list().subscribe(data => {
      this.datasets = data;
    });
  }

  openDataset(dataset: DatasetPreview) {
    this.selectedDataset = dataset;
    this.showDatasetList = false;
    this.clearTextSelection();
    this.loadCuratedStats();
    this.textsPage = 0;
    this.datasetService.getTexts(dataset.dataset_id, 0, 0).subscribe(data => {
      this.curedTexts = data.items;
      this.textsTotal = data.total;
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

  get textsTotalPages(): number {
    return Math.ceil(this.filteredTexts.length / this.textsPageSize);
  }

  goToTextsPage(page: number): void {
    if (page < 0 || page >= this.textsTotalPages) return;
    this.textsPage = page;
    this.clearTextSelection();
  }

  backToDatasets() {
    this.textListNavActive = false;
    this.selectedDataset = null;
    this.showDatasetList = true;
    this.curedTexts = [];
    this.clearTextSelection();
    this.loadDatasets();
    this.loadCuratedStats();
  }

  createDataset() {
    const name = this.newDatasetName.trim();
    if (!name) return;
    this.datasetService.create(name).subscribe(() => {
      this.newDatasetName = '';
      this.loadDatasets();
    });
  }

  // ============== Project Card Selection & Inline Rename ==============

  selectDatasetCard(dataset: DatasetPreview): void {
    this.selectedDatasetCard = dataset;
  }

  onDatasetNameClick(dataset: DatasetPreview, event: MouseEvent): void {
    event.stopPropagation();
    // Only start rename if this card is already selected (slow double-click)
    if (this.selectedDatasetCard?.dataset_id === dataset.dataset_id) {
      clearTimeout(this.datasetRenameTimer);
      this.datasetRenameTimer = setTimeout(() => {
        this.startDatasetRename(dataset);
      }, 400);
    }
  }

  startDatasetRename(dataset: DatasetPreview): void {
    this.editingDataset = dataset;
    this.editingDatasetName = dataset.name;
    this.datasetRenameCancelled = false;
    setTimeout(() => {
      const inputs = this.datasetRenameInputs.toArray();
      if (inputs.length > 0) {
        const input = inputs[0].nativeElement as HTMLInputElement;
        input.focus();
        input.select();
      }
    });
  }

  confirmDatasetRename(): void {
    if (!this.editingDataset || this.datasetRenameCancelled) { return; }
    const dataset = this.editingDataset;
    const newName = this.editingDatasetName.trim();
    this.editingDataset = null;

    if (!newName || newName === dataset.name) { return; }

    this.datasetService.rename(dataset.dataset_id, newName).subscribe(
      () => {
        dataset.name = newName;
        this.notificationService.showSuccess(`Renamed to "${newName}"`);
      },
      () => this.notificationService.showError('Failed to rename dataset')
    );
  }

  cancelDatasetRename(): void {
    this.datasetRenameCancelled = true;
    this.editingDataset = null;
    this.editingDatasetName = '';
  }

  onDatasetRenameBlur(): void {
    setTimeout(() => {
      if (this.editingDataset && !this.datasetRenameCancelled) {
        this.confirmDatasetRename();
      }
    }, 100);
  }

  // ============== Project Context Menu ==============

  onDatasetContextMenu(dataset: DatasetPreview, event: MouseEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.datasetContextMenuNode = dataset;
    this.datasetContextMenuX = event.clientX;
    this.datasetContextMenuY = event.clientY;
    this.datasetContextMenuVisible = true;
  }

  startDatasetRenameFromMenu(): void {
    if (!this.datasetContextMenuNode) { return; }
    const dataset = this.datasetContextMenuNode;
    this.datasetContextMenuVisible = false;
    this.selectedDatasetCard = dataset;
    this.startDatasetRename(dataset);
  }

  deleteDatasetFromMenu(): void {
    if (!this.datasetContextMenuNode) { return; }
    const dataset = this.datasetContextMenuNode;
    this.datasetContextMenuVisible = false;
    this.deleteDataset(dataset);
  }

  @HostListener('document:click')
  onDocumentClick(): void {
    this.datasetContextMenuVisible = false;
    this.textContextMenuVisible = false;
  }

  // ============== Text Selection & Batch Curate ==============

  toggleTextSelection(item: TextPreview, event: MouseEvent): void {
    const index = this.filteredTexts.indexOf(item);
    const id = item.text_id;

    if (event.shiftKey && this.lastSelectedTextIndex >= 0) {
      const start = Math.min(this.lastSelectedTextIndex, index);
      const end = Math.max(this.lastSelectedTextIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedTexts.add(this.filteredTexts[i].text_id);
      }
    } else if (event.ctrlKey || event.metaKey) {
      if (this.selectedTexts.has(id)) {
        this.selectedTexts.delete(id);
      } else {
        this.selectedTexts.add(id);
      }
    } else {
      this.selectedTexts.clear();
      this.selectedTexts.add(id);
    }
    this.lastSelectedTextIndex = index;
  }

  isTextSelected(item: TextPreview): boolean {
    return this.selectedTexts.has(item.text_id);
  }

  selectAllTexts(): void {
    if (this.selectedTexts.size === this.filteredTexts.length) {
      this.selectedTexts.clear();
    } else {
      this.filteredTexts.forEach(t => this.selectedTexts.add(t.text_id));
    }
  }

  clearTextSelection(): void {
    this.selectedTexts.clear();
    this.lastSelectedTextIndex = -1;
  }

  deleteSelectedTexts(): void {
    if (this.selectedTexts.size === 0) { return; }
    const count = this.selectedTexts.size;
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: 'Delete Texts',
        message: `Delete ${count} selected text(s) and their transliterations?`,
        confirmText: 'Delete',
        warn: true
      }
    });

    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed) { return; }
      const textIds = Array.from(this.selectedTexts);

      this.curedService.batchDeleteTexts(textIds).subscribe({
        next: (result) => {
          this.curedTexts = this.curedTexts.filter(t => !this.selectedTexts.has(t.text_id));
          this.notificationService.showSuccess(`Deleted ${result.deleted} text(s)`);
          this.clearTextSelection();
          this.refreshCurrentDataset();
        },
        error: () => {
          this.notificationService.showError('Failed to delete texts');
          this.clearTextSelection();
          this.refreshCurrentDataset();
        }
      });
    });
  }

  allSelectedAreCurated(): boolean {
    if (this.selectedTexts.size === 0) return false;
    return this.curedTexts
      .filter(t => this.selectedTexts.has(t.text_id))
      .every(t => t.is_curated);
  }

  batchCurateFromHeader(): void {
    if (this.selectedTexts.size === 0) return;
    // If all selected are already curated, uncurate; otherwise curate
    const curate = !this.allSelectedAreCurated();
    this.batchCurate(curate);
  }

  batchCurate(curate: boolean): void {
    if (this.selectedTexts.size === 0) return;
    this.isBatchCurating = true;
    const textIds = Array.from(this.selectedTexts);

    this.curedService.batchCurate(textIds, curate).subscribe({
      next: (result) => {
        this.isBatchCurating = false;
        const msg = curate
          ? `Curated ${result.updated} text(s)`
          : `Uncurated ${result.updated} text(s)`;
        this.notificationService.showSuccess(msg);
        if (result.skipped > 0) {
          this.notificationService.showWarning(`Skipped ${result.skipped} text(s) without transliterations`);
        }
        this.refreshCurrentDataset();
        this.loadCuratedStats();
        this.clearTextSelection();
      },
      error: () => {
        this.isBatchCurating = false;
        this.notificationService.showError('Batch curate failed');
      }
    });
  }

  toggleSingleTextCuration(item: TextPreview, event: Event): void {
    event.stopPropagation();
    const newState = !(item.is_curated_kraken || item.is_curated_vlm);
    this.curedService.batchCurate([item.text_id], newState).subscribe({
      next: (result) => {
        if (result.updated > 0) {
          item.is_curated_kraken = newState;
          item.is_curated_vlm = newState;
          this.loadCuratedStats();
        }
      },
      error: () => this.notificationService.showError('Failed to toggle curation')
    });
  }


  // ============== Text Context Menu (Grid View) ==============

  onTextContextMenu(item: TextPreview, event: MouseEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.textContextMenuItem = item;
    this.textContextMenuX = event.clientX;
    this.textContextMenuY = event.clientY;
    this.textContextMenuVisible = true;
  }

  curateFromContextMenu(): void {
    if (!this.textContextMenuItem) return;
    const item = this.textContextMenuItem;
    this.textContextMenuVisible = false;
    this.curedService.batchCurate([item.text_id], true).subscribe({
      next: (result) => {
        if (result.updated > 0) {
          item.is_curated_kraken = true;
          item.is_curated_vlm = true;
          this.notificationService.showSuccess('Marked as curated');
          this.loadCuratedStats();
        }
      },
      error: () => this.notificationService.showError('Failed to curate')
    });
  }

  uncurateFromContextMenu(): void {
    if (!this.textContextMenuItem) return;
    const item = this.textContextMenuItem;
    this.textContextMenuVisible = false;
    this.curedService.batchCurate([item.text_id], false).subscribe({
      next: (result) => {
        if (result.updated > 0) {
          item.is_curated_kraken = false;
          item.is_curated_vlm = false;
          this.notificationService.showSuccess('Removed curation');
          this.loadCuratedStats();
        }
      },
      error: () => this.notificationService.showError('Failed to uncurate')
    });
  }

  onTextListBackgroundClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    if (target.closest('.details-row') || target.closest('.text-grid-card')) {
      return;
    }
    this.clearTextSelection();
  }

  private refreshCurrentDataset(): void {
    if (!this.selectedDataset) return;
    if (this.selectedDataset.dataset_id === -1) {
      this.loadUnassignedTexts();
    } else {
      this.datasetService.getTexts(this.selectedDataset.dataset_id, 0, 0).subscribe(data => {
        this.curedTexts = data.items;
        this.textsTotal = data.total;
        this.collectExistingParts();
        this.loadTransliterationIds();
      });
    }
  }

  deleteDataset(dataset: DatasetPreview) {
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: { message: `Delete dataset "${dataset.name}"? Texts will become unassigned.` }
    });
    dialogRef.afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.datasetService.delete(dataset.dataset_id).subscribe(
          () => {
            if (this.selectedDataset?.dataset_id === dataset.dataset_id) {
              this.backToDatasets();
            } else {
              this.loadDatasets();
            }
          },
          (err) => {
            this.notificationService.showError(err.error?.detail || 'Delete failed');
          }
        );
      }
    });
  }

  loadUnassignedTexts() {
    this.selectedDataset = { dataset_id: -1, name: 'Unassigned' } as any;
    this.showDatasetList = false;
    this.datasetService.getUnassignedTexts().subscribe(data => {
      this.curedTexts = data;
      this.collectExistingParts();
      this.loadTransliterationIds();
    });
  }

  private _thumbnailGeneration = 0; // incremented on project change to cancel stale loads

  private loadTransliterationIds() {
    // latest_transliteration_id is already provided by the text list API,
    // so we just load thumbnails directly — no extra per-text requests needed.
    // Batch with concurrency limit to avoid overwhelming the server.
    this._thumbnailGeneration++;
    const gen = this._thumbnailGeneration;
    const items = this.curedTexts.filter(i => i.latest_transliteration_id && !i._thumbnailUrl);
    const BATCH = 6;
    let idx = 0;

    const loadNext = () => {
      if (gen !== this._thumbnailGeneration) return; // project changed, stop
      if (idx >= items.length) return;
      const item = items[idx++];
      this.curedService.getImage(item.text_id, item.latest_transliteration_id!).subscribe(
        blob => {
          if (gen !== this._thumbnailGeneration) return;
          const url = URL.createObjectURL(blob);
          item._thumbnailUrl = this.sanitizer.bypassSecurityTrustUrl(url);
          loadNext();
        },
        () => { loadNext(); }
      );
    };

    // Start BATCH parallel chains
    for (let i = 0; i < Math.min(BATCH, items.length); i++) {
      loadNext();
    }
  }

  get filteredDatasets(): DatasetPreview[] {
    if (!this.datasetSearchQuery.trim()) {
      return this.datasets;
    }
    const q = this.datasetSearchQuery.trim().toLowerCase();
    return this.datasets.filter(p => p.name.toLowerCase().includes(q));
  }

  clearDatasetSearch(): void {
    this.datasetSearchQuery = '';
  }

  /** All texts matching the current search/sort — global, not paginated */
  get filteredTexts(): TextPreview[] {
    let items = [...this.curedTexts];

    // Text search filter (global across all texts)
    if (this.searchQuery.trim()) {
      const q = this.searchQuery.trim().toLowerCase();
      items = items.filter(t => {
        const identifier = this.getItemIdentifier(t).toLowerCase();
        const label = (t.label || '').toLowerCase();
        const labels = (t.labels || []).join(' ').toLowerCase();
        return identifier.includes(q) || label.includes(q) || labels.includes(q)
          || String(t.text_id).includes(q);
      });
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

        // Handle label column — prefer labels array over legacy label field
        if (this.sortColumn === 'label') {
          valA = (a.labels?.length ? a.labels[0] : a.label) || '';
          valB = (b.labels?.length ? b.labels[0] : b.label) || '';
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

  /** Paginated slice of filteredTexts for display only */
  get displayedTexts(): TextPreview[] {
    const start = this.textsPage * this.textsPageSize;
    return this.filteredTexts.slice(start, start + this.textsPageSize);
  }

  formatFileSize(bytes: number): string {
    if (!bytes) return '—';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  toggleSort(column: string): void {
    if (this.sortColumn === column) {
      this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortColumn = column;
      this.sortDirection = column === 'last_modified' ? 'desc' : 'asc';
    }
  }

  clearSearch(): void {
    this.searchQuery = '';
    this.textsPage = 0;
  }

  searchKwic(): void {
    const query = this.searchQuery.trim();
    if (query.length < 2) {
      this.clearKwicSearch();
      return;
    }

    this.isSearchingKwic = true;
    this.kwicSearchQuery = query;

    this.productionService.searchKwic(query).subscribe({
      next: (results) => {
        this.kwicResults = results;
        this.kwicSearchActive = true;
        this.isSearchingKwic = false;
      },
      error: (err) => {
        console.error('KWIC search failed:', err);
        this.notificationService.showError('Search failed');
        this.isSearchingKwic = false;
      }
    });
  }

  clearKwicSearch(): void {
    this.kwicSearchActive = false;
    this.kwicResults = [];
    this.kwicSearchQuery = '';
  }

  openKwicResult(result: KwicResult): void {
    this.router.navigate(['/cured'], {
      queryParams: { identifier: result.identifier, type: result.identifier_type }
    });
  }

  highlightKwicMatch(line: string): string {
    if (!this.kwicSearchQuery) return line;
    const safe = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const escaped = this.kwicSearchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escaped})`, 'gi');
    return safe.replace(regex, '<mark>$1</mark>');
  }

  openListItem(item: TextPreview) {
    this.textListNavActive = true;
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

  navigateToPrevText(): void {
    if (this.hasUnsavedChanges && !confirm('You have unsaved changes. Discard them?')) return;
    this.hasUnsavedChanges = false;
    const idx = this.currentTextListIndex;
    if (idx > 0) {
      this.openListItem(this.filteredTexts[idx - 1]);
    }
  }

  navigateToNextText(): void {
    if (this.hasUnsavedChanges && !confirm('You have unsaved changes. Discard them?')) return;
    this.hasUnsavedChanges = false;
    const idx = this.currentTextListIndex;
    if (idx >= 0 && idx < this.filteredTexts.length - 1) {
      this.openListItem(this.filteredTexts[idx + 1]);
    }
  }

  navigateToTextByIndex(textId: number): void {
    if (textId === this.textId) return;
    if (this.hasUnsavedChanges && !confirm('You have unsaved changes. Discard them?')) return;
    this.hasUnsavedChanges = false;
    const item = this.filteredTexts.find(t => t.text_id === textId);
    if (item) {
      this.openListItem(item);
    }
  }

  getTextNavLabel(item: TextPreview): string {
    const ids = this.getItemIdentifiers(item);
    let idStr = ids[0] !== '-' ? ids.join(' ') : '';
    // Strip directory paths and file extensions
    if (idStr.includes('/')) idStr = idStr.split('/').pop() || idStr;
    if (idStr.includes('\\')) idStr = idStr.split('\\').pop() || idStr;
    idStr = idStr.replace(/\.(png|jpg|jpeg|pdf|tif|tiff)$/i, '');
    const parts: string[] = [];
    if (idStr) parts.push(idStr);
    if (item.part) parts.push(item.part);
    return parts.length > 0 ? parts.join(' | ') : `Text ${item.text_id}`;
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
    return this.labelColorCache.get(label)!;
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

  openPartDialog(item: TextPreview, event: Event) {
    event.stopPropagation();

    const dialogRef = this.dialog.open(PartDialogComponent, {
      data: { currentPart: item.part || '' }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result === null || result === undefined) { return; }
      const r = result as PartDialogResult;

      this.textService.updatePart(item.text_id, r.part).subscribe(
        () => {
          item.part = r.part;
          this.notificationService.showSuccess(r.part ? `Part: ${r.part}` : 'Part removed');
        },
        () => { this.notificationService.showError('Failed to update part'); }
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

  moveListItem(item: TextPreview, event: Event) {
    event.stopPropagation();
    const currentProjectId = this.selectedDataset?.dataset_id === -1 ? null : this.selectedDataset?.dataset_id ?? null;
    const dialogRef = this.dialog.open(MoveTextDialogComponent, {
      data: {
        datasets: this.datasets,
        currentDatasetId: currentProjectId,
        selectedCount: this.selectedTexts.size
      } as MoveTextDialogData
    });

    dialogRef.afterClosed().subscribe((result: MoveTextDialogResult | undefined) => {
      if (!result) return;
      const targetName = result.datasetId
        ? this.datasets.find(p => p.dataset_id === result.datasetId)?.name || 'dataset'
        : 'Unassigned';

      const textsToMove: TextPreview[] = result.moveAll && this.selectedTexts.size > 1
        ? this.curedTexts.filter(t => this.selectedTexts.has(t.text_id))
        : [item];

      let completed = 0;
      let failed = 0;
      for (const t of textsToMove) {
        this.datasetService.assignText(t.text_id, result.datasetId).subscribe(
          () => {
            this.curedTexts = this.curedTexts.filter(ct => ct !== t);
            this.selectedTexts.delete(t.text_id);
            completed++;
            if (completed + failed === textsToMove.length) {
              const msg = textsToMove.length === 1
                ? `Moved to ${targetName}`
                : `Moved ${completed} entries to ${targetName}` + (failed ? ` (${failed} failed)` : '');
              this.notificationService.showSuccess(msg);
            }
          },
          () => {
            failed++;
            if (completed + failed === textsToMove.length) {
              this.notificationService.showError(`Moved ${completed}, failed ${failed}`);
            }
          }
        );
      }
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
    const projectId = this.selectedDataset?.dataset_id;
    this.curedService.getCuratedStats(projectId).subscribe(
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

        // Add trained models (kraken, qwen_lora, trocr) into the CPU category
        const cpuCategory = this.ocrModelCategories.find(c => c.name === 'CPU');
        if (cpuCategory) {
          const existingValues = new Set(cpuCategory.models.map(m => m.value));
          const trainedPrefixes = ['kraken:', 'qwen_lora:', 'trocr:'];
          for (const model of response.models) {
            if (trainedPrefixes.some(p => model.value.startsWith(p)) && !existingValues.has(model.value)) {
              cpuCategory.models.push({
                value: model.value,
                label: model.label.replace(' (Kraken)', '').replace(/ \(Qwen QLoRA.*\)/, '').replace(/ \(TrOCR.*\)/, ''),
                description: model.value.startsWith('kraken:') ? 'Trained Kraken model' :
                             model.value.startsWith('qwen_lora:') ? 'Qwen QLoRA fine-tuned' :
                             'TrOCR fine-tuned',
                trained: true,
              });
              this.modelAvailability[model.value] = true;
            }
          }
        }
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

  getDatasetsWithCuratedData(): DatasetPreview[] {
    return this.datasets.filter(p => p.curated_count > 0);
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
    this.curedService.getRecommendedModels().subscribe(
      response => {
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
      () => {
        // Ollama not available
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

        // If text list nav not active (e.g. page reload), load the dataset's text list
        if (!this.textListNavActive && text?.dataset_id) {
          this.datasetService.getTexts(text.dataset_id, 0, 0).subscribe(data => {
            this.curedTexts = data.items;
            this.textsTotal = data.total;
            this.collectExistingParts();
            this.loadTransliterationIds();
            this.textListNavActive = true;
          });
        }
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

  // ── Guide lines toolbar helpers ──

  onGuideColorInput(event: Event): void {
    const hex = (event.target as HTMLInputElement).value;
    this.guideHexColor = hex;
    // Convert hex to rgba with moderate opacity for reading
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const rgba = `rgba(${r}, ${g}, ${b}, 0.6)`;
    this.canvas?.setSelectedGuideColor(rgba);
  }

  setGuideColor(color: string): void {
    this.canvas?.setSelectedGuideColor(color);
    // Update hex picker to match (approximate)
    this.guideHexColor = this.rgbaToHex(color);
  }

  activateGuideMode(): void {
    if (this.canvas && this.canvas.allowedActions?.some(a => a.name === CanvasMode.Guide)) {
      this.canvas.changeMode(CanvasMode.Guide);
    }
  }

  onGuideStrokeChange(event: Event): void {
    const val = +(event.target as HTMLInputElement).value;
    this.canvas?.setGuideStrokeWidth(val);
  }

  onGuideOpacityChange(event: Event): void {
    this.guideOpacity = +(event.target as HTMLInputElement).value;
    this.canvas?.setGuideOpacity(this.guideOpacity / 100);
  }

  onGuidesChanged(guides: GuideLineData[]): void {
    this.currentGuides = guides;
    this.hasUnsavedChanges = true;
  }

  private rgbaToHex(rgba: string): string {
    const match = rgba.match(/\d+/g);
    if (!match || match.length < 3) return '#ffa500';
    const r = parseInt(match[0]).toString(16).padStart(2, '0');
    const g = parseInt(match[1]).toString(16).padStart(2, '0');
    const b = parseInt(match[2]).toString(16).padStart(2, '0');
    return `#${r}${g}${b}`;
  }

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
        this.hasUnsavedChanges = true;
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
