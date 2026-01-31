import { AfterViewInit, Component, HostListener, OnInit, OnDestroy, ViewChild } from '@angular/core';
import { MatMenuTrigger } from '@angular/material/menu';
import { Image as FabricImage, Rect } from 'fabric/fabric-impl';
import { PDFDocumentProxy } from 'ng2-pdf-viewer';
import { Dimensions, Index, Letter, LetterHover, RectData } from 'src/app/models/letter';
import { CuredService } from 'src/app/services/cured.service';
import { NotificationService } from 'src/app/services/notification.service';
import { CanvasMode, CanvasType, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';
import { saveAs } from 'file-saver';
import { TextEditorComponent } from './text-editor/text-editor.component';
import { MatDialog } from '@angular/material/dialog';
import { TextCreatorComponent } from '../common/text-creator/text-creator.component';
import { SaveDialogComponent, SaveDialogResult } from '../common/save-dialog/save-dialog.component';
import { ConfirmDialogComponent } from '../common/confirm-dialog/confirm-dialog.component';
import { LabelDialogComponent } from '../common/label-dialog/label-dialog.component';
import { AuthService } from 'src/app/auth/auth.service';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { ToolbarService } from 'src/app/services/toolbar.service';
import { AtfConverterService } from 'src/app/services/atf-converter.service';
import { TextService } from 'src/app/services/text.service';
import { TextPreview } from 'src/app/models/cured';
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

  public stage = 0;

  public pdfSrc = null;
  public pdfFile = null;

  public currentpage = 1;
  public totalPages = 0;
  public pageNumbers: number[] = [];
  public isCropImage = false;
  public result: SelectedPdf

  public boundingBoxes: Rect[] = [];

  public canvasType: CanvasType = CanvasType.SingleSelection;
  public selectedBox: Rect = null;
  public backgroundImage: string;
  public isLoading: boolean = false;
  public areaIsSelected: boolean = false;
  public transliterationResult: string[] = null;

  public goToPage: number = 1;
  public uploadedImageBlob: File = null;

  public textId: number = null;
  public transliterationId: number = null;

  public isLoadedFromServer: boolean = false;
  public isTextFixed: boolean = false;

  public takeTextId: number;
  public takeTransId: number;

  public viewOnly: boolean = false;
  public highlightQuery: string = null;
  public isDragOver: boolean = false;

  // Save dialog
  public isSaving: boolean = false;
  public existingLabels: string[] = [];
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

  // Model info
  public modelInfo: ModelInfo = {
    name: 'Pre-trained (Default)',
    isPretrained: true,
    sizeMb: 0,
    lastModified: null
  };

  // OCR model selection for inference
  public selectedOcrModel: string = 'latest';
  public availableOcrModels = [
    { value: 'latest', label: 'Latest (Pennsylvania Sumerian Dictionary)' },
    { value: 'dillard', label: 'Dillard (Typewriter texts)' },
    { value: 'base', label: 'Base (SAA Corpus)' }
  ];

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

  // Training state
  public isTraining: boolean = false;
  public trainingProgress: any = null;
  private trainingProgressInterval: any = null;

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

      // Update canvas size after resize
      if (this.canvas) {
        setTimeout(() => {
          this.canvas.forceZoomOut(1);
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
    } else {
      // Use full image
      imageData = bgImage.toDataURL({});
    }

    this.curedService.getTransliterations(imageData, this.selectedOcrModel).subscribe(data => {
      if (data.lines.length == 0) {
        this.notificationService.showWarning("AI failed to parse the image, please try again", 20000);
        this.isLoading = false;
        this.toolbarService.setLoading(false);
        return;
      }

      // Set stage to 5 FIRST so lineEditor gets rendered
      this.stage = 5;
      this.isLoading = false;
      this.toolbarService.setLoading(false);

      // Wait for Angular to render the lineEditor component, then process results
      setTimeout(() => {
        // Process with box offset if box was selected
        this.fetchTransliterations(data.lines);
        this.fetchBoundingBoxes(data.dimensions, box);

        // Remove the selection box after processing
        if (box) {
          this.canvas.getCanvas().remove(box);
          this.selectedBox = null;
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
    private sanitizer: DomSanitizer) {
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

    // Load transliteration list for dashboard
    this.loadTransliterationList();

    // Load training status and models
    this.loadTrainingStatus();
    this.loadModels();

    // Subscribe to query param changes to handle navigation within the same route
    this.queryParamsSub = this.route.queryParams.subscribe(params => {
      this.handleQueryParams(params);
    });
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
      this.stage = 0;
    } else {
      // No params - show dashboard
      this.resetToCleanState();
      this.stage = 0;
      this.loadTransliterationList();
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
   * Reset component to clean state for dashboard view
   */
  private resetToCleanState() {
    this.textId = null;
    this.transliterationId = null;
    this.takeTextId = null;
    this.takeTransId = null;
    this.isLoadedFromServer = false;
    this.isTextFixed = false;
    this.viewOnly = false;
    this.lines = null;
    this.boundingBoxes = [];
    this.pdfSrc = null;
    this.pdfFile = null;
    this.backgroundImage = null;
    this.canvasType = CanvasType.SingleSelection;
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

        buttons.push({
          label: 'Curated',
          icon: 'verified',
          action: () => this.markAsCurated(),
          color: 'default',
          disabled: this.textId == null
        });

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
    const dialogRef = this.dialog.open(SaveDialogComponent, {
      data: {
        textId: this.textId,
        existingLabels: this.existingLabels,
        currentLabel: this.currentLabel,
        currentPart: this.currentPart
      }
    });

    dialogRef.afterClosed().subscribe((result: SaveDialogResult | null) => {
      if (!result) { return; } // Cancelled

      this.isSaving = true;
      const { museumNumber, pNumber, publicationNumber, label, part } = result;

      // Store label and part for later use
      this.currentLabel = label;
      this.currentPart = part;

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
    this.textService.create(identifiers).subscribe(textId => {
      this.textId = textId;
      this.doSaveWithLabelAndPart(false, label, part);
    }, err => {
      this.notificationService.showError('Failed to create text');
      this.isSaving = false;
    });
  }

  private doSaveWithLabelAndPart(isFixed: boolean, label: string, part: string) {
    if (this.transliterationId == null && this.uploadedImageBlob) {
      this.curedService.saveImage(this.uploadedImageBlob, this.textId).subscribe(imageName => {
        this.createSubmissionWithLabelAndPart(isFixed, imageName, label, part);
      }, err => {
        this.notificationService.showError('Failed to upload image');
        this.isSaving = false;
      });
    } else {
      this.createSubmissionWithLabelAndPart(isFixed, null, label, part);
    }
  }

  private doSave(isFixed: boolean) {
    this.doSaveWithLabelAndPart(isFixed, this.currentLabel, this.currentPart);
  }

  createSubmissionWithLabelAndPart(isFixed: boolean, imageName: string = null, label: string = '', part: string = '') {
    let lines = this.lines.map(line => line.letter);
    let dimensions = this.boundingBoxes.map(box => new Dimensions(box.left, box.top, box.getScaledHeight(), box.getScaledWidth()))

    this.curedService.createSubmission(this.textId, this.transliterationId, lines, dimensions, imageName, isFixed).subscribe(result => {
      this.notificationService.showInfo("Successfully saved");
      this.transliterationId = result;
      this.isTextFixed = isFixed;
      this.isSaving = false;

      // Update label if provided
      if (label && this.textId) {
        this.textService.updateLabel(this.textId, label).subscribe(
          () => {
            // Add to existing labels if new
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

      this.updateToolbarButtons();
    }, err => {
      this.notificationService.showError('Failed to save');
      this.isSaving = false;
    });
  }

  markAsCurated() {
    if (this.textId == null) {
      this.notificationService.showError('Please save first before marking as curated');
      return;
    }

    // Validate that line count matches box count
    const lineCount = this.lines?.length || 0;
    const boxCount = this.boundingBoxes?.length || 0;

    if (lineCount !== boxCount) {
      this.notificationService.showError(
        `Cannot mark as curated: ${lineCount} lines but ${boxCount} bounding boxes. They must be equal.`
      );
      return;
    }

    this.doSave(true);
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
        this.toolbarService.clearButtons();
      }

    });
  }

  loadTransliteration() {
    this.curedService.loadTransliteration(this.textId, this.transliterationId).subscribe(data => {
      this.processTransliteration(data.lines, data.boxes, true);
      this.isTextFixed = data.is_fixed;
      if (this.highlightQuery) {
        this.setHighlightByQuery(this.highlightQuery);
      }
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
    if (files && files.length > 0) {
      this.processFile(files[0]);
    }
  }

  handleFileInput(event: any) {
    const file = event.target.files[0];
    if (file) {
      this.processFile(file);
    }
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
    this.isLoading = false;
  }

  selectPageFromThumbnail(page: number) {
    this.currentpage = page;
    this.isLoading = true;

    // Move to stage 2 first so the canvas component is rendered
    this.stage = 2;

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
    console.log('[CuReD] onLinesChanged received', updatedLines.length, 'lines, boxes:', this.boundingBoxes.length);
    this.lines = updatedLines;
    this.updateToolbarButtons();
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
    this.isTextFixed = false;
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

  areaSelected() {
    this.stage = 4;
    this.toolbarService.clearButtons();
    this.toolbarService.setLoading(true);

    this.areaIsSelected = true;
    this.isLoading = true;
    let b = this.selectedBox;
    let x = ((this.canvas.getCanvas().backgroundImage as unknown) as FabricImage).toDataURL({
      left: b.left, top: b.top, height: b.getScaledHeight(), width: b.getScaledWidth()
    })
    this.curedService.getTransliterations(x, this.selectedOcrModel).subscribe(data => {
      if (data.lines.length == 0) {
        this.notificationService.showWarning("AI failed to parse the image, there was probably error while loading the image, please try again from the start", 20000)
        this.stage = 3;
        this.isLoading = false;
        this.toolbarService.setLoading(false);
        this.updateToolbarButtons();
        return;
      }

      this.processTransliteration(data.lines, data.dimensions);
    });
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
    this.updateToolbarButtons();
    this.canvas.allowedActions = [this.canvas.panMode, this.canvas.adjustMode, this.canvas.deleteMode, this.canvas.addMode];
    this.canvas.changeMode(CanvasMode.Pan);
  }



  updateBoundingBoxesIndexes() {
    this.boundingBoxes.forEach((box, row) => {
      box.data = new RectData(new Index(row, 0));
    });
  }

  goBack() {
    if (this.stage == 2) {
      // From visualizer back to thumbnails or upload
      this.backgroundImage = null;
      this.selectedBox = null;
      this.canvas.hardReset();
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode];
      if (this.pdfFile == null) {
        // Navigate to dashboard (clears query params)
        this.router.navigate(['/cured']);
      } else {
        this.stage = 1;
        this.updateToolbarButtons();
      }
    } else if (this.stage == 5) {
      // From results back to visualizer (stage 2)
      this.stage = 2;
      this.canvas.removeAllRects();
      this.boundingBoxes = [];
      this.lines = [];
      this.selectedBox = null;
      this.canvas.allowedActions = [this.canvas.panMode, this.canvas.addMode, this.canvas.adjustMode, this.canvas.deleteMode];
      this.updateToolbarButtons();
    } else if (this.stage == 1) {
      // From thumbnails back to upload - navigate to dashboard
      this.router.navigate(['/cured']);
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

  // ============================================
  // Dashboard List Methods (moved from AdminPanel)
  // ============================================

  loadTransliterationList() {
    this.textService.list().subscribe(data => {
      this.curedTexts = data;
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
      if (item.label) {
        labels.add(item.label);
      }
    }
    return Array.from(labels).sort();
  }

  get filteredTexts(): TextPreview[] {
    if (this.selectedLabelFilter === null) {
      return this.curedTexts;
    }
    return this.curedTexts.filter(item => (item.label || '') === this.selectedLabelFilter);
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

  getItemIdentifier(item: TextPreview): string {
    if (item.text_identifiers && item.text_identifiers.museum &&
        item.text_identifiers.museum.name) {
      const fullName = item.text_identifiers.museum.name.trim();
      const abbr = fullName.split(' - ')[0] || fullName;
      const num = item.text_identifiers.museum.number || '';
      return `${abbr}.${num}`.trim();
    }
    if (item.text_identifiers && item.text_identifiers.p_number &&
        item.text_identifiers.p_number.number) {
      return `P-${item.text_identifiers.p_number.number}`;
    }
    return '-';
  }

  openLabelDialog(item: TextPreview, event: Event) {
    event.stopPropagation();

    const dialogRef = this.dialog.open(LabelDialogComponent, {
      data: {
        currentLabel: item.label || '',
        existingLabels: this.existingLabels
      }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result === null) { return; }
      const newLabel = result as string;

      this.textService.updateLabel(item.text_id, newLabel).subscribe(
        () => {
          item.label = newLabel;
          if (newLabel && !this.existingLabels.includes(newLabel)) {
            this.existingLabels.push(newLabel);
            this.existingLabels.sort();
          }
          this.notificationService.showSuccess(newLabel ? `Label set to "${newLabel}"` : 'Label removed');
        },
        () => { this.notificationService.showError('Failed to update label'); }
      );
    });
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

  startTraining() {
    if (!this.trainingStatus.isReady) {
      this.notificationService.showError('Not enough training data. Need at least 1000 curated lines.');
      return;
    }

    if (this.isTraining) {
      this.notificationService.showWarning('Training is already in progress.');
      return;
    }

    this.isTraining = true;
    this.trainingProgress = { status: 'preparing', current_epoch: 0, total_epochs: 50 };

    this.curedService.startTraining(50).subscribe(
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

          if (progress.status === 'completed') {
            this.stopTrainingProgressPolling();
            this.isTraining = false;
            this.notificationService.showSuccess(`Training completed! Model: ${progress.model_name}`);
            this.loadTrainingStatus();
            this.loadModels(); // Refresh model list
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

}
