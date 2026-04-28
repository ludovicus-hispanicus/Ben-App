import { Component, Input, Output, EventEmitter, OnInit, ViewChild, ElementRef, OnDestroy, HostListener, AfterViewInit } from '@angular/core';
import { fabric } from 'fabric';
import { PDFDocumentProxy } from 'ng2-pdf-viewer';

import { MatDialog } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';
import { YoloTrainingService } from '../../../services/yolo-training.service';
import { CuredService } from '../../../services/cured.service';
import { NotificationService } from '../../../services/notification.service';
import { CanvasBoxService } from '../../../services/canvas-box.service';
import { ImageBrowserDialogComponent } from '../../common/image-browser-dialog/image-browser-dialog.component';
import { SelectedPage } from '../../../models/pages';
import { YoloClass, YoloAnnotation, CLASS_COLORS, DEFAULT_COLOR_PALETTE, getClassColor } from '../../../models/yolo-training';
import { SelectedPdf } from '../../cure-d/cured.component';
import * as JSZip from 'jszip';

interface Snippet {
  dataUrl: string;
  className: string;
  classId: number;
  width: number;
  height: number;
}

interface AnnotationRect {
  id: string;
  fabricRect: fabric.Rect;
  classId: number;
  className: string;
}

interface SavedAnnotation {
  classId: number;
  className: string;
  // Normalized YOLO-like coordinates relative to image
  x_center: number;
  y_center: number;
  width: number;
  height: number;
}

interface QueuedImage {
  id: string;
  file: File;
  thumbnailUrl: string;
  annotated: boolean;
  annotationCount: number;
  savedAnnotations: SavedAnnotation[];
}

@Component({
  selector: 'app-annotation-canvas',
  templateUrl: './annotation-canvas.component.html',
  styleUrls: ['./annotation-canvas.component.scss']
})
export class AnnotationCanvasComponent implements OnInit, OnDestroy, AfterViewInit {
  @Input() datasetName: string = '';
  @Input() classes: YoloClass[] = [];

  @Output() saved = new EventEmitter<void>();
  @Output() cancelled = new EventEmitter<void>();

  @ViewChild('canvasContainer', { static: true }) canvasContainer!: ElementRef;
  @ViewChild('fileInput', { static: true }) fileInput!: ElementRef<HTMLInputElement>;

  canvas: fabric.Canvas | null = null;
  currentImage: fabric.Image | null = null;
  imageFile: File | null = null;
  imageWidth = 0;
  imageHeight = 0;

  annotations: AnnotationRect[] = [];
  selectedAnnotation: AnnotationRect | null = null;
  selectedClassId = 0;
  isDrawing = false;
  drawStart: { x: number; y: number } | null = null;
  tempRect: fabric.Rect | null = null;

  split: 'train' | 'val' = 'train';
  isLoading = false;
  canvasWidth = 800;
  canvasHeight = 600;

  classColors = CLASS_COLORS;

  // Add new class inline
  newClassName = '';
  newClassColor = '#FF6600';
  colorPalette = DEFAULT_COLOR_PALETTE;

  // Rename class inline
  editingClassId: number | null = null;

  // UI state
  leftPanelCollapsed = false;
  rightPanelCollapsed = false; // Start expanded to show images
  rightPanelTab: 'images' | 'saved' | 'help' | 'snippets' = 'images';
  rightPanelWidth = 380;
  private isResizingPanel = false;
  snippets: Snippet[] = [];

  // Saved images from dataset
  savedImages: Array<{
    image_id: string;
    filename: string;
    split: string;
    annotation_count: number;
    has_annotations: boolean;
    curated: boolean;
  }> = [];
  savedImagesCount = 0;
  loadingSavedImages = false;
  viewingSavedImageId: string | null = null;
  viewingSavedImageSplit: string | null = null;
  viewingSavedImageCurated = false;

  // Multi-select for saved images
  selectedImageIds: Set<string> = new Set();
  lastSelectedIndex: number = -1;
  deletingSelected = false;

  // Image queue for multi-image support
  imageQueue: QueuedImage[] = [];
  activeImageId: string | null = null;

  // Zoom and pan
  zoomLevel = 1;
  minZoom = 0.1;
  maxZoom = 5;
  isPanning = false;
  lastPanPosition: { x: number; y: number } | null = null;
  spacePressed = false;
  panModeActive = false; // Toggled pan mode (via toolbar button)
  drawModeActive = false; // When true, plain click draws boxes, Shift+click pans
  crosshairEnabled = true;
  private crosshairH: fabric.Line | null = null;
  private crosshairV: fabric.Line | null = null;
  private lastMouseScreenPos: { x: number; y: number } | null = null;

  // Auto-save
  private autoSaveTimer: any = null;

  // PDF handling
  selectedPdfPages: number[] = []; // For multi-page selection
  pdfSrc: Uint8Array | null = null;
  pdfFile: File | null = null;
  totalPages = 0;
  currentPage = 1;
  showPdfSelector = false;
  pageInputValue = 1;
  visiblePages: number[] = [];
  pagesPerSide = 5; // Show 5 pages before and after current

  constructor(
    private yoloService: YoloTrainingService,
    private curedService: CuredService,
    private notification: NotificationService,
    private canvasBoxService: CanvasBoxService,
    private dialog: MatDialog,
    private http: HttpClient
  ) {}

  ngOnInit(): void {
    if (this.classes.length > 0) {
      this.selectedClassId = this.classes[0].id;
    }
    // Load saved images list on init
    if (this.datasetName) {
      this.loadSavedImages();
    }
  }

  private resizeObserver: ResizeObserver | null = null;

  ngAfterViewInit(): void {
    // Use ResizeObserver to detect when container is properly sized
    this.resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          if (!this.canvas) {
            this.initCanvas();
          }
          this.resizeCanvas();
        }
      }
    });

    if (this.canvasContainer?.nativeElement) {
      this.resizeObserver.observe(this.canvasContainer.nativeElement);
    }

    // Fallback: also init after a delay in case ResizeObserver doesn't fire
    setTimeout(() => {
      if (!this.canvas) {
        this.initCanvas();
        this.resizeCanvas();
      }
    }, 200);
  }

  ngOnDestroy(): void {
    // Flush any pending auto-save before component is destroyed
    this.flushAutoSave();
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.canvas) {
      this.canvas.dispose();
    }
  }

  @HostListener('window:resize')
  onWindowResize(): void {
    this.resizeCanvas();
  }

  @HostListener('window:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    // Space for pan mode
    if (event.code === 'Space' && !this.spacePressed) {
      this.spacePressed = true;
      if (this.canvas) {
        this.canvas.defaultCursor = 'grab';
        this.canvas.renderAll();
      }
      event.preventDefault();
    }
    // Delete key to remove selected annotation
    if (event.key === 'Delete' || event.key === 'Backspace') {
      if (this.selectedAnnotation) {
        this.deleteSelected();
        event.preventDefault();
      }
    }
    // Number keys 1-4 to select class
    if (event.key >= '1' && event.key <= '4') {
      const classIndex = parseInt(event.key) - 1;
      if (this.classes[classIndex]) {
        this.selectClass(this.classes[classIndex].id);
      }
    }
    // Escape to deselect
    if (event.key === 'Escape') {
      if (this.canvas) {
        this.canvas.discardActiveObject();
        this.canvas.renderAll();
      }
      this.selectedAnnotation = null;
    }
    // D to toggle draw mode
    if (event.key === 'd' || event.key === 'D') {
      this.toggleDrawMode();
    }
    // Zoom with + and -
    if (event.key === '+' || event.key === '=') {
      this.zoomIn();
      event.preventDefault();
    }
    if (event.key === '-' || event.key === '_') {
      this.zoomOut();
      event.preventDefault();
    }
    // Reset zoom with 0
    if (event.key === '0') {
      this.resetZoom();
      event.preventDefault();
    }
    // Ctrl+S to save/update
    if ((event.ctrlKey || event.metaKey) && event.key === 's') {
      event.preventDefault();
      if (this.viewingSavedImageId && this.annotations.length > 0) {
        this.updateSavedImageAnnotations();
      } else if (this.imageFile) {
        this.saveAnnotations();
      }
    }
    // Ctrl+Shift+C to toggle curated
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && (event.key === 'c' || event.key === 'C')) {
      event.preventDefault();
      if (this.viewingSavedImageId) {
        this.toggleImageCurated();
      }
    }
  }

  @HostListener('window:keyup', ['$event'])
  onKeyUp(event: KeyboardEvent): void {
    if (event.code === 'Space') {
      this.spacePressed = false;
      this.isPanning = false;
      if (this.canvas) {
        // Keep grab cursor if pan mode is active
        this.canvas.defaultCursor = 'default';
        this.canvas.renderAll();
      }
    }
  }

  initCanvas(): void {
    const container = this.canvasContainer?.nativeElement;
    if (!container) return;

    this.canvasWidth = container.clientWidth || 800;
    this.canvasHeight = container.clientHeight || 600;

    this.canvas = new fabric.Canvas('annotationCanvas', {
      width: this.canvasWidth,
      height: this.canvasHeight,
      backgroundColor: '#e8e8e8',
      selection: false
    });

    // Mouse events for drawing
    this.canvas.on('mouse:down', (e) => this.onMouseDown(e));
    this.canvas.on('mouse:move', (e) => this.onMouseMove(e));
    this.canvas.on('mouse:up', (e) => this.onMouseUp(e));

    // Mouse wheel zoom/pan - use shared service for consistent behavior
    this.canvasBoxService.setupWheelZoomPan(this.canvas, {
      minZoom: this.minZoom,
      maxZoom: this.maxZoom,
      onZoomChange: (zoom) => { this.zoomLevel = zoom; this.updateCrosshairAfterViewportChange(); },
      onPan: () => this.updateCrosshairAfterViewportChange()
    });

    // Selection events
    this.canvas.on('selection:created', (e) => this.onSelectionCreated(e));
    this.canvas.on('selection:updated', (e) => this.onSelectionCreated(e));
    this.canvas.on('selection:cleared', () => this.onSelectionCleared());

    // Object modified
    this.canvas.on('object:modified', (e) => this.onObjectModified(e));

    // Hide crosshair when mouse leaves canvas
    this.canvas.on('mouse:out', () => this.hideCrosshair());

    // Create crosshair lines (initially hidden)
    this.crosshairH = new fabric.Line([0, 0, this.canvasWidth, 0], {
      stroke: 'rgba(25, 118, 210, 0.6)',
      strokeWidth: 1,
      strokeUniform: true,
      objectCaching: false,
      selectable: false,
      evented: false,
      excludeFromExport: true,
      visible: false
    });
    this.crosshairV = new fabric.Line([0, 0, 0, this.canvasHeight], {
      stroke: 'rgba(25, 118, 210, 0.6)',
      strokeWidth: 1,
      strokeUniform: true,
      objectCaching: false,
      selectable: false,
      evented: false,
      excludeFromExport: true,
      visible: false
    });
    this.canvas.add(this.crosshairH);
    this.canvas.add(this.crosshairV);
  }

  resizeCanvas(): void {
    if (!this.canvas || !this.canvasContainer) return;

    const container = this.canvasContainer.nativeElement;
    const newWidth = container.clientWidth;
    const newHeight = container.clientHeight;

    if (newWidth > 0 && newHeight > 0) {
      this.canvasWidth = newWidth;
      this.canvasHeight = newHeight;
      this.canvas.setWidth(newWidth);
      this.canvas.setHeight(newHeight);

      // Re-scale and center image if loaded
      if (this.currentImage) {
        const scale = Math.min(
          newWidth / this.imageWidth,
          newHeight / this.imageHeight
        ) * 0.95; // 95% to leave some margin

        this.currentImage.scale(scale);
        this.currentImage.set({
          left: (newWidth - this.imageWidth * scale) / 2,
          top: (newHeight - this.imageHeight * scale) / 2
        });

        // Re-position annotations relative to image
        this.repositionAnnotations(scale);
      }

      this.canvas.renderAll();
    }
  }

  repositionAnnotations(newScale: number): void {
    // Annotations are stored in canvas coordinates
    // When image is rescaled, we need to update annotation positions
    // For simplicity, we recalculate based on YOLO normalized format stored in annotations
  }

  // ============== File Handling ==============

  triggerFileInput(): void {
    this.fileInput.nativeElement.click();
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      // Process all selected files
      for (let i = 0; i < input.files.length; i++) {
        this.processFile(input.files[i]);
      }
    }
  }

  processFile(file: File): void {
    const fileName = file.name.toLowerCase();
    if (fileName.endsWith('.pdf')) {
      this.loadPdfFile(file);
    } else if (fileName.endsWith('.png') || fileName.endsWith('.jpg') || fileName.endsWith('.jpeg')) {
      this.addImageToQueue(file);
    } else {
      this.notification.showError('Unsupported file type. Please use PDF, PNG, or JPG.');
    }
  }

  browseServer(): void {
    const dialogRef = this.dialog.open(ImageBrowserDialogComponent, {
      width: '1000px', height: '720px'
    });
    dialogRef.afterClosed().subscribe((result: SelectedPage[] | null) => {
      if (!result || result.length === 0) return;
      for (const page of result) {
        this.http.get(page.image_url, { responseType: 'blob' }).subscribe(blob => {
          const file = new File([blob], page.filename, { type: 'image/png' });
          this.addImageToQueue(file);
        });
      }
    });
  }

  // ============== Image Queue Management ==============

  addImageToQueue(file: File): void {
    const reader = new FileReader();
    reader.onload = (e) => {
      const thumbnailUrl = e.target?.result as string;
      const queuedImage: QueuedImage = {
        id: this.generateId(),
        file: file,
        thumbnailUrl: thumbnailUrl,
        annotated: false,
        annotationCount: 0,
        savedAnnotations: []
      };
      this.imageQueue.push(queuedImage);

      // Auto-select if it's the first image or no image is currently active
      if (this.imageQueue.length === 1 || !this.activeImageId) {
        this.selectQueuedImage(queuedImage.id);
      }
    };
    reader.readAsDataURL(file);
  }

  selectQueuedImage(imageId: string): void {
    const queuedImage = this.imageQueue.find(img => img.id === imageId);
    if (!queuedImage) return;

    // Save current image's annotations before switching
    this.saveCurrentImageAnnotations();

    this.activeImageId = imageId;
    this.loadImageFromQueue(queuedImage);
  }

  /**
   * Save current annotations to the active queued image
   */
  saveCurrentImageAnnotations(): void {
    if (!this.activeImageId || !this.currentImage) return;

    const queuedImage = this.imageQueue.find(img => img.id === this.activeImageId);
    if (!queuedImage) return;

    // Don't overwrite existing saved annotations with empty array
    // This prevents losing annotations when quickly switching between images
    if (this.annotations.length === 0 && queuedImage.savedAnnotations.length > 0) {
      return;
    }

    const scale = this.currentImage.scaleX || 1;
    const imageLeft = this.currentImage.left || 0;
    const imageTop = this.currentImage.top || 0;

    // Convert current annotations to normalized format
    queuedImage.savedAnnotations = this.annotations.map(annotation => {
      const rect = annotation.fabricRect;

      // Get rectangle bounds in canvas coordinates
      const rectLeft = rect.left || 0;
      const rectTop = rect.top || 0;
      const rectWidth = (rect.width || 0) * (rect.scaleX || 1);
      const rectHeight = (rect.height || 0) * (rect.scaleY || 1);

      // Convert to original image coordinates (accounting for image offset)
      const imgLeft = (rectLeft - imageLeft) / scale;
      const imgTop = (rectTop - imageTop) / scale;
      const imgWidth = rectWidth / scale;
      const imgHeight = rectHeight / scale;

      // Convert to normalized format
      return {
        classId: annotation.classId,
        className: annotation.className,
        x_center: (imgLeft + imgWidth / 2) / this.imageWidth,
        y_center: (imgTop + imgHeight / 2) / this.imageHeight,
        width: imgWidth / this.imageWidth,
        height: imgHeight / this.imageHeight
      };
    });

    queuedImage.annotationCount = this.annotations.length;
    queuedImage.annotated = this.annotations.length > 0;
  }

  loadImageFromQueue(queuedImage: QueuedImage): void {
    // Flush any pending auto-save for the current image before switching
    this.flushAutoSave();

    this.imageFile = queuedImage.file;
    this.clearAnnotations();

    // Clear viewing saved image state when loading from queue
    this.viewingSavedImageId = null;
    this.viewingSavedImageSplit = null;

    // Ensure canvas dimensions are current before loading
    this.resizeCanvas();

    fabric.Image.fromURL(queuedImage.thumbnailUrl, (img) => {
      if (!this.canvas) return;

      // Store original dimensions
      this.imageWidth = img.width || 0;
      this.imageHeight = img.height || 0;

      // Scale image to fit canvas with margin
      const scale = Math.min(
        this.canvasWidth / this.imageWidth,
        this.canvasHeight / this.imageHeight
      ) * 0.95;

      img.scale(scale);

      // Center the image
      const scaledWidth = this.imageWidth * scale;
      const scaledHeight = this.imageHeight * scale;
      const imageLeft = (this.canvasWidth - scaledWidth) / 2;
      const imageTop = (this.canvasHeight - scaledHeight) / 2;

      img.set({
        left: imageLeft,
        top: imageTop,
        selectable: false,
        evented: false
      });

      // Remove old image
      if (this.currentImage) {
        this.canvas.remove(this.currentImage);
      }

      this.currentImage = img;
      this.canvas.add(img);
      this.canvas.sendToBack(img);

      // Restore saved annotations for this image
      this.restoreAnnotations(queuedImage.savedAnnotations, scale, imageLeft, imageTop);

      this.canvas.renderAll();
    });
  }

  /**
   * Restore annotations from saved normalized coordinates
   */
  restoreAnnotations(
    savedAnnotations: SavedAnnotation[],
    scale: number,
    imageLeft: number,
    imageTop: number
  ): void {
    if (!this.canvas || savedAnnotations.length === 0) return;

    for (const saved of savedAnnotations) {
      // Convert from normalized YOLO format back to canvas coordinates
      const imgWidth = saved.width * this.imageWidth;
      const imgHeight = saved.height * this.imageHeight;
      const imgLeft = (saved.x_center * this.imageWidth) - (imgWidth / 2);
      const imgTop = (saved.y_center * this.imageHeight) - (imgHeight / 2);

      // Convert to canvas coordinates
      const rectLeft = (imgLeft * scale) + imageLeft;
      const rectTop = (imgTop * scale) + imageTop;
      const rectWidth = imgWidth * scale;
      const rectHeight = imgHeight * scale;

      // Create the rectangle
      const color = getClassColor(saved.className, this.classes);
      const rect = new fabric.Rect({
        left: rectLeft,
        top: rectTop,
        width: rectWidth,
        height: rectHeight,
        fill: color + '33',
        stroke: color,
        strokeWidth: 2,
        strokeUniform: true,
        noScaleCache: false,
        objectCaching: false,
        selectable: true,
        cornerColor: color,
        cornerStyle: 'circle',
        transparentCorners: false
      });

      const annotation: AnnotationRect = {
        id: this.generateId(),
        fabricRect: rect,
        classId: saved.classId,
        className: saved.className
      };

      this.annotations.push(annotation);
      this.canvas.add(rect);
    }
  }

  removeFromQueue(imageId: string, event: Event): void {
    event.stopPropagation();
    this.imageQueue = this.imageQueue.filter(img => img.id !== imageId);

    // If we removed the active image, select another one
    if (this.activeImageId === imageId) {
      if (this.imageQueue.length > 0) {
        this.selectQueuedImage(this.imageQueue[0].id);
      } else {
        this.activeImageId = null;
        this.clearForNextImage();
      }
    }
  }

  markCurrentAsAnnotated(): void {
    if (!this.activeImageId) return;
    const queuedImage = this.imageQueue.find(img => img.id === this.activeImageId);
    if (queuedImage) {
      queuedImage.annotated = true;
      queuedImage.annotationCount = this.annotations.length;
    }
  }

  goToNextImage(): void {
    if (this.imageQueue.length === 0) return;

    const currentIndex = this.imageQueue.findIndex(img => img.id === this.activeImageId);
    const nextIndex = (currentIndex + 1) % this.imageQueue.length;
    this.selectQueuedImage(this.imageQueue[nextIndex].id);
  }

  // ============== PDF Handling ==============

  loadPdfFile(file: File): void {
    this.pdfFile = file;
    this.isLoading = true;
    this.totalPages = 0;
    this.visiblePages = [];
    this.currentPage = 1;
    this.pageInputValue = 1;
    this.selectedPdfPages = []; // Clear selection

    const fileReader = new FileReader();
    fileReader.addEventListener('load', () => {
      this.pdfSrc = new Uint8Array(fileReader.result as ArrayBuffer);
      this.showPdfSelector = true;
      this.isLoading = false;
    });
    fileReader.readAsArrayBuffer(file);
  }

  onPdfLoadComplete(pdf: PDFDocumentProxy): void {
    this.totalPages = pdf.numPages;
    this.updateVisiblePages();
  }

  updateVisiblePages(): void {
    const start = Math.max(1, this.currentPage - this.pagesPerSide);
    const end = Math.min(this.totalPages, this.currentPage + this.pagesPerSide);
    this.visiblePages = [];
    for (let i = start; i <= end; i++) {
      this.visiblePages.push(i);
    }
  }

  goToPage(): void {
    const page = Math.max(1, Math.min(this.totalPages, this.pageInputValue));
    this.currentPage = page;
    this.pageInputValue = page;
    this.updateVisiblePages();
  }

  navigatePages(direction: number): void {
    const newPage = this.currentPage + (direction * this.pagesPerSide);
    this.currentPage = Math.max(1, Math.min(this.totalPages, newPage));
    this.pageInputValue = this.currentPage;
    this.updateVisiblePages();
  }

  togglePdfPageSelection(page: number): void {
    const index = this.selectedPdfPages.indexOf(page);
    if (index > -1) {
      this.selectedPdfPages.splice(index, 1);
    } else {
      this.selectedPdfPages.push(page);
    }
    this.selectedPdfPages.sort((a, b) => a - b);
  }

  isPageSelected(page: number): boolean {
    return this.selectedPdfPages.includes(page);
  }

  loadSelectedPdfPages(): void {
    if (!this.pdfFile || this.selectedPdfPages.length === 0) {
      this.notification.showWarning('Please select at least one page');
      return;
    }

    this.isLoading = true;
    this.loadPdfPagesSequentially(0);
  }

  private loadPdfPagesSequentially(index: number): void {
    if (index >= this.selectedPdfPages.length) {
      // All pages loaded
      this.showPdfSelector = false;
      this.isLoading = false;
      this.notification.showSuccess(`${this.selectedPdfPages.length} pages loaded`);
      return;
    }

    const page = this.selectedPdfPages[index];
    const selectedPdf = new SelectedPdf(this.pdfFile!, page);

    this.curedService.convertPdf(selectedPdf).subscribe({
      next: (blob: Blob) => {
        const imageFile = new File([blob], `${this.pdfFile!.name}_page${page}.png`, { type: 'image/png' });
        this.addImageToQueue(imageFile);
        // Load next page
        this.loadPdfPagesSequentially(index + 1);
      },
      error: (err) => {
        console.error('PDF conversion error:', err);
        this.notification.showError(`Failed to convert page ${page}`);
        // Continue with next page
        this.loadPdfPagesSequentially(index + 1);
      }
    });
  }

  // Quick select for single click (legacy behavior)
  selectPdfPageSingle(page: number): void {
    if (!this.pdfFile) return;

    this.isLoading = true;
    const selectedPdf = new SelectedPdf(this.pdfFile, page);

    this.curedService.convertPdf(selectedPdf).subscribe({
      next: (blob: Blob) => {
        const imageFile = new File([blob], `${this.pdfFile!.name}_page${page}.png`, { type: 'image/png' });
        this.showPdfSelector = false;
        this.addImageToQueue(imageFile);
        this.isLoading = false;
      },
      error: (err) => {
        console.error('PDF conversion error:', err);
        this.notification.showError('Failed to convert PDF page');
        this.isLoading = false;
      }
    });
  }

  closePdfSelector(): void {
    this.showPdfSelector = false;
    this.pdfSrc = null;
    this.pdfFile = null;
    this.totalPages = 0;
    this.visiblePages = [];
    this.selectedPdfPages = [];
  }


  // ============== Zoom and Pan ==============
  // Note: Mouse wheel zoom/pan is handled by canvasBoxService.setupWheelZoomPan()

  zoomIn(): void {
    if (!this.canvas) return;
    let zoom = this.canvas.getZoom() * 1.2;
    if (zoom > this.maxZoom) zoom = this.maxZoom;
    this.canvas.setZoom(zoom);
    this.zoomLevel = zoom;
  }

  zoomOut(): void {
    if (!this.canvas) return;
    let zoom = this.canvas.getZoom() / 1.2;
    if (zoom < this.minZoom) zoom = this.minZoom;
    this.canvas.setZoom(zoom);
    this.zoomLevel = zoom;
  }

  resetZoom(): void {
    if (!this.canvas) return;
    this.canvas.setZoom(1);
    this.zoomLevel = 1;
    // Reset viewport
    this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  }

  zoomToFit(): void {
    if (!this.canvas || !this.currentImage) return;
    const zoom = Math.min(
      this.canvasWidth / this.imageWidth,
      this.canvasHeight / this.imageHeight
    ) * 0.95;
    this.canvas.setZoom(zoom);
    this.zoomLevel = zoom;
    this.canvas.setViewportTransform([zoom, 0, 0, zoom, 0, 0]);
  }

  togglePanMode(): void {
    this.panModeActive = !this.panModeActive;
    if (this.canvas) {
      this.canvas.defaultCursor = 'default';
      this.canvas.renderAll();
    }
  }

  toggleDrawMode(): void {
    this.drawModeActive = !this.drawModeActive;
    if (this.canvas) {
      this.canvas.defaultCursor = this.drawModeActive ? 'crosshair' : 'default';
      this.canvas.renderAll();
    }
  }

  toggleCrosshair(): void {
    this.crosshairEnabled = !this.crosshairEnabled;
    if (!this.crosshairEnabled) {
      this.hideCrosshair();
    }
  }

  private hideCrosshair(): void {
    if (this.crosshairH) this.crosshairH.set({ visible: false });
    if (this.crosshairV) this.crosshairV.set({ visible: false });
    if (this.canvas) this.canvas.renderAll();
  }

  private updateCrosshairAfterViewportChange(): void {
    if (!this.crosshairEnabled || !this.canvas || !this.crosshairH || !this.crosshairV) return;
    if (!this.crosshairH.visible || !this.lastMouseScreenPos) return;

    // After viewport pan/zoom, recalculate canvas coordinates from the
    // last known screen mouse position so the crosshair stays under the cursor.
    const vpt = this.canvas.viewportTransform;
    if (!vpt) return;

    const zoom = this.canvas.getZoom();
    const canvasX = (this.lastMouseScreenPos.x - vpt[4]) / zoom;
    const canvasY = (this.lastMouseScreenPos.y - vpt[5]) / zoom;

    this.crosshairH.set({ x1: -5000, y1: canvasY, x2: 5000, y2: canvasY });
    this.crosshairV.set({ x1: canvasX, y1: -5000, x2: canvasX, y2: 5000 });
    this.crosshairH.bringToFront();
    this.crosshairV.bringToFront();
    this.canvas.renderAll();
  }

  // ============== Right Panel Resize ==============

  startResizeRightPanel(event: MouseEvent): void {
    event.preventDefault();
    this.isResizingPanel = true;
    const startX = event.clientX;
    const startWidth = this.rightPanelWidth;

    const onMouseMove = (e: MouseEvent) => {
      const delta = startX - e.clientX;
      this.rightPanelWidth = Math.max(250, Math.min(600, startWidth + delta));
    };

    const onMouseUp = () => {
      this.isResizingPanel = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      this.resizeCanvas();
    };

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }

  // ============== Drawing ==============

  onMouseDown(e: fabric.IEvent): void {
    if (!this.canvas || !this.currentImage) return;

    const evt = e.e as MouseEvent;

    // Middle mouse button, space + left click, or pan mode active for panning
    if (evt.button === 1 || (this.spacePressed && evt.button === 0) || (this.panModeActive && evt.button === 0)) {
      this.isPanning = true;
      this.lastPanPosition = { x: evt.clientX, y: evt.clientY };
      this.canvas.defaultCursor = 'grabbing';
      this.canvas.renderAll();
      return;
    }

    // Check if clicking on existing object
    const target = this.canvas.findTarget(e.e as MouseEvent, false);
    if (target && target !== this.currentImage) {
      return; // Let fabric handle selection
    }

    // Determine if this click should draw or pan based on drawModeActive:
    // - Draw mode OFF (default): Shift+click = draw, plain click = pan
    // - Draw mode ON: plain click = draw, Shift+click = pan
    const wantsDraw = this.drawModeActive ? !evt.shiftKey : evt.shiftKey;

    if (wantsDraw && evt.button === 0) {
      const pointer = this.canvas.getPointer(e.e);
      this.isDrawing = true;
      this.drawStart = { x: pointer.x, y: pointer.y };

      const color = getClassColor(this.getClassName(this.selectedClassId), this.classes);
      this.tempRect = new fabric.Rect({
        left: pointer.x,
        top: pointer.y,
        width: 0,
        height: 0,
        fill: color + '33', // Semi-transparent
        stroke: color,
        strokeWidth: 2,
        strokeUniform: true,
        noScaleCache: false,
        objectCaching: false,
        selectable: false
      });

      this.canvas.add(this.tempRect);
      return;
    }

    // Otherwise pan
    if (evt.button === 0) {
      this.isPanning = true;
      this.lastPanPosition = { x: evt.clientX, y: evt.clientY };
      this.canvas.defaultCursor = 'grabbing';
      this.canvas.renderAll();
    }
  }

  onMouseMove(e: fabric.IEvent): void {
    if (!this.canvas) return;

    const evt = e.e as MouseEvent;
    this.lastMouseScreenPos = { x: evt.offsetX, y: evt.offsetY };
    const needsCrosshair = this.crosshairEnabled && this.crosshairH && this.crosshairV;

    // Update crosshair position
    if (needsCrosshair) {
      const pointer = this.canvas.getPointer(e.e);
      this.crosshairH!.set({ x1: -5000, y1: pointer.y, x2: 5000, y2: pointer.y, visible: true });
      this.crosshairV!.set({ x1: pointer.x, y1: -5000, x2: pointer.x, y2: 5000, visible: true });
      this.crosshairH!.bringToFront();
      this.crosshairV!.bringToFront();
    }

    // Handle panning
    if (this.isPanning && this.lastPanPosition) {
      const vpt = this.canvas.viewportTransform;
      if (vpt) {
        vpt[4] += evt.clientX - this.lastPanPosition.x;
        vpt[5] += evt.clientY - this.lastPanPosition.y;
        this.canvas.setViewportTransform(vpt);
        this.lastPanPosition = { x: evt.clientX, y: evt.clientY };
      }
      return;
    }

    // Handle drawing
    if (this.isDrawing && this.drawStart && this.tempRect) {
      const pointer = this.canvas.getPointer(e.e);

      const left = Math.min(this.drawStart.x, pointer.x);
      const top = Math.min(this.drawStart.y, pointer.y);
      const width = Math.abs(pointer.x - this.drawStart.x);
      const height = Math.abs(pointer.y - this.drawStart.y);

      this.tempRect.set({
        left: left,
        top: top,
        width: width,
        height: height
      });
    }

    // Render if crosshair or drawing needs update
    if (needsCrosshair || this.isDrawing) {
      this.canvas.renderAll();
    }
  }

  onMouseUp(e: fabric.IEvent): void {
    if (!this.canvas) return;

    // End panning
    if (this.isPanning) {
      this.isPanning = false;
      this.lastPanPosition = null;
      this.canvas.defaultCursor = 'default';
      this.canvas.renderAll();
      return;
    }

    if (!this.isDrawing || !this.tempRect) return;

    this.isDrawing = false;

    // Check minimum size
    const width = this.tempRect.width || 0;
    const height = this.tempRect.height || 0;

    if (width < 10 || height < 10) {
      // Too small, remove it
      this.canvas.remove(this.tempRect);
      this.tempRect = null;
      this.drawStart = null;
      return;
    }

    // Finalize the rectangle
    const color = getClassColor(this.getClassName(this.selectedClassId), this.classes);
    this.tempRect.set({
      selectable: true,
      fill: color + '33',
      stroke: color,
      strokeWidth: 2,
      strokeUniform: true,
      noScaleCache: false,
      objectCaching: false,
      cornerColor: color,
      cornerStyle: 'circle',
      transparentCorners: false
    });

    const annotation: AnnotationRect = {
      id: this.generateId(),
      fabricRect: this.tempRect,
      classId: this.selectedClassId,
      className: this.getClassName(this.selectedClassId)
    };

    this.annotations.push(annotation);
    this.tempRect = null;
    this.drawStart = null;

    this.canvas.setActiveObject(annotation.fabricRect);
    this.selectedAnnotation = annotation;
    this.canvas.renderAll();
    this.scheduleAutoSave();
  }

  // ============== Selection ==============

  onSelectionCreated(e: fabric.IEvent): void {
    const selected = e.selected?.[0] || e.target;
    if (selected) {
      const annotation = this.annotations.find(a => a.fabricRect === selected);
      if (annotation) {
        this.selectedAnnotation = annotation;
        this.selectedClassId = annotation.classId;
      }
    }
  }

  onSelectionCleared(): void {
    this.selectedAnnotation = null;
  }

  onObjectModified(e: fabric.IEvent): void {
    // Normalize scale back to width/height after resize completes.
    const target = e.target;
    if (target && target.type === 'rect') {
      const newWidth = (target.width || 0) * (target.scaleX || 1);
      const newHeight = (target.height || 0) * (target.scaleY || 1);
      target.set({
        width: newWidth,
        height: newHeight,
        scaleX: 1,
        scaleY: 1
      });
      target.setCoords();
    }
    this.canvas?.renderAll();
    this.scheduleAutoSave();
  }

  // ============== Annotation Management ==============

  selectClass(classId: number): void {
    this.selectedClassId = classId;

    // Update selected annotation if any
    if (this.selectedAnnotation && this.canvas) {
      this.selectedAnnotation.classId = classId;
      this.selectedAnnotation.className = this.getClassName(classId);

      const color = getClassColor(this.selectedAnnotation.className, this.classes);
      this.selectedAnnotation.fabricRect.set({
        fill: color + '33',
        stroke: color,
        cornerColor: color
      });
      this.canvas.renderAll();
      this.scheduleAutoSave();
    }
  }

  onClassColorChange(cls: YoloClass, event: Event): void {
    const color = (event.target as HTMLInputElement).value;
    cls.color = color;

    // Update any existing annotations on canvas that use this class
    if (this.canvas) {
      for (const ann of this.annotations) {
        if (ann.classId === cls.id) {
          ann.fabricRect.set({
            fill: color + '33',
            stroke: color,
            cornerColor: color
          });
        }
      }
      this.canvas.renderAll();
    }

    // Persist to backend
    if (this.datasetName) {
      this.yoloService.updateClassColor(this.datasetName, cls.id, color).subscribe({
        error: () => {
          this.notification.showError('Failed to save color');
        }
      });
    }
  }

  startEditClassName(cls: YoloClass, event: Event): void {
    event.stopPropagation();
    this.editingClassId = cls.id;
    // Focus the input after Angular renders it
    setTimeout(() => {
      const input = document.querySelector('.class-name-input') as HTMLInputElement;
      if (input) {
        input.focus();
        input.select();
      }
    });
  }

  finishEditClassName(cls: YoloClass, event: Event): void {
    const newName = (event.target as HTMLInputElement).value.trim();
    this.editingClassId = null;

    if (!newName || newName === cls.name) return;

    // Check for duplicates locally
    if (this.classes.find(c => c.name === newName && c.id !== cls.id)) {
      this.notification.showWarning(`Class "${newName}" already exists`);
      return;
    }

    const oldName = cls.name;
    cls.name = newName;

    // Update annotations that reference this class
    for (const ann of this.annotations) {
      if (ann.classId === cls.id) {
        ann.className = newName;
      }
    }

    // Persist to backend
    if (this.datasetName) {
      this.yoloService.renameClass(this.datasetName, cls.id, newName).subscribe({
        next: (response) => {
          if (response.success) {
            this.classes = response.classes;
          }
        },
        error: () => {
          // Revert on failure
          cls.name = oldName;
          for (const ann of this.annotations) {
            if (ann.classId === cls.id) {
              ann.className = oldName;
            }
          }
          this.notification.showError('Failed to rename class');
        }
      });
    }
  }

  cancelEditClassName(): void {
    this.editingClassId = null;
  }

  addNewClass(): void {
    const name = this.newClassName.trim();
    if (!name) return;

    if (this.classes.find(c => c.name === name)) {
      this.notification.showWarning(`Class "${name}" already exists`);
      return;
    }

    if (!this.datasetName) {
      // No dataset — add locally only
      const newId = this.classes.length;
      this.classes.push({ id: newId, name, color: this.newClassColor });
      this.selectedClassId = newId;
      this.newClassName = '';
      this.newClassColor = DEFAULT_COLOR_PALETTE[(newId + 1) % DEFAULT_COLOR_PALETTE.length];
      return;
    }

    this.yoloService.addClassesToDataset(this.datasetName, [{ name, color: this.newClassColor }]).subscribe({
      next: (response) => {
        if (response.success) {
          this.classes = response.classes;
          const added = this.classes.find(c => c.name === name);
          if (added) {
            this.selectedClassId = added.id;
          }
          this.newClassName = '';
          this.newClassColor = DEFAULT_COLOR_PALETTE[this.classes.length % DEFAULT_COLOR_PALETTE.length];
          this.notification.showSuccess(`Class "${name}" added`);
        }
      },
      error: () => {
        this.notification.showError('Failed to add class');
      }
    });
  }

  deleteClass(cls: YoloClass, event: Event): void {
    event.stopPropagation();

    const annotationsWithClass = this.annotations.filter(a => a.classId === cls.id);
    const message = annotationsWithClass.length > 0
      ? `Delete class "${cls.name}"? This will also remove ${annotationsWithClass.length} annotation(s) using this class.`
      : `Delete class "${cls.name}"?`;

    if (!confirm(message)) return;

    if (!this.datasetName) {
      // No dataset — remove locally
      // Remove annotations with this class from canvas
      annotationsWithClass.forEach(ann => {
        if (ann.fabricRect && this.canvas) {
          this.canvas.remove(ann.fabricRect);
        }
      });
      this.annotations = this.annotations.filter(a => a.classId !== cls.id);
      this.classes = this.classes.filter(c => c.id !== cls.id);
      // Re-index classes
      this.classes.forEach((c, i) => c.id = i);
      // Re-map annotation classIds
      this.annotations.forEach(ann => {
        const newCls = this.classes.find(c => c.name === ann.className);
        if (newCls) ann.classId = newCls.id;
      });
      if (this.selectedClassId === cls.id) {
        this.selectedClassId = this.classes.length > 0 ? this.classes[0].id : null;
      }
      this.canvas?.renderAll();
      return;
    }

    this.yoloService.deleteClassFromDataset(this.datasetName, cls.id).subscribe({
      next: (response) => {
        if (response.success) {
          this.classes = response.classes;
          // Remove annotations with the deleted class from canvas
          annotationsWithClass.forEach(ann => {
            if (ann.fabricRect && this.canvas) {
              this.canvas.remove(ann.fabricRect);
            }
          });
          this.annotations = this.annotations.filter(a => a.className !== cls.name);
          // Re-map annotation classIds to new indices
          this.annotations.forEach(ann => {
            const newCls = this.classes.find(c => c.name === ann.className);
            if (newCls) ann.classId = newCls.id;
          });
          if (this.selectedClassId === cls.id) {
            this.selectedClassId = this.classes.length > 0 ? this.classes[0].id : null;
          }
          this.canvas?.renderAll();
          this.notification.showSuccess(`Class "${cls.name}" deleted`);
        }
      },
      error: () => {
        this.notification.showError('Failed to delete class');
      }
    });
  }

  deleteSelected(): void {
    if (!this.selectedAnnotation || !this.canvas) return;

    const annotationId = this.selectedAnnotation.id;
    const fabricRect = this.selectedAnnotation.fabricRect;

    this.canvas.remove(fabricRect);
    this.annotations = this.annotations.filter(a => a.id !== annotationId);
    this.selectedAnnotation = null;
    this.canvas.renderAll();
    this.scheduleAutoSave();
  }

  clearAnnotations(): void {
    if (!this.canvas) return;

    for (const annotation of this.annotations) {
      this.canvas.remove(annotation.fabricRect);
    }
    this.annotations = [];
    this.selectedAnnotation = null;
    this.canvas.renderAll();
  }

  // ============== Save ==============

  async saveAnnotations(): Promise<void> {
    if (!this.imageFile) {
      this.notification.showWarning('Please load an image first');
      return;
    }

    this.isLoading = true;

    try {
      // Convert image to base64
      const imageBase64 = await this.yoloService.fileToBase64(this.imageFile);

      // Convert annotations to YOLO format
      const yoloAnnotations = this.convertToYoloFormat();

      // Upload to backend
      const response = await this.yoloService.uploadImage(
        this.datasetName,
        imageBase64,
        this.imageFile.name,
        yoloAnnotations,
        this.split
      ).toPromise();

      if (response?.success) {
        this.notification.showSuccess(`Image saved with ${response.annotation_count} annotations`);
        this.markCurrentAsAnnotated();
        this.saved.emit();

        // Refresh the saved images list so the newly saved image appears
        this.loadSavedImages();

        // Remove the saved image from the queue (it's now in the dataset)
        if (this.activeImageId) {
          this.imageQueue = this.imageQueue.filter(img => img.id !== this.activeImageId);
        }

        // If there are more images in the queue, select the first one
        // Otherwise, just clear the canvas
        if (this.imageQueue.length > 0) {
          this.selectQueuedImage(this.imageQueue[0].id);
        } else {
          this.activeImageId = null;
          this.clearForNextImage();
        }
      } else {
        this.notification.showError(response?.message || 'Failed to save');
      }
    } catch (error) {
      console.error('Save error:', error);
      this.notification.showError('Failed to save annotation');
    } finally {
      this.isLoading = false;
    }
  }

  convertToYoloFormat(): YoloAnnotation[] {
    if (!this.currentImage) return [];

    const scale = this.currentImage.scaleX || 1;
    const imageLeft = this.currentImage.left || 0;
    const imageTop = this.currentImage.top || 0;

    return this.annotations.map(annotation => {
      const rect = annotation.fabricRect;

      // Get rectangle bounds in canvas coordinates
      const rectLeft = rect.left || 0;
      const rectTop = rect.top || 0;
      const rectWidth = (rect.width || 0) * (rect.scaleX || 1);
      const rectHeight = (rect.height || 0) * (rect.scaleY || 1);

      // Convert to original image coordinates (accounting for image offset)
      const imgLeft = (rectLeft - imageLeft) / scale;
      const imgTop = (rectTop - imageTop) / scale;
      const imgWidth = rectWidth / scale;
      const imgHeight = rectHeight / scale;

      // Convert to YOLO normalized format
      return {
        class_id: annotation.classId,
        x_center: (imgLeft + imgWidth / 2) / this.imageWidth,
        y_center: (imgTop + imgHeight / 2) / this.imageHeight,
        width: imgWidth / this.imageWidth,
        height: imgHeight / this.imageHeight
      };
    });
  }

  // ============== Crop Snippets ==============

  cropSnippets(): void {
    if (!this.currentImage || this.annotations.length === 0) return;

    const imgElement = (this.currentImage as any)._element as HTMLImageElement;
    if (!imgElement) {
      this.notification.showError('Cannot access image data');
      return;
    }

    const scale = this.currentImage.scaleX || 1;
    const imageLeft = this.currentImage.left || 0;
    const imageTop = this.currentImage.top || 0;

    this.snippets = [];

    for (const ann of this.annotations) {
      const rect = ann.fabricRect;
      const rectLeft = rect.left || 0;
      const rectTop = rect.top || 0;
      const rectWidth = (rect.width || 0) * (rect.scaleX || 1);
      const rectHeight = (rect.height || 0) * (rect.scaleY || 1);

      // Convert to original image pixel coordinates
      let pixelX = Math.round((rectLeft - imageLeft) / scale);
      let pixelY = Math.round((rectTop - imageTop) / scale);
      let pixelW = Math.round(rectWidth / scale);
      let pixelH = Math.round(rectHeight / scale);

      // Clamp to image bounds
      pixelX = Math.max(0, pixelX);
      pixelY = Math.max(0, pixelY);
      pixelW = Math.min(pixelW, this.imageWidth - pixelX);
      pixelH = Math.min(pixelH, this.imageHeight - pixelY);

      if (pixelW <= 0 || pixelH <= 0) continue;

      const offscreen = document.createElement('canvas');
      offscreen.width = pixelW;
      offscreen.height = pixelH;
      const ctx = offscreen.getContext('2d');
      if (!ctx) continue;

      ctx.drawImage(imgElement, pixelX, pixelY, pixelW, pixelH, 0, 0, pixelW, pixelH);

      this.snippets.push({
        dataUrl: offscreen.toDataURL('image/png'),
        className: ann.className,
        classId: ann.classId,
        width: pixelW,
        height: pixelH,
      });
    }

    this.rightPanelTab = 'snippets';
    this.rightPanelCollapsed = false;
  }

  downloadSnippet(snippet: Snippet, index: number): void {
    const link = document.createElement('a');
    link.href = snippet.dataUrl;
    link.download = `${snippet.className}_${index}.png`;
    link.click();
  }

  async downloadAllSnippets(): Promise<void> {
    if (this.snippets.length === 0) return;

    const zip = new JSZip();

    const classCounts: { [key: string]: number } = {};
    for (const snippet of this.snippets) {
      const count = classCounts[snippet.className] || 0;
      classCounts[snippet.className] = count + 1;

      // Convert data URL to blob
      const response = await fetch(snippet.dataUrl);
      const blob = await response.blob();

      zip.file(`${snippet.className}/${snippet.className}_${count}.png`, blob);
    }

    const zipBlob = await zip.generateAsync({ type: 'blob' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(zipBlob);
    link.download = `snippets_${this.datasetName || 'annotations'}_${new Date().toISOString().slice(0, 10)}.zip`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  clearForNextImage(): void {
    this.clearAnnotations();
    this.imageFile = null;
    if (this.currentImage && this.canvas) {
      this.canvas.remove(this.currentImage);
      this.currentImage = null;
    }
    // Reset file input
    if (this.fileInput) {
      this.fileInput.nativeElement.value = '';
    }
  }

  cancel(): void {
    this.cancelled.emit();
  }

  // ============== Helpers ==============

  getClassName(classId: number): string {
    const cls = this.classes.find(c => c.id === classId);
    return cls?.name || `class_${classId}`;
  }

  generateId(): string {
    return Math.random().toString(36).substring(2, 9);
  }

  getClassColor(className: string): string {
    return getClassColor(className, this.classes);
  }

  /**
   * Check if a saved image is currently being viewed (matches both ID and split)
   */
  isViewingSavedImage(imageId: string, split: string): boolean {
    return this.viewingSavedImageId === imageId && this.viewingSavedImageSplit === split;
  }

  get currentImageIndex(): number {
    return this.imageQueue.findIndex(img => img.id === this.activeImageId);
  }

  /**
   * Get total count of images that have annotations (either saved or current)
   */
  getTotalAnnotatedImages(): number {
    // First save current annotations to update the queue
    this.saveCurrentImageAnnotations();

    return this.imageQueue.filter(img => img.savedAnnotations.length > 0).length;
  }

  /**
   * Save all images that have annotations
   */
  async saveAllAnnotatedImages(): Promise<void> {
    // Save current annotations first
    this.saveCurrentImageAnnotations();

    const annotatedImages = this.imageQueue.filter(img => img.savedAnnotations.length > 0);

    if (annotatedImages.length === 0) {
      this.notification.showWarning('No images have annotations to save');
      return;
    }

    this.isLoading = true;
    let savedCount = 0;
    let errorCount = 0;

    for (const queuedImage of annotatedImages) {
      try {
        // Convert image to base64
        const imageBase64 = await this.yoloService.fileToBase64(queuedImage.file);

        // Convert saved annotations to YOLO format
        const yoloAnnotations = queuedImage.savedAnnotations.map(saved => ({
          class_id: saved.classId,
          x_center: saved.x_center,
          y_center: saved.y_center,
          width: saved.width,
          height: saved.height
        }));

        // Upload to backend
        const response = await this.yoloService.uploadImage(
          this.datasetName,
          imageBase64,
          queuedImage.file.name,
          yoloAnnotations,
          this.split
        ).toPromise();

        if (response?.success) {
          savedCount++;
          queuedImage.annotated = true;
        } else {
          errorCount++;
        }
      } catch (error) {
        console.error('Save error for image:', queuedImage.file.name, error);
        errorCount++;
      }
    }

    this.isLoading = false;

    if (errorCount === 0) {
      this.notification.showSuccess(`Saved ${savedCount} images successfully`);
      this.saved.emit();
      // Refresh saved images list
      this.loadSavedImages();
    } else {
      this.notification.showWarning(`Saved ${savedCount} images, ${errorCount} failed`);
    }
  }

  // ============== Saved Images (Dataset Browser) ==============

  /**
   * Load list of saved images from the dataset
   */
  loadSavedImages(): void {
    if (!this.datasetName) return;

    this.loadingSavedImages = true;
    this.yoloService.listDatasetImages(this.datasetName).subscribe({
      next: (response) => {
        this.savedImages = response.images || [];
        this.savedImagesCount = response.total || 0;
        this.loadingSavedImages = false;
      },
      error: (error) => {
        console.error('Failed to load saved images:', error);
        this.notification.showError('Failed to load saved images');
        this.loadingSavedImages = false;
      }
    });
  }

  /**
   * View a saved image from the dataset with its annotations
   */
  viewSavedImage(imageId: string, split: string): void {
    if (!this.datasetName) return;

    // Flush any pending auto-save for the current image before switching
    this.flushAutoSave();

    this.isLoading = true;
    this.viewingSavedImageId = imageId;
    this.viewingSavedImageSplit = split;
    this.viewingSavedImageCurated = false;

    // Ensure canvas dimensions are current before loading
    this.resizeCanvas();

    this.yoloService.getDatasetImage(this.datasetName, imageId, split).subscribe({
      next: (response) => {
        if (!response.success) {
          this.notification.showError('Failed to load image');
          this.isLoading = false;
          return;
        }

        // Clear current state
        this.clearAnnotations();
        this.activeImageId = null;
        this.imageFile = null;

        // Store dimensions and curated status
        this.imageWidth = response.image_width;
        this.imageHeight = response.image_height;
        this.viewingSavedImageCurated = response.curated || false;

        // Load image onto canvas
        const imageUrl = `data:image/png;base64,${response.image_base64}`;
        fabric.Image.fromURL(imageUrl, (img) => {
          if (!this.canvas) {
            this.isLoading = false;
            return;
          }

          // Calculate scale to fit canvas
          const scale = Math.min(
            this.canvasWidth / this.imageWidth,
            this.canvasHeight / this.imageHeight
          ) * 0.95;

          img.scale(scale);

          // Center the image
          const scaledWidth = this.imageWidth * scale;
          const scaledHeight = this.imageHeight * scale;
          const imageLeft = (this.canvasWidth - scaledWidth) / 2;
          const imageTop = (this.canvasHeight - scaledHeight) / 2;

          img.set({
            left: imageLeft,
            top: imageTop,
            selectable: false,
            evented: false
          });

          // Remove old image
          if (this.currentImage) {
            this.canvas.remove(this.currentImage);
          }

          this.currentImage = img;
          this.canvas.add(img);
          this.canvas.sendToBack(img);

          // Convert response annotations to SavedAnnotation format and restore them
          const savedAnnotations: SavedAnnotation[] = response.annotations.map(ann => ({
            classId: ann.class_id,
            className: ann.class_name,
            x_center: ann.x_center,
            y_center: ann.y_center,
            width: ann.width,
            height: ann.height
          }));

          this.restoreAnnotations(savedAnnotations, scale, imageLeft, imageTop);

          this.canvas.renderAll();
          this.isLoading = false;
        });
      },
      error: (error) => {
        console.error('Failed to load saved image:', error);
        this.notification.showError('Failed to load image');
        this.isLoading = false;
        this.viewingSavedImageId = null;
        this.viewingSavedImageSplit = null;
      }
    });
  }

  /**
   * Toggle curated status for the currently viewed saved image.
   */
  toggleImageCurated(): void {
    if (!this.viewingSavedImageId || !this.datasetName) return;

    const newValue = !this.viewingSavedImageCurated;
    this.yoloService.toggleImageCurated(this.datasetName, this.viewingSavedImageId, newValue).subscribe({
      next: () => {
        this.viewingSavedImageCurated = newValue;
        // Update in the saved images list too
        const img = this.savedImages.find(i => i.image_id === this.viewingSavedImageId);
        if (img) img.curated = newValue;
      },
      error: () => this.notification.showError('Failed to update curated status'),
    });
  }

  /**
   * Update annotations for a saved image (manual Ctrl+S)
   */
  updateSavedImageAnnotations(): void {
    if (!this.viewingSavedImageId || !this.datasetName) return;

    // Cancel any pending auto-save since we're saving now
    if (this.autoSaveTimer) {
      clearTimeout(this.autoSaveTimer);
      this.autoSaveTimer = null;
    }

    // Get current annotations in YOLO format
    const yoloAnnotations = this.convertToYoloFormat();

    if (yoloAnnotations.length === 0) {
      this.notification.showWarning('No annotations to save');
      return;
    }

    this.isLoading = true;

    // Use the stored split directly (set when image was loaded)
    const split = this.viewingSavedImageSplit;

    this.yoloService.updateImageAnnotations(
      this.datasetName,
      this.viewingSavedImageId,
      yoloAnnotations,
      split
    ).subscribe({
      next: (response) => {
        this.isLoading = false;
        if (response.success) {
          this.notification.showSuccess(`Updated ${response.annotation_count} annotations`);
          // Refresh the list to show updated counts
          this.loadSavedImages();
        } else {
          this.notification.showError(response.message || 'Failed to update annotations');
        }
      },
      error: (error) => {
        this.isLoading = false;
        console.error('Failed to update annotations:', error);
        this.notification.showError('Failed to update annotations');
      }
    });
  }

  /**
   * Flush any pending auto-save immediately.
   * Call this before switching images to avoid losing annotations.
   */
  private flushAutoSave(): void {
    if (!this.autoSaveTimer) return;

    clearTimeout(this.autoSaveTimer);
    this.autoSaveTimer = null;

    // Save current state if we have a valid context
    if (!this.viewingSavedImageId || !this.datasetName || this.annotations.length === 0) return;

    const yoloAnnotations = this.convertToYoloFormat();
    if (yoloAnnotations.length === 0) return;

    const split = this.viewingSavedImageSplit;

    this.yoloService.updateImageAnnotations(
      this.datasetName,
      this.viewingSavedImageId,
      yoloAnnotations,
      split
    ).subscribe({
      next: () => {},
      error: (error) => console.error('Auto-save flush failed:', error)
    });
  }

  /**
   * Debounced auto-save. Only fires for saved images being edited.
   * Waits 1.5s after last change to avoid spamming the server.
   */
  private scheduleAutoSave(): void {
    if (!this.viewingSavedImageId || !this.datasetName) return;
    if (this.autoSaveTimer) {
      clearTimeout(this.autoSaveTimer);
    }

    // Capture the current image context at schedule time
    const targetImageId = this.viewingSavedImageId;
    const targetSplit = this.viewingSavedImageSplit;

    this.autoSaveTimer = setTimeout(() => {
      this.autoSaveTimer = null;

      // Only save if we're still viewing the same image
      if (this.viewingSavedImageId !== targetImageId) return;
      if (this.annotations.length === 0) return;

      const yoloAnnotations = this.convertToYoloFormat();
      if (yoloAnnotations.length === 0) return;

      this.yoloService.updateImageAnnotations(
        this.datasetName,
        targetImageId,
        yoloAnnotations,
        targetSplit
      ).subscribe({
        next: () => {},
        error: (error) => {
          console.error('Auto-save failed:', error);
        }
      });
    }, 1500);
  }

  // ============== Multi-select for saved images ==============

  toggleImageSelection(imageId: string, index: number, event: MouseEvent): void {
    event.stopPropagation();

    if (event.shiftKey && this.lastSelectedIndex >= 0) {
      // Shift+click: range select
      const start = Math.min(this.lastSelectedIndex, index);
      const end = Math.max(this.lastSelectedIndex, index);
      for (let i = start; i <= end; i++) {
        this.selectedImageIds.add(this.savedImages[i].image_id);
      }
    } else if (event.ctrlKey || event.metaKey) {
      // Ctrl/Cmd+click: toggle single
      if (this.selectedImageIds.has(imageId)) {
        this.selectedImageIds.delete(imageId);
      } else {
        this.selectedImageIds.add(imageId);
      }
    } else {
      // Plain click on checkbox: toggle single
      if (this.selectedImageIds.has(imageId)) {
        this.selectedImageIds.delete(imageId);
      } else {
        this.selectedImageIds.add(imageId);
      }
    }
    this.lastSelectedIndex = index;
  }

  isImageSelected(imageId: string): boolean {
    return this.selectedImageIds.has(imageId);
  }

  get hasSelection(): boolean {
    return this.selectedImageIds.size > 0;
  }

  selectAllImages(): void {
    this.savedImages.forEach(img => this.selectedImageIds.add(img.image_id));
  }

  clearSelection(): void {
    this.selectedImageIds.clear();
    this.lastSelectedIndex = -1;
  }

  deleteSelectedImages(): void {
    const count = this.selectedImageIds.size;
    if (count === 0) return;

    if (!confirm(`Delete ${count} image${count > 1 ? 's' : ''} from the dataset? This cannot be undone.`)) {
      return;
    }

    this.deletingSelected = true;
    const ids = Array.from(this.selectedImageIds);
    let completed = 0;
    let errors = 0;

    ids.forEach(imageId => {
      this.yoloService.deleteDatasetImage(this.datasetName, imageId).subscribe({
        next: (response) => {
          completed++;
          if (!response.success) errors++;

          // If we're viewing a deleted image, clear the canvas
          if (this.viewingSavedImageId === imageId) {
            this.clearAnnotations();
            if (this.currentImage && this.canvas) {
              this.canvas.remove(this.currentImage);
              this.currentImage = null;
            }
            this.viewingSavedImageId = null;
            this.viewingSavedImageSplit = null;
          }

          if (completed === ids.length) {
            this.deletingSelected = false;
            this.selectedImageIds.clear();
            this.lastSelectedIndex = -1;
            this.loadSavedImages();
            if (errors > 0) {
              this.notification.showError(`Deleted ${completed - errors}/${count} images (${errors} failed)`);
            } else {
              this.notification.showSuccess(`Deleted ${count} image${count > 1 ? 's' : ''}`);
            }
          }
        },
        error: () => {
          completed++;
          errors++;
          if (completed === ids.length) {
            this.deletingSelected = false;
            this.selectedImageIds.clear();
            this.lastSelectedIndex = -1;
            this.loadSavedImages();
            this.notification.showError(`Deleted ${completed - errors}/${count} images (${errors} failed)`);
          }
        }
      });
    });
  }

  /**
   * Delete a saved image from the dataset
   */
  deleteSavedImage(imageId: string, event: Event): void {
    event.stopPropagation();

    if (!confirm(`Delete image "${imageId}" from the dataset? This cannot be undone.`)) {
      return;
    }

    this.yoloService.deleteDatasetImage(this.datasetName, imageId).subscribe({
      next: (response) => {
        if (response.success) {
          this.notification.showSuccess('Image deleted');
          // If we're viewing this image, clear the canvas
          if (this.viewingSavedImageId === imageId) {
            this.clearAnnotations();
            if (this.currentImage && this.canvas) {
              this.canvas.remove(this.currentImage);
              this.currentImage = null;
            }
            this.viewingSavedImageId = null;
            this.viewingSavedImageSplit = null;
          }
          this.selectedImageIds.delete(imageId);
          // Refresh the list
          this.loadSavedImages();
        } else {
          this.notification.showError(response.message || 'Failed to delete image');
        }
      },
      error: (error) => {
        console.error('Failed to delete image:', error);
        this.notification.showError('Failed to delete image');
      }
    });
  }
}
