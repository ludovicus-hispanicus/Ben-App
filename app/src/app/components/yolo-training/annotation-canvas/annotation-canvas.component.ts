import { Component, Input, Output, EventEmitter, OnInit, ViewChild, ElementRef, OnDestroy, HostListener, AfterViewInit } from '@angular/core';
import { fabric } from 'fabric';
import { PDFDocumentProxy } from 'ng2-pdf-viewer';

import { YoloTrainingService } from '../../../services/yolo-training.service';
import { CuredService } from '../../../services/cured.service';
import { NotificationService } from '../../../services/notification.service';
import { CanvasBoxService } from '../../../services/canvas-box.service';
import { YoloClass, YoloAnnotation, CLASS_COLORS, getClassColor } from '../../../models/yolo-training';
import { SelectedPdf } from '../../cure-d/cured.component';

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

  // UI state
  leftPanelCollapsed = false;
  rightPanelCollapsed = false; // Start expanded to show images
  rightPanelTab: 'images' | 'saved' | 'help' = 'images';

  // Saved images from dataset
  savedImages: Array<{
    image_id: string;
    filename: string;
    split: string;
    annotation_count: number;
    has_annotations: boolean;
  }> = [];
  savedImagesCount = 0;
  loadingSavedImages = false;
  viewingSavedImageId: string | null = null;
  viewingSavedImageSplit: string | null = null;

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
    private canvasBoxService: CanvasBoxService
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
  }

  @HostListener('window:keyup', ['$event'])
  onKeyUp(event: KeyboardEvent): void {
    if (event.code === 'Space') {
      this.spacePressed = false;
      this.isPanning = false;
      if (this.canvas) {
        // Keep grab cursor if pan mode is active
        this.canvas.defaultCursor = this.panModeActive ? 'grab' : 'crosshair';
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
      backgroundColor: '#2a2a2a',
      selection: false
    });

    // Mouse events for drawing
    this.canvas.on('mouse:down', (e) => this.onMouseDown(e));
    this.canvas.on('mouse:move', (e) => this.onMouseMove(e));
    this.canvas.on('mouse:up', (e) => this.onMouseUp(e));

    // Mouse wheel zoom
    this.canvas.on('mouse:wheel', (opt) => this.onMouseWheel(opt));

    // Selection events
    this.canvas.on('selection:created', (e) => this.onSelectionCreated(e));
    this.canvas.on('selection:updated', (e) => this.onSelectionCreated(e));
    this.canvas.on('selection:cleared', () => this.onSelectionCleared());

    // Object modified
    this.canvas.on('object:modified', (e) => this.onObjectModified(e));
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
      const color = getClassColor(saved.className);
      const rect = new fabric.Rect({
        left: rectLeft,
        top: rectTop,
        width: rectWidth,
        height: rectHeight,
        fill: color + '33',
        stroke: color,
        strokeWidth: 2,
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

  onMouseWheel(opt: fabric.IEvent): void {
    if (!this.canvas) return;

    const evt = opt.e as WheelEvent;
    evt.preventDefault();
    evt.stopPropagation();

    // Pinch-to-zoom on trackpad sends ctrlKey
    if (evt.ctrlKey || evt.metaKey) {
      // Zoom
      const delta = evt.deltaY;
      let zoom = this.canvas.getZoom();
      zoom *= 0.99 ** delta;
      if (zoom > this.maxZoom) zoom = this.maxZoom;
      if (zoom < this.minZoom) zoom = this.minZoom;
      this.canvas.zoomToPoint({ x: evt.offsetX, y: evt.offsetY }, zoom);
      this.zoomLevel = zoom;
      return;
    }

    // Detect trackpad vs mouse wheel:
    // - Trackpad two-finger scroll: deltaMode 0 (pixels), often has deltaX
    // - Mouse wheel: deltaMode 1 (lines) or deltaMode 0 with no deltaX
    const isTrackpadPan = evt.deltaMode === 0 && (Math.abs(evt.deltaX) > 0 || Math.abs(evt.deltaY) < 40);

    if (isTrackpadPan) {
      // Two-finger scroll on trackpad = pan
      const vpt = this.canvas.viewportTransform;
      if (vpt) {
        vpt[4] -= evt.deltaX;
        vpt[5] -= evt.deltaY;
        this.canvas.setViewportTransform(vpt);
      }
    } else {
      // Mouse wheel = zoom
      const delta = evt.deltaY;
      let zoom = this.canvas.getZoom();
      zoom *= 0.999 ** delta;
      if (zoom > this.maxZoom) zoom = this.maxZoom;
      if (zoom < this.minZoom) zoom = this.minZoom;
      this.canvas.zoomToPoint({ x: evt.offsetX, y: evt.offsetY }, zoom);
      this.zoomLevel = zoom;
    }
  }

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
      this.canvas.defaultCursor = this.panModeActive ? 'grab' : 'crosshair';
      this.canvas.renderAll();
    }
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

    const pointer = this.canvas.getPointer(e.e);

    // Check if clicking on existing object
    const target = this.canvas.findTarget(e.e as MouseEvent, false);
    if (target && target !== this.currentImage) {
      return; // Let fabric handle selection
    }

    // Start drawing new rectangle
    this.isDrawing = true;
    this.drawStart = { x: pointer.x, y: pointer.y };

    const color = getClassColor(this.getClassName(this.selectedClassId));
    this.tempRect = new fabric.Rect({
      left: pointer.x,
      top: pointer.y,
      width: 0,
      height: 0,
      fill: color + '33', // Semi-transparent
      stroke: color,
      strokeWidth: 2,
      selectable: false
    });

    this.canvas.add(this.tempRect);
  }

  onMouseMove(e: fabric.IEvent): void {
    if (!this.canvas) return;

    const evt = e.e as MouseEvent;

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
    if (!this.isDrawing || !this.drawStart || !this.tempRect) return;

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

    this.canvas.renderAll();
  }

  onMouseUp(e: fabric.IEvent): void {
    if (!this.canvas) return;

    // End panning
    if (this.isPanning) {
      this.isPanning = false;
      this.lastPanPosition = null;
      this.canvas.defaultCursor = (this.spacePressed || this.panModeActive) ? 'grab' : 'crosshair';
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
    const color = getClassColor(this.getClassName(this.selectedClassId));
    this.tempRect.set({
      selectable: true,
      fill: color + '33',
      stroke: color,
      strokeWidth: 2,
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
  }

  // ============== Selection ==============

  onSelectionCreated(e: fabric.IEvent): void {
    const selected = e.selected?.[0];
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
    // Object was moved or resized - annotations will be recalculated on save
    this.canvas?.renderAll();
  }

  // ============== Annotation Management ==============

  selectClass(classId: number): void {
    this.selectedClassId = classId;

    // Update selected annotation if any
    if (this.selectedAnnotation && this.canvas) {
      this.selectedAnnotation.classId = classId;
      this.selectedAnnotation.className = this.getClassName(classId);

      const color = getClassColor(this.selectedAnnotation.className);
      this.selectedAnnotation.fabricRect.set({
        fill: color + '33',
        stroke: color,
        cornerColor: color
      });
      this.canvas.renderAll();
    }
  }

  deleteSelected(): void {
    if (!this.selectedAnnotation || !this.canvas) return;

    const annotationId = this.selectedAnnotation.id;
    const fabricRect = this.selectedAnnotation.fabricRect;

    this.canvas.remove(fabricRect);
    this.annotations = this.annotations.filter(a => a.id !== annotationId);
    this.selectedAnnotation = null;
    this.canvas.renderAll();
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
    return getClassColor(className);
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

    this.isLoading = true;
    this.viewingSavedImageId = imageId;
    this.viewingSavedImageSplit = split;

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

        // Store dimensions
        this.imageWidth = response.image_width;
        this.imageHeight = response.image_height;

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
   * Update annotations for a saved image
   */
  updateSavedImageAnnotations(): void {
    if (!this.viewingSavedImageId || !this.datasetName) return;

    // Get current annotations in YOLO format
    const yoloAnnotations = this.convertToYoloFormat();

    if (yoloAnnotations.length === 0) {
      this.notification.showWarning('No annotations to save');
      return;
    }

    this.isLoading = true;

    // Find the split for this image
    const savedImage = this.savedImages.find(img => img.image_id === this.viewingSavedImageId);
    const split = savedImage?.split;

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
