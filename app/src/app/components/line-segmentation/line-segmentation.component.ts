import {
  Component, OnInit, OnDestroy, AfterViewInit,
  ViewChild, ElementRef, HostListener
} from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { DestitchService } from '../../services/destitch.service';

/**
 * A point along the highlighter stroke.
 * x, y are the center of the stroke at this sample.
 * halfHeight is half the stroke thickness at this point
 * (controlled by Ctrl+Wheel while drawing).
 */
interface StrokePoint {
  x: number;
  y: number;
  halfHeight: number;
}

/**
 * A single line annotation — the tapered polygon produced by one stroke.
 * `points` defines the center-line with varying height at each sample.
 * From this we derive the top/bottom polygon edges for rendering & export.
 */
export interface LineAnnotation {
  points: StrokePoint[];
  /** Polygon vertices (top edge left->right, then bottom edge right->left) */
  polygon: { x: number; y: number }[];
}

const LINE_COLORS = [
  'rgba(79,195,247,0.35)',  // blue
  'rgba(129,199,132,0.35)', // green
  'rgba(255,183,77,0.35)',  // orange
  'rgba(240,98,146,0.35)',  // pink
  'rgba(186,104,200,0.35)', // purple
  'rgba(255,241,118,0.35)', // yellow
  'rgba(77,208,225,0.35)',  // cyan
  'rgba(255,138,101,0.35)', // red-orange
];

const LINE_BORDER_COLORS = [
  'rgba(79,195,247,0.8)',
  'rgba(129,199,132,0.8)',
  'rgba(255,183,77,0.8)',
  'rgba(240,98,146,0.8)',
  'rgba(186,104,200,0.8)',
  'rgba(255,241,118,0.8)',
  'rgba(77,208,225,0.8)',
  'rgba(255,138,101,0.8)',
];

@Component({
  selector: 'app-line-segmentation',
  templateUrl: './line-segmentation.component.html',
  styleUrls: ['./line-segmentation.component.scss']
})
export class LineSegmentationComponent implements OnInit, OnDestroy, AfterViewInit {

  @ViewChild('segCanvas', { static: true }) canvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('canvasContainer', { static: true }) containerRef!: ElementRef<HTMLDivElement>;
  @ViewChild('fileInput', { static: true }) fileInput!: ElementRef<HTMLInputElement>;
  @ViewChild('splitContainer', { static: false }) splitContainerRef!: ElementRef<HTMLDivElement>;

  // -- State --
  imageLoaded = false;
  isLoading = false;
  // Pan is the default mode. Holding Shift temporarily activates the highlighter.
  drawModeActive = false;
  panModeActive = true;
  rightPanelCollapsed = false;
  rightPanelTab: 'tablets' | 'lines' = 'tablets';

  // Tablet data
  tablets: any[] = [];
  currentTablet: any = null;
  loadingTablets = false;
  showingLineart = true;
  transliterationLines: string[] = [];
  translationLines: string[] = [];

  // ACE editor text (pre-loaded from ORACC transliteration)
  editorText: string = '';

  private readonly API_BASE = environment.apiUrl + '/segmentation';

  zoomLevel = 1;
  panX = 0;
  panY = 0;

  strokeHeight = 20;
  private readonly MIN_STROKE_HEIGHT = 4;
  private readonly MAX_STROKE_HEIGHT = 200;
  private readonly STROKE_HEIGHT_STEP = 2;

  lineAnnotations: LineAnnotation[] = [];
  selectedLineIndex = -1;

  // -- Destitch (optional, manually triggered) --
  /** Crops returned by the destitcher, keyed by view ('obverse' | 'reverse'). */
  destitchedViews: { obverse?: string; reverse?: string } = {};
  /** Currently displayed view in the canvas. */
  currentView: 'original' | 'obverse' | 'reverse' = 'original';
  isDestitching = false;
  destitchError = '';
  /** Per-view annotations so the user can mark obverse and reverse separately. */
  private annotationsByView = new Map<'original' | 'obverse' | 'reverse', LineAnnotation[]>();

  // Split panel (CuReD-style resizable)
  leftPanelWidth = 50; // percentage
  private isResizing = false;
  private resizeHandler!: (e: MouseEvent | TouchEvent) => void;
  private resizeEndHandler!: () => void;

  // -- Internal --
  private ctx!: CanvasRenderingContext2D;
  private image: HTMLImageElement | null = null;
  private imageWidth = 0;
  private imageHeight = 0;

  // Drawing state
  private isDrawing = false;
  private currentStroke: StrokePoint[] = [];

  // Cursor position in image coordinates (null = pointer not over canvas)
  private cursorImg: { x: number; y: number } | null = null;

  // Panning state
  private isPanning = false;
  private panStart = { x: 0, y: 0 };
  private spaceHeld = false;
  /** True while Shift is held — temporarily activates the highlighter regardless of pan mode. */
  private shiftHeld = false;

  // Minimum distance between sampled points (image pixels)
  private readonly SAMPLE_DISTANCE = 3;

  constructor(
    private router: Router,
    private route: ActivatedRoute,
    private http: HttpClient,
    private destitch: DestitchService,
  ) {}

  ngOnInit(): void {
    this.loadTabletList();
    // If navigated here from Segmentation with ?p=Pxxxxxx, auto-load that tablet.
    const p = this.route.snapshot.queryParamMap.get('p');
    if (p) {
      this.loadTablet(p);
    }
  }

  ngAfterViewInit(): void {
    const canvas = this.canvasRef.nativeElement;
    this.ctx = canvas.getContext('2d')!;
    this.resizeCanvas();
  }

  ngOnDestroy(): void {
    // Clean up resize listeners
    if (this.resizeHandler) {
      document.removeEventListener('mousemove', this.resizeHandler);
      document.removeEventListener('touchmove', this.resizeHandler);
    }
    if (this.resizeEndHandler) {
      document.removeEventListener('mouseup', this.resizeEndHandler);
      document.removeEventListener('touchend', this.resizeEndHandler);
    }
  }

  // -- Split panel resizing (CuReD pattern) --

  startResize(event: MouseEvent | TouchEvent): void {
    event.preventDefault();
    this.isResizing = true;

    const container = this.splitContainerRef?.nativeElement;
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

      // Resize canvas to fit new panel width
      setTimeout(() => this.resizeCanvas(), 50);
    };

    document.addEventListener('mousemove', this.resizeHandler);
    document.addEventListener('mouseup', this.resizeEndHandler);
    document.addEventListener('touchmove', this.resizeHandler);
    document.addEventListener('touchend', this.resizeEndHandler);
  }

  // -- ACE editor integration --

  onEditorTextChanged(text: string): void {
    this.editorText = text;
    // Update transliteration lines from editor content
    this.transliterationLines = text.split('\n').filter(l => l.trim());
  }

  // -- File loading --

  triggerFileInput(): void {
    this.fileInput.nativeElement.click();
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files || input.files.length === 0) return;

    const file = input.files[0];
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        this.image = img;
        this.imageWidth = img.width;
        this.imageHeight = img.height;
        this.imageLoaded = true;
        this.lineAnnotations = [];
        this.selectedLineIndex = -1;
        this.resetZoom();
        this.fitImageToView();
        this.redraw();
      };
      img.src = e.target!.result as string;
    };
    reader.readAsDataURL(file);
    input.value = '';
  }

  // -- Zoom & Pan --

  zoomIn(): void { this.setZoom(this.zoomLevel * 1.2); }
  zoomOut(): void { this.setZoom(this.zoomLevel / 1.2); }

  resetZoom(): void {
    this.zoomLevel = 1;
    this.panX = 0;
    this.panY = 0;
    this.fitImageToView();
    this.redraw();
  }

  private setZoom(level: number): void {
    this.zoomLevel = Math.max(0.1, Math.min(10, level));
    this.redraw();
  }

  private fitImageToView(): void {
    if (!this.image) return;
    const container = this.containerRef.nativeElement;
    const scaleX = container.clientWidth / this.imageWidth;
    const scaleY = container.clientHeight / this.imageHeight;
    this.zoomLevel = Math.min(scaleX, scaleY) * 0.95;
    this.panX = (container.clientWidth - this.imageWidth * this.zoomLevel) / 2;
    this.panY = (container.clientHeight - this.imageHeight * this.zoomLevel) / 2;
  }

  // -- Mode toggles --

  toggleDrawMode(): void {
    this.drawModeActive = !this.drawModeActive;
    if (this.drawModeActive) this.panModeActive = false;
    this.updateCursor();
  }

  togglePanMode(): void {
    this.panModeActive = !this.panModeActive;
    if (this.panModeActive) this.drawModeActive = false;
    this.updateCursor();
  }

  private updateCursor(): void {
    const canvas = this.canvasRef.nativeElement;
    // Shift overrides pan/space to enter draw mode.
    if (this.shiftHeld || this.drawModeActive) {
      // Custom highlighter preview is drawn on the canvas — hide OS cursor.
      canvas.style.cursor = 'none';
    } else if (this.panModeActive || this.spaceHeld) {
      canvas.style.cursor = 'grab';
    } else {
      canvas.style.cursor = 'default';
    }
  }

  /** True when the highlighter is active — either toggled on or temporarily via Shift. */
  private get isHighlighterActive(): boolean {
    return this.drawModeActive || this.shiftHeld;
  }

  // -- Canvas resize --

  @HostListener('window:resize')
  onResize(): void { this.resizeCanvas(); }

  private resizeCanvas(): void {
    const container = this.containerRef.nativeElement;
    const canvas = this.canvasRef.nativeElement;
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;
    this.redraw();
  }

  // -- Coordinate conversion --

  private screenToImage(sx: number, sy: number): { x: number; y: number } {
    return {
      x: (sx - this.panX) / this.zoomLevel,
      y: (sy - this.panY) / this.zoomLevel,
    };
  }

  private imageToScreen(ix: number, iy: number): { x: number; y: number } {
    return {
      x: ix * this.zoomLevel + this.panX,
      y: iy * this.zoomLevel + this.panY,
    };
  }

  // -- Mouse / keyboard handlers --

  @HostListener('window:keydown', ['$event'])
  onKeyDown(e: KeyboardEvent): void {
    // Don't capture keys when ACE editor or other inputs are focused
    const tag = (e.target as HTMLElement).tagName;
    const isEditorFocused = (e.target as HTMLElement).closest('.ace_editor') !== null;
    if (isEditorFocused || tag === 'INPUT' || tag === 'TEXTAREA') return;

    if (e.key === 'Shift' && !this.shiftHeld) {
      this.shiftHeld = true;
      this.updateCursor();
      if (this.cursorImg) { this.redraw(); }
    }
    if (e.key === ' ') {
      e.preventDefault();
      this.spaceHeld = true;
      this.updateCursor();
    }
    if (e.key === 'd' || e.key === 'D') {
      this.toggleDrawMode();
    }
    if (e.key === 'Delete') this.deleteSelected();
    if (e.key === 'z' && e.ctrlKey) this.undoLastLine();
    if (e.key === '+' || e.key === '=') this.zoomIn();
    if (e.key === '-') this.zoomOut();
    if (e.key === '0') this.resetZoom();
  }

  @HostListener('window:keyup', ['$event'])
  onKeyUp(e: KeyboardEvent): void {
    if (e.key === 'Shift') {
      this.shiftHeld = false;
      this.updateCursor();
      if (this.cursorImg) { this.redraw(); }
    }
    if (e.key === ' ') {
      this.spaceHeld = false;
      this.updateCursor();
    }
  }

  @HostListener('mousedown', ['$event'])
  onMouseDown(e: MouseEvent): void {
    if (!this.imageLoaded) return;

    // Only handle events on the canvas
    const canvas = this.canvasRef.nativeElement;
    if (!canvas.contains(e.target as Node)) return;

    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    // Shift+click → draw, regardless of mode. Otherwise: pan/draw/select per mode.
    if (this.isHighlighterActive && e.button === 0) {
      const imgPt = this.screenToImage(sx, sy);
      this.isDrawing = true;
      this.currentStroke = [{
        x: imgPt.x,
        y: imgPt.y,
        halfHeight: this.strokeHeight / 2,
      }];
      this.selectedLineIndex = -1;
      this.redraw();
      return;
    }

    // Pan with space+click or middle mouse or pan mode
    if (this.spaceHeld || this.panModeActive || e.button === 1) {
      this.isPanning = true;
      this.panStart = { x: e.clientX - this.panX, y: e.clientY - this.panY };
      canvas.style.cursor = 'grabbing';
      e.preventDefault();
      return;
    }

    // Click to select existing line (no mode active)
    if (e.button === 0) {
      const imgPt = this.screenToImage(sx, sy);
      this.selectedLineIndex = this.findLineAt(imgPt.x, imgPt.y);
      this.redraw();
    }
  }

  @HostListener('mousemove', ['$event'])
  onMouseMove(e: MouseEvent): void {
    const canvas = this.canvasRef.nativeElement;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const overCanvas = sx >= 0 && sy >= 0 && sx <= rect.width && sy <= rect.height
                       && canvas.contains(e.target as Node);

    if (this.isPanning) {
      this.panX = e.clientX - this.panStart.x;
      this.panY = e.clientY - this.panStart.y;
      this.redraw();
      return;
    }

    if (this.isDrawing) {
      const imgPt = this.screenToImage(sx, sy);
      this.cursorImg = imgPt;
      const last = this.currentStroke[this.currentStroke.length - 1];
      const dist = Math.hypot(imgPt.x - last.x, imgPt.y - last.y);
      if (dist >= this.SAMPLE_DISTANCE) {
        this.currentStroke.push({
          x: imgPt.x,
          y: imgPt.y,
          halfHeight: this.strokeHeight / 2,
        });
      }
      this.redraw();
      return;
    }

    // Track cursor for the highlighter preview overlay.
    if (overCanvas && this.imageLoaded && this.isHighlighterActive) {
      this.cursorImg = this.screenToImage(sx, sy);
      this.redraw();
    } else if (this.cursorImg) {
      this.cursorImg = null;
      this.redraw();
    }
  }

  @HostListener('mouseleave', ['$event'])
  onCanvasMouseLeave(_e: MouseEvent): void {
    if (this.cursorImg) {
      this.cursorImg = null;
      this.redraw();
    }
  }

  @HostListener('mouseup', ['$event'])
  onMouseUp(e: MouseEvent): void {
    if (this.isPanning) {
      this.isPanning = false;
      this.updateCursor();
      return;
    }

    if (this.isDrawing) {
      this.isDrawing = false;
      if (this.currentStroke.length >= 2) {
        const annotation = this.buildAnnotation(this.currentStroke);
        this.lineAnnotations.push(annotation);
        this.selectedLineIndex = this.lineAnnotations.length - 1;
      }
      this.currentStroke = [];
      this.redraw();
    }
  }

  @HostListener('wheel', ['$event'])
  onWheel(e: WheelEvent): void {
    if (!this.imageLoaded) return;

    // Only handle wheel events on the canvas
    const canvas = this.canvasRef.nativeElement;
    if (!canvas.contains(e.target as Node)) return;

    // Ctrl+Wheel: adjust stroke height (centralised through setStrokeHeight
    // so the live preview redraws whether or not we're currently drawing).
    if (e.ctrlKey) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -this.STROKE_HEIGHT_STEP : this.STROKE_HEIGHT_STEP;
      this.setStrokeHeight(this.strokeHeight + delta);
      return;
    }

    // Regular wheel: zoom
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.max(0.1, Math.min(10, this.zoomLevel * factor));

    this.panX = mx - (mx - this.panX) * (newZoom / this.zoomLevel);
    this.panY = my - (my - this.panY) * (newZoom / this.zoomLevel);
    this.zoomLevel = newZoom;
    this.redraw();
  }

  // -- Annotation management --

  selectLine(index: number): void {
    this.selectedLineIndex = index;
    this.redraw();
  }

  deleteLine(index: number, event?: Event): void {
    event?.stopPropagation();
    this.lineAnnotations.splice(index, 1);
    if (this.selectedLineIndex >= this.lineAnnotations.length) {
      this.selectedLineIndex = this.lineAnnotations.length - 1;
    }
    this.redraw();
  }

  deleteSelected(): void {
    if (this.selectedLineIndex >= 0) {
      this.deleteLine(this.selectedLineIndex);
    }
  }

  undoLastLine(): void {
    if (this.lineAnnotations.length > 0) {
      this.lineAnnotations.pop();
      this.selectedLineIndex = Math.min(this.selectedLineIndex, this.lineAnnotations.length - 1);
      this.redraw();
    }
  }

  clearAllLines(): void {
    this.lineAnnotations = [];
    this.selectedLineIndex = -1;
    this.redraw();
  }

  getLineColor(index: number): string {
    return LINE_COLORS[index % LINE_COLORS.length];
  }

  goBack(): void {
    this.router.navigate(['/']);
  }

  saveAnnotations(): void {
    // TODO: wire to backend API
    console.log('Annotations:', JSON.stringify(this.lineAnnotations, null, 2));
  }

  // -- Highlighter size control --

  /** Step the highlighter height up by one STROKE_HEIGHT_STEP, clamped to MAX. */
  increaseStrokeHeight(): void {
    this.setStrokeHeight(this.strokeHeight + this.STROKE_HEIGHT_STEP);
  }

  /** Step the highlighter height down by one STROKE_HEIGHT_STEP, clamped to MIN. */
  decreaseStrokeHeight(): void {
    this.setStrokeHeight(this.strokeHeight - this.STROKE_HEIGHT_STEP);
  }

  /** Set the highlighter height to a specific value (clamped). Used by slider/input. */
  setStrokeHeight(px: number | string): void {
    const n = typeof px === 'string' ? parseInt(px, 10) : px;
    if (!Number.isFinite(n)) { return; }
    const next = Math.max(this.MIN_STROKE_HEIGHT,
      Math.min(this.MAX_STROKE_HEIGHT, Math.round(n)));
    if (next === this.strokeHeight) { return; }
    this.strokeHeight = next;
    if (this.isDrawing && this.currentStroke.length > 0) {
      this.currentStroke[this.currentStroke.length - 1].halfHeight = this.strokeHeight / 2;
    }
    // Live preview: redraw whenever drawing OR the cursor is over the canvas.
    if (this.isDrawing || this.cursorImg) {
      this.redraw();
    }
  }

  get canIncreaseStroke(): boolean { return this.strokeHeight < this.MAX_STROKE_HEIGHT; }
  get canDecreaseStroke(): boolean { return this.strokeHeight > this.MIN_STROKE_HEIGHT; }
  get strokeHeightMin(): number { return this.MIN_STROKE_HEIGHT; }
  get strokeHeightMax(): number { return this.MAX_STROKE_HEIGHT; }

  // -- Destitch (optional) --

  get hasDestitchedViews(): boolean {
    return !!(this.destitchedViews.obverse || this.destitchedViews.reverse);
  }

  /**
   * Send the currently displayed image to the destitcher and keep only the
   * obverse and reverse crops. Triggered from the toolbar — optional, since
   * many tablets are single-view and don't need splitting.
   */
  destitchCurrentImage(): void {
    if (!this.image || !this.imageWidth || !this.imageHeight) { return; }
    if (this.isDestitching) { return; }

    // Snapshot the current image as base64 (works whether the image came from
    // the API, a destitched view, or a local upload).
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = this.imageWidth;
    tempCanvas.height = this.imageHeight;
    const tctx = tempCanvas.getContext('2d');
    if (!tctx) { return; }
    tctx.drawImage(this.image, 0, 0);
    const dataUri = tempCanvas.toDataURL('image/jpeg', 0.92);
    const base64 = dataUri.split(',')[1];

    this.isDestitching = true;
    this.destitchError = '';
    this.destitch.split({ image: base64, include_crops: true }).subscribe({
      next: (result) => {
        this.isDestitching = false;
        if (result.error) {
          this.destitchError = result.error;
          return;
        }
        const views = result.views || [];
        const obv = views.find(v => /obv|_01/i.test(v.code || ''));
        const rev = views.find(v => /rev|_02/i.test(v.code || ''));
        this.destitchedViews = {
          obverse: obv?.crop_base64 || undefined,
          reverse: rev?.crop_base64 || undefined,
        };
        if (!this.destitchedViews.obverse && !this.destitchedViews.reverse) {
          this.destitchError = 'No obverse/reverse views detected.';
          return;
        }
        // Cache the in-progress annotations under 'original', then jump to
        // whichever side the destitcher actually produced.
        this.annotationsByView.set('original', [...this.lineAnnotations]);
        this.selectDestitchView(this.destitchedViews.obverse ? 'obverse' : 'reverse');
      },
      error: (err) => {
        this.isDestitching = false;
        this.destitchError = err?.error?.detail || err?.message || 'Destitch failed.';
      },
    });
  }

  /** Switch the canvas to a different view. Per-view annotations are preserved. */
  selectDestitchView(view: 'original' | 'obverse' | 'reverse'): void {
    if (view === this.currentView) { return; }
    if (view !== 'original' && !this.destitchedViews[view]) { return; }

    // Stash the annotations for the view we're leaving.
    this.annotationsByView.set(this.currentView, [...this.lineAnnotations]);
    this.currentView = view;
    this.lineAnnotations = this.annotationsByView.get(view) || [];
    this.selectedLineIndex = -1;

    if (view === 'original') {
      if (this.currentTablet) {
        this.loadTabletImage(this.currentTablet.p_number, this.showingLineart ? 'lineart' : 'photo');
      }
    } else {
      const data = this.destitchedViews[view];
      if (data) { this.loadImageFromBase64(data); }
    }
  }

  /** Drop the destitched crops, returning to the single-image flow. */
  clearDestitch(): void {
    this.destitchedViews = {};
    this.destitchError = '';
    this.annotationsByView.delete('obverse');
    this.annotationsByView.delete('reverse');
    if (this.currentView !== 'original') {
      this.selectDestitchView('original');
    }
  }

  private loadImageFromBase64(b64: string): void {
    const img = new Image();
    img.onload = () => {
      this.image = img;
      this.imageWidth = img.width;
      this.imageHeight = img.height;
      this.imageLoaded = true;
      this.isLoading = false;
      this.fitImageToView();
      this.redraw();
    };
    img.onerror = () => { this.isLoading = false; };
    img.src = `data:image/png;base64,${b64}`;
  }

  // -- Tablet loading --

  loadTabletList(): void {
    this.loadingTablets = true;
    this.http.get<any[]>(`${this.API_BASE}/tablets`).subscribe(
      (tablets) => {
        this.tablets = tablets;
        this.loadingTablets = false;
      },
      () => { this.loadingTablets = false; }
    );
  }

  loadTablet(pNumber: string): void {
    this.isLoading = true;
    this.http.get<any>(`${this.API_BASE}/tablets/${pNumber}`).subscribe(
      (tablet) => {
        this.currentTablet = tablet;
        this.transliterationLines = (tablet.transliteration || '')
          .split('\n')
          .filter((l: string) => l.trim());
        this.translationLines = (tablet.translation || '')
          .split('\n')
          .filter((l: string) => l.trim());
        this.lineAnnotations = [];
        this.selectedLineIndex = -1;
        this.rightPanelTab = 'lines';

        // Pre-load transliteration into the ACE editor
        this.editorText = tablet.transliteration || '';

        // Reset destitch state — crops belong to the previous tablet.
        this.destitchedViews = {};
        this.currentView = 'original';
        this.destitchError = '';
        this.annotationsByView.clear();

        // Prefer photo when available; fall back to lineart only if there's no photo.
        this.showingLineart = !tablet.has_photo && !!tablet.has_lineart;
        this.loadTabletImage(pNumber, this.showingLineart ? 'lineart' : 'photo');
      },
      () => { this.isLoading = false; }
    );
  }

  toggleImageType(): void {
    if (!this.currentTablet) return;
    // Toggling photo/lineart invalidates the destitched crops (they were made
    // from the previous source). Clear them so the user can re-destitch.
    if (this.hasDestitchedViews) {
      this.clearDestitch();
    }
    this.showingLineart = !this.showingLineart;
    this.loadTabletImage(
      this.currentTablet.p_number,
      this.showingLineart ? 'lineart' : 'photo'
    );
  }

  private loadTabletImage(pNumber: string, type: 'lineart' | 'photo'): void {
    const url = `${this.API_BASE}/tablets/${pNumber}/${type}`;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      this.image = img;
      this.imageWidth = img.width;
      this.imageHeight = img.height;
      this.imageLoaded = true;
      this.isLoading = false;
      this.fitImageToView();
      this.redraw();
    };
    img.onerror = () => {
      this.isLoading = false;
    };
    img.src = url;
  }

  // -- Hit testing --

  private findLineAt(ix: number, iy: number): number {
    for (let i = this.lineAnnotations.length - 1; i >= 0; i--) {
      if (this.isPointInPolygon(ix, iy, this.lineAnnotations[i].polygon)) {
        return i;
      }
    }
    return -1;
  }

  private isPointInPolygon(x: number, y: number, polygon: { x: number; y: number }[]): boolean {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const xi = polygon[i].x, yi = polygon[i].y;
      const xj = polygon[j].x, yj = polygon[j].y;
      const intersect = ((yi > y) !== (yj > y)) &&
        (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  // -- Polygon builder --

  private buildAnnotation(points: StrokePoint[]): LineAnnotation {
    const topEdge: { x: number; y: number }[] = [];
    const bottomEdge: { x: number; y: number }[] = [];

    for (const p of points) {
      topEdge.push({ x: p.x, y: p.y - p.halfHeight });
      bottomEdge.push({ x: p.x, y: p.y + p.halfHeight });
    }

    const polygon = [...topEdge, ...bottomEdge.reverse()];
    return { points: [...points], polygon };
  }

  // -- Rendering --

  private redraw(): void {
    const canvas = this.canvasRef.nativeElement;
    const ctx = this.ctx;
    if (!ctx) return;

    ctx.fillStyle = '#e8e8e8';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (this.image) {
      ctx.save();
      ctx.translate(this.panX, this.panY);
      ctx.scale(this.zoomLevel, this.zoomLevel);
      ctx.drawImage(this.image, 0, 0);
      ctx.restore();
    }

    for (let i = 0; i < this.lineAnnotations.length; i++) {
      this.drawLineAnnotation(ctx, this.lineAnnotations[i], i, i === this.selectedLineIndex);
    }

    if (this.isDrawing && this.currentStroke.length >= 2) {
      const tempAnnotation = this.buildAnnotation(this.currentStroke);
      this.drawLineAnnotation(ctx, tempAnnotation, this.lineAnnotations.length, false, true);
    }

    // Highlighter preview overlay — visible when draw mode is on or Shift is held.
    if (this.isHighlighterActive && this.cursorImg && !this.isPanning) {
      this.drawHighlighterPreview(ctx, this.cursorImg);
    }
  }

  /**
   * Draw a thin vertical "highlighter" preview at the cursor.
   * Width is fixed at 3 screen pixels; height = current `strokeHeight` —
   * so the user sees a slim vertical bar showing exactly how tall the
   * stroke will be at this point.
   */
  private drawHighlighterPreview(ctx: CanvasRenderingContext2D, pos: { x: number; y: number }): void {
    const halfH = this.strokeHeight / 2;
    const halfW = 1.5 / this.zoomLevel; // 3 screen px wide regardless of zoom

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.zoomLevel, this.zoomLevel);

    ctx.fillStyle = 'rgba(25,118,210,0.55)';
    ctx.fillRect(pos.x - halfW, pos.y - halfH, halfW * 2, this.strokeHeight);

    ctx.restore();
  }

  private drawLineAnnotation(
    ctx: CanvasRenderingContext2D,
    annotation: LineAnnotation,
    colorIndex: number,
    selected: boolean,
    inProgress = false,
  ): void {
    const poly = annotation.polygon;
    if (poly.length < 3) return;

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.zoomLevel, this.zoomLevel);

    ctx.beginPath();
    const first = poly[0];
    ctx.moveTo(first.x, first.y);
    for (let i = 1; i < poly.length; i++) {
      ctx.lineTo(poly[i].x, poly[i].y);
    }
    ctx.closePath();

    const fillColor = LINE_COLORS[colorIndex % LINE_COLORS.length];
    const borderColor = LINE_BORDER_COLORS[colorIndex % LINE_BORDER_COLORS.length];

    ctx.fillStyle = inProgress ? 'rgba(255,255,255,0.2)' : fillColor;
    ctx.fill();

    ctx.strokeStyle = selected ? '#fff' : borderColor;
    ctx.lineWidth = selected ? 2 / this.zoomLevel : 1 / this.zoomLevel;
    if (inProgress) {
      ctx.setLineDash([4 / this.zoomLevel, 4 / this.zoomLevel]);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw center baseline
    const points = annotation.points;
    if (points.length >= 2) {
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
      }
      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1 / this.zoomLevel;
      ctx.setLineDash([2 / this.zoomLevel, 2 / this.zoomLevel]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    ctx.restore();
  }
}
