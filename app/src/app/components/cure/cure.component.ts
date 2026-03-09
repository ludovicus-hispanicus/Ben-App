import { AfterViewInit, Component, ElementRef, HostListener, OnDestroy, OnInit, QueryList, ViewChild, ViewChildren } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { fabric } from 'fabric';
import { Image as FabricImage, Rect } from 'fabric/fabric-impl';
import { PDFDocumentProxy } from 'ng2-pdf-viewer';
import { Dimensions, Index, Letter } from 'src/app/models/letter';
import { DatasetPreview, TextIdentifier, TextIdentifiers, TextPreview } from 'src/app/models/cured';
import { CuReSignResult, CuReModelInfo, CuReActiveModel, CuReTrainingStatus, CuReTrainingProgress } from 'src/app/models/cure';
import { CureService } from 'src/app/services/cure.service';
import { NotificationService } from 'src/app/services/notification.service';
import { ToolbarService } from 'src/app/services/toolbar.service';
import { CanvasMode, CanvasType, FabricCanvasComponent } from '../fabric-canvas/fabric-canvas.component';
import { TextEditorComponent } from '../cure-d/text-editor/text-editor.component';
import { MatDialog } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';
import { ConfirmDialogComponent } from '../common/confirm-dialog/confirm-dialog.component';
import { LabelDialogComponent } from '../common/label-dialog/label-dialog.component';
import { ImageBrowserDialogComponent } from '../common/image-browser-dialog/image-browser-dialog.component';
import { SaveDialogComponent, SaveDialogResult } from '../common/save-dialog/save-dialog.component';
import { TextService } from 'src/app/services/text.service';
import { CuredService } from 'src/app/services/cured.service';
import { DatasetService } from 'src/app/services/dataset.service';
import { SelectedPage } from '../../models/pages';
import { PagesService } from '../../services/pages.service';
import { DomSanitizer } from '@angular/platform-browser';

export enum CureViewMode {
  Datasets = 'datasets',
  Models = 'models',
  Training = 'training'
}

@Component({
  selector: 'cure',
  templateUrl: './cure.component.html',
  styleUrls: ['./cure.component.scss']
})
export class CureComponent implements OnInit, AfterViewInit, OnDestroy {
  public CanvasMode = CanvasMode;
  public CureViewMode = CureViewMode;

  // Tab navigation
  public viewMode: CureViewMode = CureViewMode.Datasets;

  // Stage workflow within Datasets: 0=dataset list, 1=PDF page select, 2=image+model, 3=results
  public stage = 0;

  // PDF handling
  public pdfSrc = null;
  public pdfFile: File = null;
  public currentpage = 1;
  public totalPages = 0;
  public pageNumbers: number[] = [];
  public visiblePageNumbers: number[] = [];
  public goToPageInput: number = 1;
  public readonly PAGE_WINDOW_SIZE = 10;

  // Image
  public backgroundImage: string;
  public uploadedImageBlob: File = null;
  public isDragOver: boolean = false;

  // Canvas
  public canvasType: CanvasType = CanvasType.SingleSelection;
  public selectedBox: Rect = null;
  public cropOffset: { x: number; y: number } = null;
  public boundingBoxes: Rect[] = [];
  public isLoading: boolean = false;

  // Results (sign-level)
  public signs: CuReSignResult[] = [];
  public lines: Letter[] = [];
  public selectedSign: CuReSignResult = null;
  public selectedSignIndex: number = -1;
  public transliterationHtml: string = '';
  public isSaving: boolean = false;

  // Save state (BEN database)
  public textId: number = null;
  public transliterationId: number = null;
  private autoSaveTimer: any = null;
  private readonly AUTO_SAVE_DEBOUNCE_MS = 2000;
  public existingLabels: string[] = [];
  public currentLabel: string = '';
  public currentPart: string = '';
  public isCuratedCure: boolean = false;

  // Sign label → cuneiform unicode map (for live preview conversion)
  public signToUnicodeMap: { [key: string]: string } = null;

  // Cuneiform script/font selection
  public selectedScript: string = 'Assurbanipal';
  public scriptOptions = [
    { label: 'Neo-Assyrian', font: 'Assurbanipal' },
    { label: 'Neo-Babylonian', font: 'Esagil' },
    { label: 'Old Babylonian', font: 'Santakku' },
  ];

  // Models
  public selectedModel: string = 'active';
  public models: CuReModelInfo[] = [];
  public activeModel: CuReActiveModel = null;
  public selectedCureModel: CuReModelInfo | null = null;

  // Training
  public trainingStatus: CuReTrainingStatus = null;
  public trainingProgress: CuReTrainingProgress = null;
  public isTraining: boolean = false;
  private trainingProgressInterval: any = null;
  public trainingRightTab: 'progress' | 'jobs' = 'jobs';

  // Training config form
  public trainingModelName: string = '';
  public trainingEpochs: number = 50;
  public trainingBatchSize: number = 32;
  public trainingLearningRate: number = 0.001;
  public trainingPatience: number = 20;
  public trainingDevice: string = 'auto';
  public trainingBaseModel: string = '';

  // Dashboard
  public datasets: DatasetPreview[] = [];
  public selectedDataset: DatasetPreview | null = null;
  public showDatasetList: boolean = true;
  public newDatasetName: string = '';

  // Dataset view mode, search & sort
  public datasetViewMode: 'grid' | 'list' = 'grid';
  public datasetSearchQuery: string = '';
  public datasetSortColumn: 'name' | 'texts' | 'curated' | 'created' = 'name';
  public datasetSortDirection: 'asc' | 'desc' = 'asc';
  public datasetTexts: TextPreview[] = [];
  public isLoadingTexts: boolean = false;

  // Text view mode, search & sort (inside dataset)
  public textViewMode: 'grid' | 'list' = 'list';
  public textSearchQuery: string = '';
  public textSortColumn: 'name' | 'label' | 'id' | 'lines' = 'name';
  public textSortDirection: 'asc' | 'desc' = 'asc';

  // Dataset card selection & inline rename
  public selectedDatasetCard: DatasetPreview | null = null;
  public selectedDatasets: Set<number> = new Set();
  public lastSelectedDatasetIndex: number = -1;
  public editingDataset: DatasetPreview | null = null;
  public editingDatasetName: string = '';
  private datasetRenameTimer: any = null;
  private datasetRenameCancelled: boolean = false;

  // Text multi-selection
  public selectedTextItems: Set<number> = new Set();
  public lastSelectedTextIndex: number = -1;

  // Dataset context menu
  public datasetContextMenuVisible: boolean = false;
  public datasetContextMenuX: number = 0;
  public datasetContextMenuY: number = 0;
  public datasetContextMenuNode: DatasetPreview | null = null;

  // Resizable panels
  public leftPanelWidth: number = 60;
  private isResizing: boolean = false;
  private resizeHandler: (e: MouseEvent | TouchEvent) => void;
  private resizeEndHandler: () => void;

  @ViewChild('canvas') canvas: FabricCanvasComponent;
  @ViewChild('lineEditor', { static: false }) lineEditor: TextEditorComponent;
  @ViewChildren('datasetRenameInput') datasetRenameInputs!: QueryList<ElementRef>;

  constructor(
    private cureService: CureService,
    private curedService: CuredService,
    private textService: TextService,
    private datasetService: DatasetService,
    private notificationService: NotificationService,
    private toolbarService: ToolbarService,
    private dialog: MatDialog,
    private http: HttpClient,
    private route: ActivatedRoute,
    private pagesService: PagesService,
    private sanitizer: DomSanitizer,
  ) {}

  setViewMode(mode: CureViewMode): void {
    this.viewMode = mode;
    if (mode === CureViewMode.Datasets) {
      this.loadDatasets();
    } else if (mode === CureViewMode.Models) {
      this.loadModels();
      this.loadActiveModel();
    } else if (mode === CureViewMode.Training) {
      this.loadTrainingStatus();
    }
  }

  ngOnInit(): void {
    this.loadDatasets();
    this.loadActiveModel();
    this.loadTrainingStatus();
    this.loadModels();
    this.loadSignMap();

    this.route.queryParams.subscribe(params => {
      if (params['library_dataset'] && params['library_page']) {
        this.loadFromLibrary(params['library_dataset'], parseInt(params['library_page']));
      }
    });
  }

  private loadSignMap(): void {
    this.cureService.getLabels().subscribe(
      data => {
        if (data.label_to_unicode && Object.keys(data.label_to_unicode).length > 0) {
          // Server returns unicode→labels mapping (e.g. "𒀭": "d / an / dingir").
          // Invert to labels→unicode for the text-editor preview.
          const inverted: { [key: string]: string } = {};
          for (const [unicodeChar, labels] of Object.entries(data.label_to_unicode)) {
            const labelList = (labels as string).split(' / ');
            for (const label of labelList) {
              const trimmed = label.trim();
              if (trimmed && !inverted[trimmed]) {
                inverted[trimmed] = unicodeChar;
              }
            }
          }
          if (Object.keys(inverted).length > 0) {
            this.signToUnicodeMap = inverted;
          }
        }
      },
      () => {} // sign map is optional, fail silently
    );
  }

  ngAfterViewInit(): void {}

  ngOnDestroy(): void {
    if (this.trainingProgressInterval) {
      clearInterval(this.trainingProgressInterval);
    }
    if (this.autoSaveTimer) {
      clearTimeout(this.autoSaveTimer);
    }
  }

  onLinesChanged(updatedLines: Letter[]): void {
    this.lines = updatedLines;
    this.autoSave();
  }

  private autoSave(): void {
    // Only auto-save if we have an existing transliteration (already saved once)
    if (!this.transliterationId || !this.textId) return;

    if (this.autoSaveTimer) clearTimeout(this.autoSaveTimer);
    this.autoSaveTimer = setTimeout(() => {
      const lineTexts = this.lines.map(line => line.letter);
      const dimensions = this.signs.map(s => new Dimensions(
        s.bbox.x, s.bbox.y, s.bbox.height, s.bbox.width
      ));

      this.curedService.createSubmission(
        this.textId, this.transliterationId, lineTexts, dimensions, null, this.isCuratedCure, false
      ).subscribe(
        result => { this.transliterationId = result; },
        () => {}
      );
    }, this.AUTO_SAVE_DEBOUNCE_MS);
  }

  // ==========================================
  // Canvas dimensions
  // ==========================================

  getCanvasDimensions(): { width: number; height: number } {
    // Read actual panel-left container size if available
    const panelLeft = document.querySelector('.panel-left') as HTMLElement;
    if (panelLeft) {
      return {
        width: Math.max(panelLeft.offsetWidth, 400),
        height: Math.max(panelLeft.offsetHeight, 400)
      };
    }
    // Fallback
    const availableHeight = window.innerHeight - 100;
    const availableWidth = window.innerWidth * 0.6;
    return {
      width: Math.max(availableWidth, 500),
      height: Math.max(availableHeight, 600)
    };
  }

  // ==========================================
  // Dashboard — Datasets
  // ==========================================

  loadDatasets(): void {
    this.cureService.listDatasets().subscribe(
      datasets => this.datasets = datasets,
      err => console.error('Failed to load CuRe datasets', err)
    );
  }

  selectDataset(dataset: DatasetPreview): void {
    this.selectedDataset = dataset;
    this.showDatasetList = false;
    this.isLoadingTexts = true;
    this.datasetTexts = [];
    this.clearDatasetSelection();
    this.clearTextSelection();
    this.datasetService.getTexts(dataset.dataset_id).subscribe(
      data => {
        this.datasetTexts = data;
        this.isLoadingTexts = false;
        this.loadTransliterationIds();
      },
      () => {
        this.isLoadingTexts = false;
      }
    );
  }

  backToDatasets(): void {
    this.showDatasetList = true;
    this.selectedDataset = null;
    this.datasetTexts = [];
    this.clearTextSelection();
    this.loadDatasets();
  }

  private loadTransliterationIds(): void {
    for (const item of this.datasetTexts) {
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

  private loadListThumbnail(item: TextPreview): void {
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

  openSavedResult(item: TextPreview): void {
    if (!item.latest_transliteration_id) {
      this.notificationService.showWarning('No transliteration found for this text');
      return;
    }

    this.textId = item.text_id;
    this.transliterationId = item.latest_transliteration_id;
    this.currentLabel = item.label || '';
    this.currentPart = item.part || '';
    this.isCuratedCure = item.is_curated_kraken || false;
    this.isLoading = true;

    // Load image
    this.curedService.getImage(item.text_id, item.latest_transliteration_id).subscribe(
      blob => {
        const reader = new FileReader();
        reader.onload = (e) => {
          this.backgroundImage = e.target.result as string;
          this.uploadedImageBlob = new File([blob], `text_${item.text_id}.png`, { type: blob.type });
          this.stage = 3;

          // Load transliteration data
          this.curedService.loadTransliteration(item.text_id, item.latest_transliteration_id).subscribe(
            data => {
              this.lines = data.lines.map((text, row) => {
                const letter = new Letter(text);
                letter.index = new Index(row, 0);
                return letter;
              });
              this.signs = [];
              this.transliterationHtml = '';
              this.isLoading = false;

              setTimeout(() => {
                this.setCanvasImage(this.backgroundImage);
                if (this.lineEditor) {
                  this.lineEditor.setLines(this.lines);
                }
              }, 200);
            },
            () => {
              this.isLoading = false;
              this.notificationService.showError('Failed to load transliteration');
            }
          );
        };
        reader.readAsDataURL(blob);
      },
      () => {
        this.isLoading = false;
        this.notificationService.showError('Failed to load image');
      }
    );
  }

  toggleTextSelection(item: TextPreview, event: MouseEvent): void {
    const index = this.filteredTexts.indexOf(item);
    const id = item.text_id;

    if (event.shiftKey && this.lastSelectedTextIndex >= 0) {
      const start = Math.min(this.lastSelectedTextIndex, index);
      const end = Math.max(this.lastSelectedTextIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedTextItems.add(this.filteredTexts[i].text_id);
      }
    } else if (event.ctrlKey || event.metaKey) {
      if (this.selectedTextItems.has(id)) {
        this.selectedTextItems.delete(id);
      } else {
        this.selectedTextItems.add(id);
      }
    } else {
      this.selectedTextItems.clear();
      this.selectedTextItems.add(id);
    }
    this.lastSelectedTextIndex = index;
  }

  isTextSelected(item: TextPreview): boolean {
    return this.selectedTextItems.has(item.text_id);
  }

  selectAllTexts(): void {
    if (this.selectedTextItems.size === this.filteredTexts.length) {
      this.selectedTextItems.clear();
    } else {
      this.filteredTexts.forEach(t => this.selectedTextItems.add(t.text_id));
    }
  }

  clearTextSelection(): void {
    this.selectedTextItems.clear();
    this.lastSelectedTextIndex = -1;
  }

  deleteTextItem(item: TextPreview, event: MouseEvent): void {
    event.stopPropagation();
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: { message: `Delete text "${this.getItemIdentifier(item)}" (BEN ${item.text_id})?` }
    });
    dialogRef.afterClosed().subscribe(confirmed => {
      if (confirmed) {
        this.curedService.deleteText(item.text_id).subscribe(
          () => {
            this.datasetTexts = this.datasetTexts.filter(t => t.text_id !== item.text_id);
            this.notificationService.showSuccess('Text deleted');
          },
          () => this.notificationService.showError('Failed to delete text')
        );
      }
    });
  }

  deleteSelectedTexts(): void {
    if (this.selectedTextItems.size === 0) { return; }
    const count = this.selectedTextItems.size;
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: { message: `Delete ${count} selected text(s)?` }
    });
    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed) { return; }
      const selectedItems = this.filteredTexts.filter(t => this.selectedTextItems.has(t.text_id));
      let completed = 0;
      let errors = 0;
      const total = selectedItems.length;
      selectedItems.forEach(item => {
        this.curedService.deleteText(item.text_id).subscribe({
          next: () => {
            completed++;
            this.datasetTexts = this.datasetTexts.filter(t => t.text_id !== item.text_id);
            if (completed + errors === total) {
              this.notificationService.showSuccess(`Deleted ${completed} text(s)`);
              this.clearTextSelection();
            }
          },
          error: () => {
            errors++;
            if (completed + errors === total) {
              this.notificationService.showError(`Deleted ${completed}, failed ${errors}`);
              this.clearTextSelection();
            }
          }
        });
      });
    });
  }

  createDataset(): void {
    if (!this.newDatasetName.trim()) return;
    this.cureService.createDataset(this.newDatasetName.trim()).subscribe(
      () => {
        this.newDatasetName = '';
        this.loadDatasets();
        this.notificationService.showSuccess('Dataset created');
      },
      err => this.notificationService.showError('Failed to create dataset')
    );
  }

  // ============== Dataset Filtering & Sorting ==============

  get filteredDatasets(): DatasetPreview[] {
    let list = this.datasets;

    // Search filter
    if (this.datasetSearchQuery.trim()) {
      const q = this.datasetSearchQuery.trim().toLowerCase();
      list = list.filter(p => p.name.toLowerCase().includes(q));
    }

    // Sort
    const sorted = [...list];
    sorted.sort((a, b) => {
      let cmp = 0;
      switch (this.datasetSortColumn) {
        case 'name':
          cmp = a.name.localeCompare(b.name);
          break;
        case 'texts':
          cmp = (a.text_count || 0) - (b.text_count || 0);
          break;
        case 'curated':
          cmp = (a.curated_count || 0) - (b.curated_count || 0);
          break;
        case 'created':
          cmp = (a.created_at || 0) - (b.created_at || 0);
          break;
      }
      return this.datasetSortDirection === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }

  toggleDatasetSort(column: 'name' | 'texts' | 'curated' | 'created'): void {
    if (this.datasetSortColumn === column) {
      this.datasetSortDirection = this.datasetSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.datasetSortColumn = column;
      this.datasetSortDirection = 'asc';
    }
  }

  clearDatasetSearch(): void {
    this.datasetSearchQuery = '';
  }

  // ============== Text Filtering & Sorting (inside dataset) ==============

  get filteredTexts(): TextPreview[] {
    let list = this.datasetTexts;

    if (this.textSearchQuery.trim()) {
      const q = this.textSearchQuery.trim().toLowerCase();
      list = list.filter(t => {
        const identifier = this.getItemIdentifier(t).toLowerCase();
        const label = (t.label || '').toLowerCase();
        const labels = (t.labels || []).join(' ').toLowerCase();
        return identifier.includes(q) || label.includes(q) || labels.includes(q)
          || String(t.text_id).includes(q);
      });
    }

    const sorted = [...list];
    sorted.sort((a, b) => {
      let cmp = 0;
      switch (this.textSortColumn) {
        case 'name':
          cmp = this.getItemIdentifier(a).localeCompare(this.getItemIdentifier(b));
          break;
        case 'label':
          cmp = (a.label || '').localeCompare(b.label || '');
          break;
        case 'id':
          cmp = (a.text_id || 0) - (b.text_id || 0);
          break;
        case 'lines':
          cmp = (a.lines_count || 0) - (b.lines_count || 0);
          break;
      }
      return this.textSortDirection === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }

  toggleTextSort(column: 'name' | 'label' | 'id' | 'lines'): void {
    if (this.textSortColumn === column) {
      this.textSortDirection = this.textSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.textSortColumn = column;
      this.textSortDirection = 'asc';
    }
  }

  clearTextSearch(): void {
    this.textSearchQuery = '';
  }

  formatDatasetDate(timestamp: number): string {
    if (!timestamp) return '—';
    return new Date(timestamp * 1000).toLocaleDateString();
  }

  // ============== Dataset Card Selection & Inline Rename ==============

  selectDatasetCard(dataset: DatasetPreview, event?: MouseEvent): void {
    this.selectedDatasetCard = dataset;
    const index = this.filteredDatasets.indexOf(dataset);
    const id = dataset.dataset_id;

    if (event?.shiftKey && this.lastSelectedDatasetIndex >= 0) {
      const start = Math.min(this.lastSelectedDatasetIndex, index);
      const end = Math.max(this.lastSelectedDatasetIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedDatasets.add(this.filteredDatasets[i].dataset_id);
      }
    } else if (event?.ctrlKey || event?.metaKey) {
      if (this.selectedDatasets.has(id)) {
        this.selectedDatasets.delete(id);
      } else {
        this.selectedDatasets.add(id);
      }
    } else {
      this.selectedDatasets.clear();
      this.selectedDatasets.add(id);
    }
    this.lastSelectedDatasetIndex = index;
  }

  isDatasetSelected(dataset: DatasetPreview): boolean {
    return this.selectedDatasets.has(dataset.dataset_id);
  }

  selectAllDatasets(): void {
    if (this.selectedDatasets.size === this.filteredDatasets.length) {
      this.selectedDatasets.clear();
    } else {
      this.filteredDatasets.forEach(p => this.selectedDatasets.add(p.dataset_id));
    }
  }

  clearDatasetSelection(): void {
    this.selectedDatasets.clear();
    this.lastSelectedDatasetIndex = -1;
  }

  deleteSelectedDatasets(): void {
    if (this.selectedDatasets.size === 0) { return; }
    const count = this.selectedDatasets.size;
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: { message: `Delete ${count} selected dataset(s)?` }
    });
    dialogRef.afterClosed().subscribe(confirmed => {
      if (!confirmed) { return; }
      const ids = Array.from(this.selectedDatasets);
      let completed = 0;
      let errors = 0;
      ids.forEach(id => {
        this.cureService.deleteDataset(id).subscribe({
          next: () => {
            completed++;
            if (completed + errors === ids.length) {
              this.notificationService.showSuccess(`Deleted ${completed} dataset(s)`);
              this.clearDatasetSelection();
              this.loadDatasets();
            }
          },
          error: () => {
            errors++;
            if (completed + errors === ids.length) {
              this.notificationService.showError(`Deleted ${completed}, failed ${errors}`);
              this.clearDatasetSelection();
              this.loadDatasets();
            }
          }
        });
      });
    });
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

    this.cureService.renameDataset(dataset.dataset_id, newName).subscribe(
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

  // ============== Dataset Context Menu ==============

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
  }

  @HostListener('document:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if (event.ctrlKey && event.key === 'a') {
      if (this.showDatasetList && this.viewMode === CureViewMode.Datasets) {
        event.preventDefault();
        this.selectAllDatasets();
      } else if (!this.showDatasetList && this.stage === 0) {
        event.preventDefault();
        this.selectAllTexts();
      }
    }
    if (event.key === 'Delete') {
      if (this.showDatasetList && this.selectedDatasets.size > 0 && this.viewMode === CureViewMode.Datasets) {
        this.deleteSelectedDatasets();
      } else if (!this.showDatasetList && this.selectedTextItems.size > 0 && this.stage === 0) {
        this.deleteSelectedTexts();
      }
    }
  }

  deleteDataset(dataset: DatasetPreview): void {
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: { message: `Delete dataset "${dataset.name}"?` }
    });
    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.cureService.deleteDataset(dataset.dataset_id).subscribe(
          () => {
            this.loadDatasets();
            this.notificationService.showSuccess('Dataset deleted');
          },
          err => this.notificationService.showError('Failed to delete dataset')
        );
      }
    });
  }

  // ==========================================
  // File upload
  // ==========================================

  handleFileInput(event: any): void {
    const file = event.target.files[0] as File;
    if (!file) return;
    this.processFile(file);
  }

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
    const files = event.dataTransfer?.files;
    if (files && files.length > 0) {
      this.processFile(files[0]);
    }
  }

  private loadFromLibrary(projectId: string, pageNumber: number): void {
    const imageUrl = this.pagesService.getPageImageUrl(projectId, pageNumber);
    this.http.get(imageUrl, { responseType: 'blob' }).subscribe({
      next: (blob) => {
        const file = new File([blob], `page_${pageNumber}.png`, { type: 'image/png' });
        this.processFile(file);
      },
      error: () => {
        this.notificationService.showError('Failed to load image from library');
      }
    });
  }

  browseServer(): void {
    const dialogRef = this.dialog.open(ImageBrowserDialogComponent, {
      width: '1000px', height: '720px'
    });
    dialogRef.afterClosed().subscribe((result: SelectedPage[] | null) => {
      if (!result || result.length === 0) return;
      const page = result[0];
      this.http.get(page.image_url, { responseType: 'blob' }).subscribe(blob => {
        const file = new File([blob], page.filename, { type: 'image/png' });
        this.processFile(file);
      });
    });
  }

  handleFolderInput(event: any): void {
    const files: FileList = event.target.files;
    if (!files || files.length === 0) return;

    const supportedExts = ['.png', '.jpg', '.jpeg'];
    const imageFiles: File[] = [];
    for (let i = 0; i < files.length; i++) {
      const name = files[i].name.toLowerCase();
      if (supportedExts.some(ext => name.endsWith(ext))) {
        imageFiles.push(files[i]);
      }
    }

    if (imageFiles.length === 0) {
      this.notificationService.showError('No supported image files found (PNG, JPG)');
      event.target.value = '';
      return;
    }

    imageFiles.sort((a, b) => a.name.localeCompare(b.name));
    this.notificationService.showInfo(`Loaded ${imageFiles.length} images from folder`);
    this.processFile(imageFiles[0]);
    event.target.value = '';
  }

  processFile(file: File): void {
    if (file.type === 'application/pdf') {
      this.loadPDFFile(file);
    } else if (file.type.startsWith('image/')) {
      this.loadImage(file);
    } else {
      this.notificationService.showWarning('Unsupported file type. Use PDF, PNG, or JPG.');
    }
  }

  loadPDFFile(file: File): void {
    this.pdfFile = file;
    this.isLoading = true;
    this.totalPages = 0;
    this.pageNumbers = [];
    const reader = new FileReader();
    reader.onload = (e) => {
      this.pdfSrc = new Uint8Array(e.target.result as ArrayBuffer);
      this.stage = 1;
    };
    reader.readAsArrayBuffer(file);
  }

  afterLoadComplete(pdf: PDFDocumentProxy): void {
    this.totalPages = pdf.numPages;
    this.pageNumbers = Array.from({ length: pdf.numPages }, (_, i) => i + 1);
    this.goToPageInput = 1;
    this.updateVisiblePages(1);
    this.isLoading = false;
  }

  updateVisiblePages(targetPage: number): void {
    if (this.totalPages === 0) return;
    let startPage = Math.max(1, targetPage - 4);
    let endPage = Math.min(this.totalPages, startPage + this.PAGE_WINDOW_SIZE - 1);
    if (endPage - startPage + 1 < this.PAGE_WINDOW_SIZE) {
      startPage = Math.max(1, endPage - this.PAGE_WINDOW_SIZE + 1);
    }
    this.visiblePageNumbers = [];
    for (let i = startPage; i <= endPage; i++) {
      this.visiblePageNumbers.push(i);
    }
  }

  jumpToPage(): void {
    const page = Math.max(1, Math.min(this.totalPages, this.goToPageInput || 1));
    this.goToPageInput = page;
    this.updateVisiblePages(page);
  }

  nextPageWindow(): void {
    const lastVisible = this.visiblePageNumbers[this.visiblePageNumbers.length - 1];
    if (lastVisible < this.totalPages) {
      this.updateVisiblePages(lastVisible + 1);
      this.goToPageInput = this.visiblePageNumbers[0];
    }
  }

  prevPageWindow(): void {
    const firstVisible = this.visiblePageNumbers[0];
    if (firstVisible > 1) {
      const newTarget = Math.max(1, firstVisible - this.PAGE_WINDOW_SIZE);
      this.updateVisiblePages(newTarget);
      this.goToPageInput = this.visiblePageNumbers[0];
    }
  }

  selectPageFromThumbnail(page: number): void {
    this.currentpage = page;
    this.isLoading = true;

    this.cureService.convertPdf(this.pdfFile, page).subscribe(
      blob => {
        this.uploadedImageBlob = new File([blob], `page_${page}.png`, { type: 'image/png' });
        const reader = new FileReader();
        reader.onload = (e) => {
          this.backgroundImage = e.target.result as string;
          this.stage = 2;
          // Wait for canvas to render in DOM, then set image and force size
          setTimeout(() => {
            this.isLoading = false;
            this.setCanvasImage(this.backgroundImage);
          }, 200);
        };
        reader.readAsDataURL(blob);
      },
      err => {
        this.notificationService.showError('Failed to extract PDF page');
        this.isLoading = false;
      }
    );
  }

  loadImage(file: File): void {
    this.uploadedImageBlob = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      this.backgroundImage = e.target.result as string;
      this.stage = 2;
      // Wait for canvas to render in DOM, then set image and force size
      setTimeout(() => this.setCanvasImage(this.backgroundImage), 200);
    };
    reader.readAsDataURL(file);
  }

  private setCanvasImage(imageData: string): void {
    if (!this.canvas) return;
    this.canvas.props.canvasImage = imageData;
    this.canvas.setCanvasImage();
    const dims = this.getCanvasDimensions();
    this.canvas.props.canvasHeight = dims.height;
    this.canvas.props.canvasWidth = dims.width;
    this.canvas.forceCanvasSize();
    this.canvas.forceZoomOut(0.5);
  }

  // ==========================================
  // Selection box (crop region)
  // ==========================================

  onBoxAdded(rect: Rect): void {
    if (this.stage !== 2) return;

    // Only allow one selection box at a time — remove the previous one
    if (this.selectedBox) {
      const fabricCanvas = this.canvas.getCanvas();
      fabricCanvas.remove(this.selectedBox);
    }
    this.selectedBox = rect;
  }

  /**
   * Get image data for detection, cropped to selection box if one exists.
   * Uses an offscreen HTML canvas to crop the Fabric.js background image.
   */
  private getImageForDetection(): string | null {
    const fabricCanvas = this.canvas.getCanvas();
    const bgImage = fabricCanvas.backgroundImage as unknown as FabricImage;
    if (!bgImage) return null;

    const imgElement = (bgImage as any).getElement() as HTMLImageElement;
    if (!imgElement) return null;

    const tempCanvas = document.createElement('canvas');
    const ctx = tempCanvas.getContext('2d');

    if (this.selectedBox) {
      // Crop to the selection box region
      const left = Math.max(0, this.selectedBox.left);
      const top = Math.max(0, this.selectedBox.top);
      const width = this.selectedBox.getScaledWidth();
      const height = this.selectedBox.getScaledHeight();

      tempCanvas.width = width;
      tempCanvas.height = height;
      ctx.drawImage(imgElement, left, top, width, height, 0, 0, width, height);

      // Store offset so result boxes can be placed correctly on the full canvas
      this.cropOffset = { x: left, y: top };
    } else {
      // Full image — no crop
      tempCanvas.width = imgElement.naturalWidth || imgElement.width;
      tempCanvas.height = imgElement.naturalHeight || imgElement.height;
      ctx.drawImage(imgElement, 0, 0);
      this.cropOffset = null;
    }

    return tempCanvas.toDataURL('image/png');
  }

  // ==========================================
  // Model management
  // ==========================================

  loadActiveModel(): void {
    this.cureService.getActiveModel().subscribe(
      model => this.activeModel = model,
      err => console.error('Failed to load active model', err)
    );
  }

  loadModels(): void {
    this.cureService.getModels().subscribe(
      data => this.models = data.models,
      err => console.error('Failed to load models', err)
    );
  }

  selectCureModel(model: CuReModelInfo): void {
    this.selectedCureModel = model;
  }

  activateModel(modelName: string): void {
    this.cureService.activateModel(modelName).subscribe(
      () => {
        this.loadActiveModel();
        this.loadModels();
        this.notificationService.showSuccess(`Model "${modelName}" activated`);
      },
      err => this.notificationService.showError('Failed to activate model')
    );
  }

  deleteCureModel(modelName: string): void {
    const dialogRef = this.dialog.open(ConfirmDialogComponent, {
      data: { message: `Delete model "${modelName}"?` }
    });
    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.cureService.deleteModel(modelName).subscribe(
          () => {
            if (this.selectedCureModel?.name === modelName) {
              this.selectedCureModel = null;
            }
            this.loadModels();
            this.notificationService.showSuccess(`Model "${modelName}" deleted`);
          },
          err => this.notificationService.showError('Failed to delete model')
        );
      }
    });
  }

  // ==========================================
  // Detect & Classify
  // ==========================================

  detectAndClassify(): void {
    this.toolbarService.setLoading(true);
    this.isLoading = true;

    const imageData = this.getImageForDetection();
    if (!imageData) {
      this.notificationService.showError('No image loaded');
      this.toolbarService.setLoading(false);
      this.isLoading = false;
      return;
    }

    this.cureService.classify(imageData, this.selectedModel).subscribe(
      data => {
        const hasSigns = data.signs && data.signs.length > 0;
        const hasDimensions = data.dimensions && data.dimensions.length > 0;

        if (!hasSigns && !hasDimensions) {
          this.notificationService.showWarning('No signs detected. Try drawing a box around the tablet area.');
          this.isLoading = false;
          this.toolbarService.setLoading(false);
          return;
        }

        if (hasSigns) {
          // Full classification results
          this.signs = data.signs;

          // ACE Editor gets transliteration names (editable text)
          this.lines = this.buildTransliterationLines(data.signs);

          // Preview pane gets cuneiform signs (Assurbanipal font)
          this.transliterationHtml = this.buildCuneiformHtml(data.signs);
          this.fetchSignBoxes(data.signs);

          if (this.lineEditor) {
            this.lineEditor.setLines(this.lines);
          }
        } else {
          // Detection succeeded but no classifier model — show boxes without labels
          this.signs = [];
          this.transliterationHtml = '';
          this.lines = data.lines.map((text, row) => {
            const letter = new Letter(text);
            letter.index = new Index(row, 0);
            return letter;
          });

          this.fetchDetectionBoxes(data.dimensions);
          this.notificationService.showWarning(
            'No classifier model installed. Showing detection boxes only. ' +
            'Import the cyrus model to get sign labels.'
          );
        }

        this.stage = 3;
        this.isLoading = false;
        this.toolbarService.setLoading(false);
      },
      err => {
        this.notificationService.showError('Classification failed: ' + (err.error?.detail || err.message));
        this.isLoading = false;
        this.toolbarService.setLoading(false);
      }
    );
  }

  detectOnly(): void {
    this.toolbarService.setLoading(true);
    this.isLoading = true;

    const imageData = this.getImageForDetection();
    if (!imageData) {
      this.notificationService.showError('No image loaded');
      this.toolbarService.setLoading(false);
      this.isLoading = false;
      return;
    }

    this.cureService.detect(imageData).subscribe(
      data => {
        // Create detection-only boxes (no labels)
        this.signs = [];
        this.lines = [];
        this.fetchDetectionBoxes(data.dimensions);

        this.stage = 3;
        this.isLoading = false;
        this.toolbarService.setLoading(false);
        this.notificationService.showSuccess(`Detected ${data.sign_count} signs in ${data.line_count} lines`);
      },
      err => {
        this.notificationService.showError('Detection failed: ' + (err.error?.detail || err.message));
        this.isLoading = false;
        this.toolbarService.setLoading(false);
      }
    );
  }

  // ==========================================
  // Sign box rendering
  // ==========================================

  private fetchSignBoxes(signs: CuReSignResult[]): void {
    if (!this.canvas) return;
    const fabricCanvas = this.canvas.getCanvas();

    // Clear existing boxes (including any selection box from stage 2)
    this.boundingBoxes.forEach(box => fabricCanvas.remove(box));
    this.boundingBoxes = [];
    if (this.selectedBox) {
      fabricCanvas.remove(this.selectedBox);
    }

    // Offset: when image was cropped, result coords are relative to the crop.
    // Add the crop origin so boxes align with the full background image.
    const ox = this.cropOffset ? this.cropOffset.x : 0;
    const oy = this.cropOffset ? this.cropOffset.y : 0;

    for (let i = 0; i < signs.length; i++) {
      const sign = signs[i];
      const bbox = sign.bbox;

      const color = this.getConfidenceColor(sign.confidence);

      const rect = new fabric.Rect({
        left: bbox.x + ox,
        top: bbox.y + oy,
        width: bbox.width,
        height: bbox.height,
        fill: color.replace(')', ', 0.15)').replace('rgb', 'rgba'),
        stroke: color,
        strokeWidth: 2,
        selectable: true,
        hasControls: false,
        lockMovementX: true,
        lockMovementY: true,
        lockScalingX: true,
        lockScalingY: true,
        lockRotation: true,
        data: { index: i, sign: sign },
      } as any);

      fabricCanvas.add(rect);
      this.boundingBoxes.push(rect);
    }

    fabricCanvas.renderAll();
  }

  private fetchDetectionBoxes(dimensions: Dimensions[]): void {
    if (!this.canvas) return;
    const fabricCanvas = this.canvas.getCanvas();

    this.boundingBoxes.forEach(box => fabricCanvas.remove(box));
    this.boundingBoxes = [];
    if (this.selectedBox) {
      fabricCanvas.remove(this.selectedBox);
    }

    const ox = this.cropOffset ? this.cropOffset.x : 0;
    const oy = this.cropOffset ? this.cropOffset.y : 0;

    for (let i = 0; i < dimensions.length; i++) {
      const dim = dimensions[i];
      const rect = new fabric.Rect({
        left: dim.x + ox,
        top: dim.y + oy,
        width: dim.width,
        height: dim.height,
        fill: 'rgba(33, 150, 243, 0.1)',
        stroke: '#2196F3',
        strokeWidth: 1,
        selectable: true,
        hasControls: false,
        lockMovementX: true,
        lockMovementY: true,
        lockScalingX: true,
        lockScalingY: true,
        lockRotation: true,
        data: { index: i },
      } as any);

      fabricCanvas.add(rect);
      this.boundingBoxes.push(rect);
    }

    fabricCanvas.renderAll();
  }

  /**
   * Group signs by line number, sorted by position.
   */
  private groupSignsByLine(signs: CuReSignResult[]): [number, CuReSignResult[]][] {
    const lineMap = new Map<number, CuReSignResult[]>();
    for (const sign of signs) {
      if (!lineMap.has(sign.line)) {
        lineMap.set(sign.line, []);
      }
      lineMap.get(sign.line).push(sign);
    }
    const sorted = Array.from(lineMap.entries()).sort((a, b) => a[0] - b[0]);
    for (const [, arr] of sorted) {
      arr.sort((a, b) => a.position - b.position);
    }
    return sorted;
  }

  /**
   * Build Letter[] lines with transliteration names for the ACE editor.
   * Each line contains space-separated sign reading names.
   */
  private buildTransliterationLines(signs: CuReSignResult[]): Letter[] {
    const grouped = this.groupSignsByLine(signs);
    return grouped.map(([, lineSignsArr], row) => {
      const text = lineSignsArr.map(s => {
        return s.unicode ? s.unicode.split(' / ')[0] : s.label;
      }).join(' ');
      const letter = new Letter(text);
      letter.index = new Index(row, 0);
      return letter;
    });
  }

  /**
   * Build cuneiform HTML for the preview pane (Assurbanipal font).
   * ACE Editor can't render SMP Unicode (U+12000+), so cuneiform goes here.
   */
  private buildCuneiformHtml(signs: CuReSignResult[]): string {
    if (!signs || signs.length === 0) return '';

    const grouped = this.groupSignsByLine(signs);

    let html = '<div style="padding: 4px 8px;">';

    for (const [lineNum, lineSignsArr] of grouped) {
      html += `<div style="margin-bottom: 4px; display: flex; align-items: baseline; gap: 6px;">`;
      html += `<span style="color:#888; font-size:11px; flex-shrink:0;">${lineNum + 1}.</span>`;

      // Cuneiform signs
      html += `<span style="font-family:'Assurbanipal','Noto Sans Cuneiform',serif; font-size:16px; line-height:1.3; letter-spacing:1px;">`;
      html += lineSignsArr.map(s => {
        const conf = s.confidence;
        let color = '#333';
        if (conf < 0.7) color = '#f44336';
        else if (conf < 0.9) color = '#ff9800';
        const name = s.unicode ? s.unicode.split(' / ')[0] : '';
        return `<span style="color:${color}" title="${name} (${(conf * 100).toFixed(1)}%)">${s.label}</span>`;
      }).join('');
      html += `</span>`;

      html += `</div>`;
    }

    html += '</div>';
    return html;
  }

  private getConfidenceColor(confidence: number): string {
    if (confidence >= 0.9) return 'rgb(76, 175, 80)';    // green
    if (confidence >= 0.7) return 'rgb(255, 193, 7)';     // amber
    return 'rgb(244, 67, 54)';                             // red
  }

  // ==========================================
  // Sign selection / interaction
  // ==========================================

  onSignBoxSelected(index: number): void {
    if (index < 0 || index >= this.signs.length) return;
    this.selectedSign = this.signs[index];
    this.selectedSignIndex = index;

    // Highlight corresponding line in editor
    if (this.lineEditor && this.selectedSign) {
      this.lineEditor.setNewSelectedLine(new Index(this.selectedSign.line, 0));
    }
  }

  onBoxSelectionChanged(index: number): void {
    // selectionChange emits the index of the selected rect in the canvas.
    // Our sign boxes store sign array index in data.index.
    if (index >= 0 && index < this.boundingBoxes.length) {
      const box = this.boundingBoxes[index];
      const signIndex = (box as any).data?.index;
      if (typeof signIndex === 'number') {
        this.onSignBoxSelected(signIndex);
      }
    }
  }

  clearSelection(): void {
    this.selectedSign = null;
    this.selectedSignIndex = -1;
  }

  // ==========================================
  // Training
  // ==========================================

  loadTrainingStatus(): void {
    this.cureService.getTrainingStatus().subscribe(
      status => this.trainingStatus = status,
      err => console.error('Failed to load training status', err)
    );
  }

  startTraining(): void {
    const params: any = {
      epochs: this.trainingEpochs,
      batch_size: this.trainingBatchSize,
      learning_rate: this.trainingLearningRate,
      patience: this.trainingPatience,
      device: this.trainingDevice,
    };
    if (this.trainingModelName.trim()) {
      params.model_name = this.trainingModelName.trim();
    }
    if (this.trainingBaseModel) {
      params.base_model = this.trainingBaseModel;
    }
    this.cureService.startTraining(params).subscribe(
      result => {
        this.isTraining = true;
        this.trainingRightTab = 'progress';
        this.notificationService.showSuccess(`Training started: ${result.model_name}`);
        this.pollTrainingProgress();
      },
      err => this.notificationService.showError('Failed to start training: ' + (err.error?.detail || err.message))
    );
  }

  cancelTraining(): void {
    this.cureService.cancelTraining().subscribe(
      () => {
        this.isTraining = false;
        if (this.trainingProgressInterval) {
          clearInterval(this.trainingProgressInterval);
          this.trainingProgressInterval = null;
        }
        this.notificationService.showSuccess('Training cancelled');
      },
      err => this.notificationService.showError('Failed to cancel training')
    );
  }

  getTrainingStatusColor(status: string): string {
    switch (status) {
      case 'completed': return '#4caf50';
      case 'training': case 'preparing': return '#1976d2';
      case 'failed': return '#f44336';
      case 'cancelled': return '#ff9800';
      default: return '#666';
    }
  }

  private pollTrainingProgress(): void {
    if (this.trainingProgressInterval) {
      clearInterval(this.trainingProgressInterval);
    }
    this.trainingProgressInterval = setInterval(() => {
      this.cureService.getTrainingProgress().subscribe(progress => {
        this.trainingProgress = progress;
        if (progress.status === 'completed' || progress.status === 'failed' || progress.status === 'cancelled') {
          this.isTraining = false;
          clearInterval(this.trainingProgressInterval);
          this.trainingProgressInterval = null;
          this.loadTrainingStatus();
          this.loadActiveModel();
          if (progress.status === 'completed') {
            this.notificationService.showSuccess(`Training completed! Accuracy: ${(progress.best_accuracy * 100).toFixed(1)}%`);
          } else if (progress.status === 'failed') {
            this.notificationService.showError('Training failed: ' + progress.error);
          }
        }
      });
    }, 3000);
  }

  // ==========================================
  // Panel resizing
  // ==========================================

  startResize(event: MouseEvent | TouchEvent): void {
    event.preventDefault();
    this.isResizing = true;

    const container = (event.target as HTMLElement).closest('.split-container') as HTMLElement;
    if (!container) return;

    const containerRect = container.getBoundingClientRect();

    this.resizeHandler = (e: MouseEvent | TouchEvent) => {
      if (!this.isResizing) return;
      const clientX = e instanceof MouseEvent ? e.clientX : e.touches[0].clientX;
      const newWidth = ((clientX - containerRect.left) / containerRect.width) * 100;
      this.leftPanelWidth = Math.max(20, Math.min(80, newWidth));
    };

    this.resizeEndHandler = () => {
      this.isResizing = false;
      document.removeEventListener('mousemove', this.resizeHandler);
      document.removeEventListener('mouseup', this.resizeEndHandler);
      document.removeEventListener('touchmove', this.resizeHandler);
      document.removeEventListener('touchend', this.resizeEndHandler);

      if (this.canvas) {
        setTimeout(() => this.canvas.forceZoomOut(1), 100);
      }
    };

    document.addEventListener('mousemove', this.resizeHandler);
    document.addEventListener('mouseup', this.resizeEndHandler);
    document.addEventListener('touchmove', this.resizeHandler);
    document.addEventListener('touchend', this.resizeEndHandler);
  }

  // ==========================================
  // Navigation
  // ==========================================

  goBack(): void {
    if (this.stage === 3) {
      this.stage = 2;
      this.signs = [];
      this.selectedSign = null;
      this.selectedSignIndex = -1;
      this.cropOffset = null;
      if (this.canvas) {
        const fabricCanvas = this.canvas.getCanvas();
        this.boundingBoxes.forEach(box => fabricCanvas.remove(box));
        this.boundingBoxes = [];
        fabricCanvas.renderAll();
      }
    } else if (this.stage === 2) {
      this.stage = 0;
      this.backgroundImage = null;
      this.selectedBox = null;
      this.cropOffset = null;
    } else if (this.stage === 1) {
      this.stage = 0;
      this.pdfSrc = null;
      this.pdfFile = null;
    }
  }

  // ==========================================
  // Save & Curate
  // ==========================================

  openSaveDialog(): void {
    if (!this.signs || this.signs.length === 0) {
      this.notificationService.showWarning('No signs to save');
      return;
    }

    const dialogRef = this.dialog.open(SaveDialogComponent, {
      data: {
        textId: this.textId,
        existingLabels: this.existingLabels,
        existingParts: [],
        currentLabel: this.currentLabel,
        currentPart: this.currentPart
      }
    });

    dialogRef.afterClosed().subscribe((result: SaveDialogResult | null) => {
      if (!result) return;

      this.isSaving = true;
      const { museumNumber, pNumber, publicationNumber, label, part } = result;
      this.currentLabel = label;
      this.currentPart = part;

      if (this.textId != null) {
        this.doSave(label, part);
        return;
      }

      // Parse "name-number" identifiers (e.g. "BM-12345")
      const parseId = (value: string) => {
        if (!value) return null;
        const idx = value.lastIndexOf('-');
        if (idx > 0) {
          const name = value.substring(0, idx);
          const num = parseInt(value.substring(idx + 1), 10);
          if (!isNaN(num)) return { name, number: num };
        }
        const num = parseInt(value, 10);
        if (!isNaN(num)) return { name: '', number: num };
        return { name: value, number: 0 };
      };

      const identifiers = {
        museum: parseId(museumNumber),
        publication: parseId(publicationNumber),
        p_number: parseId(pNumber)
      };

      const hasValid =
        (identifiers.museum?.number > 0) ||
        (identifiers.publication?.number > 0) ||
        (identifiers.p_number?.number > 0);

      if (hasValid) {
        this.textService.getTextIdByIdentifiers(identifiers as any).subscribe(
          existingId => {
            if (existingId && existingId !== -1) {
              this.textId = existingId;
              this.doSave(label, part);
            } else {
              this.createTextAndSave(identifiers, label, part);
            }
          },
          () => this.createTextAndSave(identifiers, label, part)
        );
      } else {
        this.createTextAndSave(identifiers, label, part);
      }
    });
  }

  private createTextAndSave(identifiers: any, label: string, part: string): void {
    const datasetId = this.selectedDataset?.dataset_id || null;
    this.textService.create(identifiers, [], datasetId).subscribe(
      textId => {
        this.textId = textId;
        this.doSave(label, part);
      },
      () => {
        this.notificationService.showError('Failed to create text');
        this.isSaving = false;
      }
    );
  }

  private doSave(label: string, part: string, curate: boolean = false): void {
    if (this.transliterationId == null && this.uploadedImageBlob) {
      this.curedService.saveImage(this.uploadedImageBlob, this.textId).subscribe(
        imageName => this.createSubmission(imageName, label, part, curate),
        () => {
          this.notificationService.showError('Failed to upload image');
          this.isSaving = false;
        }
      );
    } else {
      this.createSubmission(null, label, part, curate);
    }
  }

  private createSubmission(imageName: string, label: string, part: string, curate: boolean): void {
    const lineTexts = this.lines.map(line => line.letter);

    // Build line-level dimensions from sign bounding boxes
    const dimensions = this.signs.map(s => new Dimensions(
      s.bbox.x, s.bbox.y, s.bbox.height, s.bbox.width
    ));

    const isCurated = curate || this.isCuratedCure;

    this.curedService.createSubmission(
      this.textId, this.transliterationId, lineTexts, dimensions, imageName, isCurated, false
    ).subscribe(
      result => {
        this.transliterationId = result;
        this.isCuratedCure = isCurated;
        this.isSaving = false;
        this.notificationService.showSuccess('Saved successfully');

        // Update label/part metadata
        if (label && this.textId) {
          this.textService.updateLabel(this.textId, label).subscribe(() => {
            if (!this.existingLabels.includes(label)) {
              this.existingLabels.push(label);
              this.existingLabels.sort();
            }
          }, () => {});
        }
        if (part && this.textId) {
          this.textService.updatePart(this.textId, part).subscribe(() => {}, () => {});
        }

        // Also save sign crops as training data
        this.saveTrainingCrops();
      },
      () => {
        this.notificationService.showError('Failed to save');
        this.isSaving = false;
      }
    );
  }

  private saveTrainingCrops(): void {
    const imageData = this.getImageForDetection();
    if (!imageData || !this.signs.length) return;

    const csvRows = ['x1,y1,x2,y2,label'];
    for (const sign of this.signs) {
      const b = sign.bbox;
      csvRows.push(`${b.x},${b.y},${b.x + b.width},${b.y + b.height},${sign.label}`);
    }

    const cropName = this.selectedDataset
      ? `${this.selectedDataset.name}_page${this.currentpage}`
      : `cure_${Date.now()}`;

    this.cureService.uploadAnnotations(imageData, csvRows.join('\n'), cropName).subscribe(
      () => {},
      () => {} // training crop save is best-effort
    );
  }

  curateCheck(): void {
    if (this.textId == null) {
      this.notificationService.showWarning('Please save first before curating');
      return;
    }
    this.isSaving = true;
    this.doSave(this.currentLabel, this.currentPart, true);
  }

  newOcr(): void {
    this.stage = 0;
    this.backgroundImage = null;
    this.pdfSrc = null;
    this.pdfFile = null;
    this.signs = [];
    this.lines = [];
    this.transliterationHtml = '';
    this.selectedSign = null;
    this.selectedSignIndex = -1;
    this.selectedBox = null;
    this.cropOffset = null;
    this.boundingBoxes = [];
    this.textId = null;
    this.transliterationId = null;
    this.currentLabel = '';
    this.currentPart = '';
    this.isCuratedCure = false;
  }
}
