import { AfterContentChecked, AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter, HostListener, Input, Output, ViewChild } from '@angular/core';
import { fabric } from 'fabric';
import { Point, Rect } from 'fabric/fabric-impl';
import { Index, LineStats } from 'src/app/models/letter';
import { ShortcutInput, ShortcutEventOutput, KeyboardShortcutsComponent, AllowIn } from "ng-keyboard-shortcuts";
import { NotificationService } from 'src/app/services/notification.service';
import { CanvasBoxService } from 'src/app/services/canvas-box.service';
import { GuideLineService } from 'src/app/services/guide-line.service';
import { GuideLineData } from 'src/app/models/cured';



export enum CanvasType {
  Amendment = "Amendment",
  ViewAmendment = "ViewAmendment",
  Drawing = "Drawing",
  SingleSelection = "SingleSelection"
}

export enum CanvasMode {
  Pan = "Pan",
  Add = "Add",
  Adjust = "Adjust",
  Draw = "Draw",
  Erase = "Erase",
  Split = "Split",
  Combine = "Combine",
  Delete = "Delete",
  Mark = "Mark",
  AddTemplate = "AddTemplate",
  Guide = "Guide"
}

export enum RectColor {
  Regular = "Regular",
  Delete = "Delete",
  Mark = "Mark"
}

export class CanvasModeProperties {
  constructor(public name: string,
    public tooltip: string,
    public icon: string) {}
}

@Component({
  selector: 'fabric-canvas',
  templateUrl: './fabric-canvas.component.html',
  styleUrls: ['./fabric-canvas.component.scss']
})
export class FabricCanvasComponent implements AfterViewInit, AfterContentChecked {

  @ViewChild('htmlCanvas') htmlCanvas: ElementRef;
  @ViewChild('container', { static: true }) canvasContainer: ElementRef;

  
  private canvas: fabric.Canvas;
  @Output() modeChange: EventEmitter<string> = new EventEmitter();
  @Output() selectionChange: EventEmitter<number> = new EventEmitter();

  @Output() boxDeleted: EventEmitter<number> = new EventEmitter();
  @Output() boxAdded: EventEmitter<Rect> = new EventEmitter();
  @Output() boxMarkToggle: EventEmitter<Rect> = new EventEmitter();
  @Output() combineBoxesEmitter: EventEmitter<any> = new EventEmitter();

  @Output() mouseUp: EventEmitter<any> = new EventEmitter();
  @Output() imageRotated: EventEmitter<string> = new EventEmitter();

  @Input() public canvasType: CanvasType;
  @Input() public isLoading: boolean = false;

  public allCanvasModes = CanvasMode;

  public selectedMode = CanvasMode.Pan;

  public selectedRect: Rect = null;

  public selectedTemplate = null;
  public imageBeingCreated: boolean = false;
  public adjustMode = new CanvasModeProperties(CanvasMode.Adjust, "Adjust a box (alt+x)", "transform");
  public addMode = new CanvasModeProperties(CanvasMode.Add, "Add a box (alt+a)", "add");
  public panMode = new CanvasModeProperties(CanvasMode.Pan, "Pan (alt+z)", "pan_tool");
  public deleteMode = new CanvasModeProperties(CanvasMode.Delete, "Delete a box (alt+d)", "delete_sweep");
  public addTemplateMode = new CanvasModeProperties(CanvasMode.AddTemplate, "Add template (alt+a)", "add");
  public drawMode = new CanvasModeProperties(CanvasMode.Draw, "Draw (alt+r)", "brush");
  public eraseMode = new CanvasModeProperties(CanvasMode.Erase, "Erase (alt+e)", "phonelink_erase");
  public guideMode = new CanvasModeProperties(CanvasMode.Guide, "Guide line (alt+g)", "straighten");

  shortcuts: ShortcutInput[] = [];  


  public props = {
    canvasWidth: 300,
    canvasHeight: 300,
    backgroundColor: "#ebebef",
    canvasImage: '',
    maxZoom: 50,
    minZoom: 0.1
  };

  public drawTemplates = [
    {"src": "/assets/img/templates/horiz1.png", "height": 116, "width": 205},
    {"src": "/assets/img/templates/horiz2.png", "height": 150, "width": 217},
    {"src": "/assets/img/templates/ver1.png", "height": 205, "width": 116},
    {"src": "/assets/img/templates/ver2.png", "height": 230, "width": 184},
    {"src": "/assets/img/templates/winck1.png", "height": 121, "width": 98},
    {"src": "/assets/img/templates/winck2.png", "height": 136, "width": 127},
    {"src": "/assets/img/templates/winck3.png", "height": 139, "width": 130}
  ];

  public allowedActions: CanvasModeProperties[]  = [];

  public drawActions = [
    this.drawMode,
    this.eraseMode,
    this.addTemplateMode,
    this.adjustMode,
    this.deleteMode
  ]

  public amendmentActions = [
    this.panMode,
    this.adjustMode,
    this.addMode,
    new CanvasModeProperties(CanvasMode.Split, "Split a box (alt+s)", "content_cut"),
    new CanvasModeProperties(CanvasMode.Combine, "Combine boxes (alt+c)", "merge_type"),
    this.deleteMode
  ]

  public viewAmendmentActions = [
    this.panMode
  ]

  public singleSelectionActions = [
    this.panMode,
    this.addMode,
    this.adjustMode,
    this.deleteMode,
    this.guideMode
  ]

  private tempTemplate = null;

  private newRect = null;
  private deleteLine: fabric.Line = null;

  public RECT_STROKE_WIDTH = 2;  // Match YOLO annotation style
  public DEFAULT_RECT_FILL = "rgba(33,150,243,0.2)"  // Material blue, matching service
  public DEFAULT_RECT_STROKE = "#2196F3"  // Material blue

  // Pan/zoom state (same as annotation-canvas)
  private spacePressed = false;
  private panModeActive = false;
  private isPanning = false;
  private lastPanPosition: { x: number; y: number } | null = null;
  private isDrawingBox = false;
  private drawStart: { x: number; y: number } | null = null;

  private mode: CanvasMode = CanvasMode.Pan;

  // Crosshair guide lines
  public crosshairEnabled: boolean = true;
  private crosshairH: fabric.Line = null;
  private crosshairV: fabric.Line = null;

  // ── Guide lines (bezier reading guides) ──
  @Output() guidesChanged: EventEmitter<GuideLineData[]> = new EventEmitter();
  private guides: Map<string, { data: GuideLineData; path: fabric.Path; handles: fabric.Object[] }> = new Map();
  private guideDrawState: 'idle' | 'placing' = 'idle';
  private guideStartPoint: { x: number; y: number } | null = null;
  private guidePreviewLine: fabric.Line | null = null;
  public selectedGuideId: string | null = null;
  public guideColor: string = 'rgba(255, 0, 255, 0.4)';
  public guideHexColor: string = '#ff00ff';
  public guideStrokeWidth: number = 20;

  // ── Custom-color picker draft state ───────────────────────────────────
  // The native `<input type="color">` fires `input` on every cursor move
  // inside the OS picker, which used to spam the recent-colors list with
  // every transient hue the user passed through. Now the picker only
  // mutates these draft fields; nothing is applied (and nothing lands in
  // recents) until the user clicks the Add button. The alpha lives here
  // as a 0–100 percentage so the slider can bind to it directly.
  public draftHex: string = '#ff00ff';
  public draftAlphaPct: number = 40;

  constructor(
    private cdref: ChangeDetectorRef,
    public notificationService: NotificationService,
    private canvasBoxService: CanvasBoxService,
    public guideLineService: GuideLineService
  ) {}

  // Keyboard listeners for pan mode (same as annotation-canvas)
  @HostListener('window:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if (event.code === 'Space' && !this.spacePressed) {
      this.spacePressed = true;
      if (this.canvas) {
        this.canvas.defaultCursor = 'grab';
        this.canvas.renderAll();
      }
    }
    // Arrow keys: nudge selected guide
    if (this.selectedGuideId && (event.code === 'ArrowUp' || event.code === 'ArrowDown')) {
      event.preventDefault();
      const zoom = this.canvas ? this.canvas.getZoom() : 1;
      const step = 5 / zoom;  // adaptive to zoom
      const dy = event.code === 'ArrowUp' ? -step : step;
      this.nudgeSelectedGuide(dy);
    }
  }

  @HostListener('window:keyup', ['$event'])
  onKeyUp(event: KeyboardEvent): void {
    if (event.code === 'Space') {
      this.spacePressed = false;
      this.isPanning = false;
      if (this.canvas) {
        this.canvas.defaultCursor = this.panModeActive ? 'grab' : 'default';
        this.canvas.renderAll();
      }
    }
  }

  ngAfterViewInit(): void {
    this.initAll();
    this.cdref.detectChanges();

    // Native keydown listener for Delete key as fallback
    document.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Delete') {
        console.log('[KEYDOWN] Delete key pressed natively');
        this.deleteActiveObject();
      }
    });
    for (let index = 0; index < 7; index++) {
      this.shortcuts.push({
        key: `alt + ${index+1}`,  
        preventDefault: true,  
        command: e => this.changeTemplate(index)
      });  
    }

    this.shortcuts.push(  
      {  
          key: "alt + z",  
          preventDefault: true,  
          command: e => this.changeMode(CanvasMode.Pan)  
      },
      {  
        key: "alt + x",  
        preventDefault: true,  
        command: e => this.changeMode(CanvasMode.Adjust)  
      },
      {  
        key: "alt + a",  
        preventDefault: true,  
        command: e => this.changeToAMode()  
      },
      {  
        key: "alt + s",  
        preventDefault: true,  
        command: e => this.changeMode(CanvasMode.Split)  
      },
      {  
        key: "alt + c",  
        preventDefault: true,  
        command: e => this.changeMode(CanvasMode.Combine)  
      },
      {  
        key: "alt + e",  
        preventDefault: true,  
        command: e => this.changeMode(CanvasMode.Erase)
      },
      {  
        key: "alt + d",  
        preventDefault: true,  
        command: e => this.changeMode(CanvasMode.Delete)
      },
      {
        key: "alt + r",
        preventDefault: true,
        command: e => this.changeMode(CanvasMode.Draw)
      },
      {
        key: "delete",
        preventDefault: true,
        command: e => this.deleteActiveObject()
      },
      {
        key: "alt + g",
        preventDefault: true,
        command: e => this.changeMode(CanvasMode.Guide)
      }
    )
  }

  deleteActiveObject() {
    // Check if a guide is selected first
    if (this.selectedGuideId) {
      this.removeGuide(this.selectedGuideId);
      return;
    }
    let activeObj = this.canvas.getActiveObject();
    if (activeObj && activeObj.type === 'rect') {
      this.canvas.remove(activeObj);
      this.canvas.discardActiveObject();
      this.canvas.requestRenderAll();
      if (activeObj.data) {
        this.boxDeleted.emit(activeObj.data.index);
      }
    }
  }


  changeToAMode() {
    if(this.canvasType == CanvasType.Drawing) {
      this.changeMode(CanvasMode.AddTemplate);
    } else {
      this.changeMode(CanvasMode.Add)
    } 
  }

  public isDrawingMode() {
    return this.selectedMode == 'Draw' || this.selectedMode == 'Erase';
  }

  public isTemplateMode() {
    return this.selectedMode == 'AddTemplate';
  }

  ngAfterContentChecked() {
    this.cdref.detectChanges();
  }

  // Track if wheel zoom/pan has been set up
  private wheelZoomSetup = false;

  initAll() {
    this.canvas = new fabric.Canvas(this.htmlCanvas.nativeElement, {
      hoverCursor: 'pointer',
      selectionBorderColor: '#2196F3',  // Material blue
      backgroundColor: '#ebebef',
      preserveObjectStacking: true,
      uniformScaling: false,
    });

    // Always set up wheel zoom/pan for all canvas types (except Drawing)
    // This ensures consistent behavior whether canvas is initialized via canvasType or externally
    if (this.canvasType !== CanvasType.Drawing) {
      this.setWheelZooming();
    }

    if(this.canvasType) {
      this.updateActionsAccordingToType();
    }

    // Crosshair guide lines (hidden by default)
    this.crosshairH = new fabric.Line([0, 0, 5000, 0], {
      stroke: 'rgba(25, 118, 210, 0.6)',
      strokeWidth: 1,
      strokeUniform: true,
      objectCaching: false,
      selectable: false,
      evented: false,
      excludeFromExport: true,
      visible: false
    });
    this.crosshairV = new fabric.Line([0, 0, 0, 5000], {
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

    // Global crosshair tracking via native DOM events (survives resetEvents)
    const upperCanvas = this.canvas.getSelectionElement();
    if (upperCanvas) {
      upperCanvas.addEventListener('mousemove', (e: MouseEvent) => {
        if (!this.crosshairEnabled || !this.crosshairH || !this.crosshairV) return;
        const pointer = this.canvas.getPointer(e);
        this.crosshairH.set({ x1: -5000, y1: pointer.y, x2: 5000, y2: pointer.y, visible: true });
        this.crosshairV.set({ x1: pointer.x, y1: -5000, x2: pointer.x, y2: 5000, visible: true });
        this.crosshairH.bringToFront();
        this.crosshairV.bringToFront();
        this.canvas.renderAll();
      });
      upperCanvas.addEventListener('mouseleave', () => this.hideCrosshair());
    }
  }

  changeTemplate(val) {
    this.selectedTemplate = `${val}`;

    if(this.tempTemplate) {
      // if temp template, change its image to new selected template
      let self = this;
      let t = self.drawTemplates[self.selectedTemplate]

      fabric.Image.fromURL(t.src, function(myImg) {
        self.canvas.remove(self.tempTemplate);
        
        self.addTemplateImageToCanvas(myImg, self.tempTemplate.left, self.tempTemplate.top, t.width, t.height);
  
        self.tempTemplate = myImg;
      });
    }
  }
  
  updateActionsAccordingToType() {
    if(this.canvasType == CanvasType.Amendment) {
      this.allowedActions = this.amendmentActions;
      this.setWheelZooming();
      this.changeMode(CanvasMode.Pan);
    }
    else if(this.canvasType == CanvasType.ViewAmendment) {
      this.allowedActions = this.viewAmendmentActions;
      this.setWheelZooming();
      this.changeMode(CanvasMode.Pan);
    }
    else if(this.canvasType == CanvasType.Drawing) {
      this.allowedActions = this.drawActions;
      this.changeMode(CanvasMode.Draw);
    } else if(this.canvasType == CanvasType.SingleSelection) {
      this.allowedActions = this.singleSelectionActions;
      this.setWheelZooming();
      this.changeMode(CanvasMode.Pan);
    }
  }

  hardReset() {
    this.canvas.clear();
    // Reset wheel zoom setup so it can be re-initialized
    this.wheelZoomSetup = false;
  }

  getCanvas() {
    return this.canvas;
  }

  clearCanvas() {
    this.canvas.clear();
    this.canvas.setBackgroundColor("#ebebef", undefined);
  }

  forceZoomOut(zoom=0.5) {
    // Set zoom - position at origin (like before) for consistent placement
    // The viewport transform is [scaleX, skewY, skewX, scaleY, translateX, translateY]
    this.canvas.setViewportTransform([zoom, 0, 0, zoom, 0, 0]);
    this.canvas.renderAll();
  }

  getViewportTransform(): number[] | null {
    return this.canvas?.viewportTransform ? [...this.canvas.viewportTransform] : null;
  }

  restoreViewportTransform(vpt: number[]): void {
    if (this.canvas && vpt) {
      this.canvas.setViewportTransform(vpt);
      this.canvas.renderAll();
    }
  }

  zoomIn() {
    let zoom = this.canvas.getZoom() * 1.3;
    if (zoom > this.props.maxZoom) zoom = this.props.maxZoom;
    this.canvas.zoomToPoint({ x: this.canvas.getWidth() / 2, y: this.canvas.getHeight() / 2 } as Point, zoom);
  }

  zoomOut() {
    let zoom = this.canvas.getZoom() / 1.3;
    if (zoom < this.props.minZoom) zoom = this.props.minZoom;
    this.canvas.zoomToPoint({ x: this.canvas.getWidth() / 2, y: this.canvas.getHeight() / 2 } as Point, zoom);
  }

  setWheelZooming() {
    // Avoid setting up wheel zoom multiple times
    if (this.wheelZoomSetup) return;

    // Use shared service for consistent zoom/pan behavior
    this.canvasBoxService.setupWheelZoomPan(this.canvas, {
      minZoom: this.props.minZoom,
      maxZoom: this.props.maxZoom
    });

    this.wheelZoomSetup = true;
  }

  setCanvasSize() {
    let width = this.canvasContainer.nativeElement.offsetWidth - 30;
    this.canvas.setWidth(width);
    this.canvas.setHeight(this.props.canvasHeight);
    this.canvas.renderAll();
    this.canvas.calcOffset();
    // this.canvas.calcViewportBoundaries();
  }

  forceCanvasSize() {
    this.canvas.setWidth(this.props.canvasWidth);
    this.canvas.setHeight(this.props.canvasHeight);
    this.canvas.renderAll();
    this.canvas.calcOffset();
  }
  
  clear() {
    this.canvas.clear();
    this.canvas.backgroundColor = this.props.backgroundColor;
  }

  setDeleteBoxMode() {
  }

  isCombineMode() {
    return this.selectedMode == CanvasMode.Combine;
  }

  setSplitBoxMode() {
  }

  setCombineMode() {
    this.setAllRectsSelectableState(false);
  }

  setMarkMode() {
    this.setAllRectsSelectableState(false);
  }

  setFreeHandMode() {
    if (this.canvasType == CanvasType.Drawing) return;

    // Allow object selection (for handles) but disable multi-select drag
    this.canvas.selection = false;
    this.setAllRectsSelectableState(true);

    // Use arrow functions to preserve 'this' context (same as annotation-canvas)
    this.canvas.on('mouse:down', (opt) => this.onFreeHandMouseDown(opt));
    this.canvas.on('mouse:move', (opt) => this.onFreeHandMouseMove(opt));
    this.canvas.on('mouse:up', (opt) => this.onFreeHandMouseUp(opt));
  }

  // Mouse handlers matching annotation-canvas behavior
  private onFreeHandMouseDown(e: fabric.IEvent): void {
    if (!this.canvas) return;

    const evt = e.e as MouseEvent;
    const target = e.target;

    // Middle mouse button or space + left click = panning
    if (evt.button === 1 || (this.spacePressed && evt.button === 0)) {
      this.isPanning = true;
      this.lastPanPosition = { x: evt.clientX, y: evt.clientY };
      this.canvas.defaultCursor = 'grabbing';
      this.canvas.renderAll();
      return;
    }

    // Click on a box or its handles: let fabric.js handle it natively
    if (target) {
      this.isPanning = false;
      this.isDrawingBox = false;
      return;
    }

    // Shift + left click on empty area = draw new box (unified with YOLO annotation)
    if (evt.shiftKey && evt.button === 0) {
      this.canvas.discardActiveObject();

      const pointer = this.canvas.getPointer(e.e);
      this.drawStart = { x: pointer.x, y: pointer.y };
      this.isDrawingBox = true;

      // Create temp rect
      this.newRect = this.makeRectangle(
        pointer.x, pointer.y, 0, 0,
        this.DEFAULT_RECT_FILL, this.DEFAULT_RECT_STROKE, false
      );
      this.canvas.add(this.newRect);
      this.canvas.renderAll();
      return;
    }

    // Plain left click on empty area = start panning
    if (evt.button === 0) {
      this.isPanning = true;
      this.lastPanPosition = { x: evt.clientX, y: evt.clientY };
      this.canvas.defaultCursor = 'grabbing';
      this.canvas.renderAll();
    }
  }

  private onFreeHandMouseMove(e: fabric.IEvent): void {
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
    if (!this.isDrawingBox || !this.drawStart || !this.newRect) return;

    const pointer = this.canvas.getPointer(e.e);

    const left = Math.min(this.drawStart.x, pointer.x);
    const top = Math.min(this.drawStart.y, pointer.y);
    const width = Math.abs(pointer.x - this.drawStart.x);
    const height = Math.abs(pointer.y - this.drawStart.y);

    this.newRect.set({ left, top, width, height });
    this.canvas.renderAll();
  }

  private onFreeHandMouseUp(e: fabric.IEvent): void {
    if (!this.canvas) return;

    // End panning
    if (this.isPanning) {
      this.isPanning = false;
      this.lastPanPosition = null;
      this.canvas.defaultCursor = (this.spacePressed || this.panModeActive) ? 'grab' : 'default';
      this.canvas.setViewportTransform(this.canvas.viewportTransform!);
      this.canvas.renderAll();
      return;
    }

    // End drawing
    if (!this.isDrawingBox || !this.newRect) return;

    this.isDrawingBox = false;
    this.drawStart = null;

    // Finalize the box
    this.canvas.remove(this.newRect);
    const finalRect = this.newRect;
    this.newRect = null;

    // Only add if box is large enough
    if (finalRect.getScaledWidth() >= 7 && finalRect.getScaledHeight() >= 7) {
      this.addEventsToRectangle(finalRect);
      this.canvas.add(finalRect);
      this.boxAdded.emit(finalRect);
    }

    this.canvas.renderAll();
  }

  deselectSelectedRect() {
    if(this.selectedRect) this.fillBox(this.selectedRect, RectColor.Regular)
  }

  setDrawMode() {
    this.canvas.isDrawingMode = true;
    // var brush = new fabric.PencilBrush();
    // brush.color = 'red';
    // brush.width = 4;
    // this.canvas.freeDrawingBrush = brush;
    this.canvas.freeDrawingBrush.color = '#000';
    this.canvas.freeDrawingBrush.width = 7;
    let self = this;
    // this.canvas.on('mouse:up', function(obj) {
    //   self.mouseUp.emit();
    //   return obj;
    // });
  }
  
  setEraseMode() {
    this.canvas.isDrawingMode = true;
    this.canvas.freeDrawingBrush.color = '#ebebef';
    this.canvas.freeDrawingBrush.width = 25;

  }

  brushSizeChange(event) {
    this.canvas.freeDrawingBrush.width = event.value;
  }

  setCanvasImage() {
    if (this.props.canvasImage) {
      this.canvas.setBackgroundImage(this.props.canvasImage, this.canvas.renderAll.bind(this.canvas), {excludeFromExport: false});
      // this.canvas.renderAll();
    }
  }

  /**
   * Rotate the background image 90° clockwise.
   * Swaps canvas dimensions and re-renders.
   */
  rotateImage(): void {
    const bgImage = this.canvas.backgroundImage as fabric.Image;
    if (!bgImage) return;

    // Create an offscreen canvas to rotate the image
    const srcEl = bgImage.getElement() as HTMLImageElement;
    const offscreen = document.createElement('canvas');
    const ctx = offscreen.getContext('2d');
    // After 90° CW rotation: new width = old height, new height = old width
    offscreen.width = srcEl.height;
    offscreen.height = srcEl.width;
    ctx.translate(offscreen.width, 0);
    ctx.rotate(Math.PI / 2);
    ctx.drawImage(srcEl, 0, 0);

    const rotatedDataUrl = offscreen.toDataURL('image/png');

    // Update canvas dimensions
    const newWidth = offscreen.width;
    const newHeight = offscreen.height;
    this.props.canvasWidth = newWidth;
    this.props.canvasHeight = newHeight;
    this.canvas.setWidth(newWidth);
    this.canvas.setHeight(newHeight);

    // Set rotated image as new background
    this.props.canvasImage = rotatedDataUrl;
    this.canvas.setBackgroundImage(rotatedDataUrl, () => {
      this.canvas.renderAll();
      this.imageRotated.emit(rotatedDataUrl);
    }, { excludeFromExport: false });
  }

  emitSelectionChanged(id) {
    this.deselectSelectedRect()
    this.selectionChange.emit(id)
  }

  emitSelectionClear() {
    this.deselectSelectedRect()
    this.selectionChange.emit(undefined)
  }

  resetCanvasSelection() {
    this.canvas.discardActiveObject();
    this.canvas.selection = false;
    this.canvas.forEachObject(function(o) {
        o.selectable = false;
    });
  }

  addTemplateImageToCanvas(img: fabric.Image, left, top, width, height) {
    let self = this;
    img.set({ left: left, top: top, width: width, height: height});
    this.canvas.add(img); 

    img.on('mousedown', (opt) => {
      if(self.mode == CanvasMode.Delete) {
        self.canvas.remove(img);
        if(img == self.tempTemplate) {
          self.tempTemplate = null;
        }
      }
    });


    img.on('mousemove', (opt) => {
      if(self.mode == CanvasMode.Delete) {
        img.backgroundColor = 'red';
        img.opacity = 0.3
        self.canvas.renderAll()
        // img.set("stroke", 'red');
      }
    });

    img.on('mouseout', (opt) => {
        img.backgroundColor = 'transparent';
        img.opacity = 1
        self.canvas.renderAll()      
    });
  }

  setAddTemplateMode() {
    this.resetCanvasSelection();
    let self = this;
    let originX, originY = 0;

    this.canvas.on('mouse:down', function(o){
      // create template from temp to real, if temp exists
      if(self.tempTemplate != null) {
        var pointer = self.canvas.getPointer(o.e);
        originX = pointer.x;
        originY = pointer.y;

        let t = self.drawTemplates[self.selectedTemplate]
        fabric.Image.fromURL(t.src, function(myImg) {
          self.addTemplateImageToCanvas(myImg, originX, originY, t.width, t.height);
        });

        self.selectedTemplate = null;
        self.canvas.remove(self.tempTemplate);
        self.tempTemplate = null;
      }
    });

    this.canvas.on('mouse:move', function(o){
      // if no temp template, and selected one, and nothing being created already, create a temp template!
      if (self.tempTemplate == null && self.selectedTemplate != null && self.imageBeingCreated == false) {
        self.imageBeingCreated = true;

        var pointer = self.canvas.getPointer(o.e);
        originX = pointer.x;
        originY = pointer.y;
        let t = self.drawTemplates[self.selectedTemplate]

        fabric.Image.fromURL(t.src, function(myImg) {
          self.addTemplateImageToCanvas(myImg, originX, originY, t.width, t.height);

          self.tempTemplate = myImg;
          self.imageBeingCreated = false;
        });
        
      }

      if(self.tempTemplate != null) {
        // updat template location with cursor
        var pointer = self.canvas.getPointer(o.e);
        self.tempTemplate.set({ left: Math.abs(pointer.x) });
        self.tempTemplate.set({ top: Math.abs(pointer.y) });
        self.canvas.renderAll();
      }

    });

    this.canvas.on('mouse:out', function(o){
      // remove temp template when leaving the canvas
      if (self.tempTemplate == null) return;
      self.canvas.remove(self.tempTemplate);
      self.tempTemplate = null;
    });   
  }

  setAddBoxMode() {
    this.resetCanvasSelection();

    // this.canvas.preserveObjectStacking  = false;

    let self = this;
    let isMouseDown = false;
    let originX, originY = 0;

    // initialize new rect on mouse down
    this.canvas.on('mouse:down', function(o){
      isMouseDown = true;
      var pointer = self.canvas.getPointer(o.e);
      originX = pointer.x;
      originY = pointer.y;
      
      if(self.newRect == null) {
        self.newRect = self.makeRectangle(originX, originY, pointer.x-originX, pointer.y-originY, self.DEFAULT_RECT_FILL, self.DEFAULT_RECT_STROKE, false);
        self.canvas.add(self.newRect);
      }
    });
    
    // on mouse move, resize and move it
    this.canvas.on('mouse:move', function(o){
      // do something only if new rect is created
      if (!isMouseDown || self.newRect == null) return;

      var pointer = self.canvas.getPointer(o.e);
      if(originX > pointer.x){
        self.newRect.set({ left: Math.abs(pointer.x) });
      }
      if(originY > pointer.y){
        self.newRect.set({ top: Math.abs(pointer.y) });
      }
      
      self.newRect.set({ width: Math.abs(originX - pointer.x) });
      self.newRect.set({ height: Math.abs(originY - pointer.y) });
      self.canvas.renderAll();
    });
  
  // when mouse up - delete temp rect and create good one
    this.canvas.on('mouse:up', function(o){
      isMouseDown = false;
      self.canvas.remove(self.newRect);

      let finalRect = self.newRect;
      self.newRect = null;

      if(finalRect.getScaledWidth() < 7 || finalRect.getScaledHeight() < 7) {
        return;
      }

      self.addEventsToRectangle(finalRect);
      finalRect.selectable = false;
      self.canvas.add(finalRect);

      let txt = ""
      self.canvas.getObjects().forEach(obj => {
        txt += "[" + obj.left + ", " + obj.top + ", " + obj.getScaledWidth() + ", " + obj.getScaledHeight() + "],\n";
      });

      self.boxAdded.emit(finalRect);
    });
  }

makeRectangle(left: number, top: number, width: number, height: number, fill: string = this.DEFAULT_RECT_FILL,
  stroke: string = this.DEFAULT_RECT_STROKE, addListeners: boolean = true, index: Index = null, trustedDimensions: boolean = false) {
  // Boundary checking
  if(!trustedDimensions) {
    if(left < 0) left = 0;
    if(top < 0) top = 0;
    let canvasWidth = this.canvasContainer.nativeElement.offsetWidth - 30;
    if(left + width > canvasWidth) width = canvasWidth - left;
  }

  // Use shared service for consistent box creation
  const newRect = this.canvasBoxService.createBox(left, top, width, height, {
    fill: fill,
    stroke: stroke,
    strokeWidth: this.RECT_STROKE_WIDTH,
    data: index
  });

  if(addListeners) {
    this.addEventsToRectangle(newRect);
  }

  return newRect;
}

addRectangles(rects: fabric.Rect[]) {
  rects.forEach(rect => {
    this.canvas.add(rect);
  });
  this.canvas.renderAll();
}

printTarget(target) {
  // //console.log("Height: ", target.height, " Width: ", target.width);
  // //console.log("SCALED Height: ", target.getScaledHeight(), " Width: ", target.getScaledWidth())
}

addEventsToRectangle(rect: fabric.Rect) {
  let self = this;

  rect.on('mouseover', (opt) => {
    if(rect == null) {
      return;
    }

    if(self.mode == CanvasMode.Pan) {
      if(this.canvas.getActiveObject() == undefined) {
        // Only emit selection change if rect has data with index (not for selection boxes in stage 2)
        if (rect.data && rect.data.index !== undefined) {
          self.emitSelectionChanged(rect.data.index);
        }
        self.changeSelection(rect);
      }
    }
  })

  rect.on('mousemove', (opt) => {
    if(rect == null) {
      return;
    }

    if(self.mode == CanvasMode.Split) {
      let target = opt.target;
      if(self.deleteLine != null) {
        self.canvas.remove(self.deleteLine);
      }

      var pointer = self.canvas.getPointer(opt.e);
      let pointerX = pointer.x;

      let targetHeight = target.getScaledHeight();
      let zoom = this.canvas.getZoom()
      self.deleteLine = new fabric.Line([pointerX, target.top, pointerX, (target.top + targetHeight)], {
        strokeDashArray: [1 , 2 ],
        stroke: 'red',
        selectable: false,
        evented: false
      })

      self.canvas.add(self.deleteLine);
      self.canvas.renderAll();
    }
    if(self.mode == CanvasMode.Delete) {
      this.fillBox(rect, RectColor.Delete);
    } else if(self.mode == CanvasMode.Combine || self.mode == CanvasMode.Mark) {
      this.fillBox(rect, RectColor.Mark);
    }
  });

  rect.on('mouseout', opt => {
    if(rect == null) {
      return;
    }

    if(self.mode == CanvasMode.Pan) {
      if(this.canvas.getActiveObject() == undefined) {
        self.emitSelectionClear();
      }
    }

    if(self.mode == CanvasMode.Delete || ((self.mode == CanvasMode.Combine || self.mode == CanvasMode.Mark) && rect.data && !rect.data.selectedForAction)) {
      this.fillBox(rect, RectColor.Regular);
    }
  });

  rect.on('mousedown', (opt) => {
    if(self.mode == CanvasMode.Split) {
      if (self.deleteLine == null) {
        return;
      }
      var scaledPointer = self.canvas.getPointer(opt.e);
      let mouseX = scaledPointer.x;
      let target = opt.target as fabric.Rect;

      const targetLeft = target.left,
            targetTop = target.top,
            targetHeight = target.getScaledHeight() - this.RECT_STROKE_WIDTH,
            targetWidth = target.getScaledWidth();

      let leftRect = self.makeRectangle(targetLeft, targetTop, mouseX - targetLeft, targetHeight );
      let leftRectWidth = leftRect.getScaledWidth();
      let rightRect = self.makeRectangle(mouseX, targetTop, targetWidth - leftRectWidth, targetHeight);

      self.canvas.add(leftRect, rightRect);
      self.canvas.remove(rect, self.deleteLine);

      if (rect.data && rect.data.index !== undefined) {
        self.boxDeleted.emit(rect.data.index);
      }
      self.boxAdded.emit(rightRect);
      self.boxAdded.emit(leftRect);

      self.deleteLine = null;
      self.canvas.renderAll();
      this.setAllRectsSelectableState(false);
      // self.changeMode(CanvasMode.Pan);
    }

    if(self.mode == CanvasMode.Delete) {
      self.canvas.remove(rect);
      if (rect.data && rect.data.index !== undefined) {
        self.boxDeleted.emit(rect.data.index);
      }
      rect = null;
    }

    else if(self.mode == CanvasMode.Combine || self.mode == CanvasMode.Mark) {
      if (rect.data && rect.data.index !== undefined) {
        self.boxMarkToggle.emit(rect.data.index);
      }
    }

  });
}

resetMode() {
  this.resetEvents();
  this.resetCanvasStates();
  this.resetCanvasOverlays();
}

resetCanvasStates() {
  this.canvas.isDrawingMode = false;
  this.canvas.selection = false;
  this.setAllRectsSelectableState(true);
}

setAllRectsSelectableState(selectable: boolean) {
  this.canvas.forEachObject(function(o) {
    o.selectable = selectable;
  });

  if(!selectable) {
    this.canvas.discardActiveObject();
  }
}

resetCanvasOverlays() {
  this.canvas.remove(this.deleteLine);
  this.canvas.remove(this.newRect);
  this.newRect = null;
  this.deleteLine = null;

  // Clean up guide drawing state (but keep placed guides)
  if (this.guidePreviewLine) {
    this.canvas.remove(this.guidePreviewLine);
    this.guidePreviewLine = null;
  }
  this.guideDrawState = 'idle';
  this.guideStartPoint = null;
  // Hide guide handles only when leaving guide mode (not re-entering)
  if (this.mode !== CanvasMode.Guide) {
    this.guides.forEach(g => this.showGuideHandles(g.data.id, false));
    this.selectedGuideId = null;
  }
}

resetEvents() {
  this.canvas.off('mouse:down')
  this.canvas.off('mouse:up')
  this.canvas.off('mouse:move')
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

setAdujstMode() {
  this.canvas.selection = true;
  this.setAllRectsSelectableState(true);
}


changeMode(mode: CanvasMode) {
  this.resetMode();
  if(!this.allowedActions.some(action => action.name == mode)) {
    this.notificationService.showError(`Canvas ${mode} mode is not allowed`);
    return;
  }
  this.selectedMode = mode;
  switch(mode) { 
    case CanvasMode.Pan: { 
      this.setFreeHandMode()
      break; 
    } 
    case CanvasMode.Add: { 
      this.setAddBoxMode();
      break; 
    }
    case CanvasMode.Adjust: {
      this.setAdujstMode();
      break;
    }
    case CanvasMode.Draw: { 
      this.setDrawMode()
      break; 
    } 
    case CanvasMode.Erase: {
      this.setEraseMode();
      // this.setFreeHandMode()
      break;
    }
    case CanvasMode.Split: { 
      this.setSplitBoxMode();
      this.setFreeHandMode()
      break; 
    }
    case CanvasMode.Combine: {
      this.setCombineMode(); 
      this.setFreeHandMode()  
      break; 
    }
    case CanvasMode.Mark: {
      this.setMarkMode();
      this.setFreeHandMode();
      break;
    }
    case CanvasMode.Delete: { 
      this.setDeleteBoxMode()
      this.setFreeHandMode()
      break; 
    } 
    case CanvasMode.AddTemplate: {
      this.setAddTemplateMode();
      break;
    }
    case CanvasMode.Guide: {
      this.setGuideMode();
      break;
    }
    default: {
       break;
    }
  }

  if (Object.values(CanvasMode).includes(mode)) {
    this.mode = CanvasMode[mode];
  }

  this.modeChange.emit(mode);
  
}
  
changeSelection(rect) {
  // clear old rect first and don't render yet
  if(this.selectedRect) this.fillBox(this.selectedRect, RectColor.Regular, false)

  if(rect) {
    this.selectedRect = rect;
    this.fillBox(this.selectedRect, RectColor.Mark);
  } else {
    if(this.selectedRect) this.canvas.renderAll();
  }
}

markBoxForAction(rect: Rect, mark: boolean = true) {
  if(mark) {
    this.fillBox(rect, RectColor.Mark);
  } else {
    this.fillBoxRegular(rect);
  }
}

fillBoxRegular(rect: Rect) {
  this.fillBox(rect, RectColor.Regular);
}

fillBox(rect: Rect, mode: RectColor, render = true) {
  switch (mode) {
    case RectColor.Regular:
      rect.set("fill", this.DEFAULT_RECT_FILL);
      rect.set("stroke", this.DEFAULT_RECT_STROKE);
      break;
    case RectColor.Delete:
      rect.set("fill", 'rgba(244,67,54,0.2)');  // Material red
      rect.set("stroke", '#F44336');
      break;
    case RectColor.Mark:
      rect.set("fill", 'rgba(255,235,59,0.3)');  // Material yellow
      rect.set("stroke", '#FFC107');  // Material amber
      break;
    default:
      break;
  }

  if(render) this.canvas.renderAll();

}

combineSelected() {
  this.combineBoxesEmitter.emit();
}

combineBoxes(rects: Rect[]) {
  rects.sort((rect, otherRect) => rect.left < otherRect.left ? -1 : 1) // sort rects by left ascending
  let firstRect = rects[0], lastRect = rects[rects.length - 1];
  let newRectLeft = firstRect.left + this.RECT_STROKE_WIDTH;
  let newRectRight = lastRect.left + lastRect.getScaledWidth() - this.RECT_STROKE_WIDTH;
  let newRectWidth = newRectRight - newRectLeft;
  rects.sort((rect, otherRect) => rect.top < otherRect.top ? -1 : 1) // sort rects by top ascending
  let newRectTop = rects[0].top;
  
  rects.sort((rect, otherRect) => this.getRectBottom(rect) > this.getRectBottom(otherRect) ? -1 : 1); // sort rects by bottom descending
  let newRectBottom = this.getRectBottom(rects[0]);
  let newRectHeight = newRectBottom - newRectTop - this.RECT_STROKE_WIDTH;
  let newRect = this.makeRectangle(newRectLeft, newRectTop, newRectWidth, newRectHeight);   
  this.canvas.add(newRect);

  rects.forEach(rect => {
    this.canvas.remove(rect);
    this.boxDeleted.emit(rect.data.index);
  });

  this.boxAdded.emit(newRect);
  this.setAllRectsSelectableState(false);
}

removeAllRects() {
  this.canvas.getObjects().forEach(obj => {
    if(obj.type == "rect") {
      this.canvas.remove(obj);
    }
  })
}

getRectBottom(rect: Rect) {
  return rect.top + rect.getScaledHeight();
}

updateLines(lines: LineStats[]) {
  let fontSize = 24;

  // clean previous texts
  this.canvas.getObjects().forEach(obj => {
    if(obj.type == "text") {
      this.canvas.remove(obj);
    }
  })

  lines.forEach((line, index) => {
    var text = this.canvas.add(new fabric.Text(`${index + 1}`, { 
      left: -20,
      top: ((line.topAvg + line.bottomAvg) / 2) - (fontSize * 0.6),
      fill: 'black',
      fontSize: fontSize,
      textBackgroundColor: "yellow"
      
    }));

  })



}

// ════════════════════════════════════════════════
// ── Guide Lines (bezier reading guides) ────────
// ════════════════════════════════════════════════

setGuideMode(): void {
  this.canvas.selection = false;
  this.setAllRectsSelectableState(false);
  this.canvas.defaultCursor = 'crosshair';
  this.guideDrawState = 'idle';
  this.guideStartPoint = null;
  // Unfreeze any guides left in a half-drawn state from a previous
  // session (e.g. user clicked once, switched modes, came back). No-op
  // when nothing is frozen.
  this._freezeGuidesForDrawing(false);

  // Only the currently-selected guide (if any) shows its handles. Showing
  // handles for every existing guide on mode entry made loaded lines look
  // like they were all "activated" — the user couldn't tell which one
  // their next color/opacity/stroke change would apply to.
  this.guides.forEach(g => {
    this.showGuideHandles(g.data.id, this.selectedGuideId === g.data.id);
  });

  const self = this;

  this.canvas.on('mouse:down', (opt) => {
    const evt = opt.e as MouseEvent;

    // Middle mouse or space = panning
    if (evt.button === 1 || (this.spacePressed && evt.button === 0)) {
      this.isPanning = true;
      this.lastPanPosition = { x: evt.clientX, y: evt.clientY };
      this.canvas.defaultCursor = 'grabbing';
      return;
    }

    // Right click on guide = add control point
    if (evt.button === 2) {
      evt.preventDefault();
      const pointer = this.canvas.getPointer(opt.e);
      this.addControlPointAtClick(pointer.x, pointer.y);
      return;
    }

    const pointer = this.canvas.getPointer(opt.e);
    const target = opt.target;

    // While drawing, the second click MUST complete the line — don't let
    // it get hijacked into selecting whatever guide happens to live under
    // the endpoint. At 20px stroke + 5px handles the catchment area is
    // large, so finishing a line near another guide's endpoint used to
    // silently select that other guide instead of placing the new one.
    if (this.guideDrawState !== 'placing') {
      // Click on a guide handle (circle with guideId data)
      if (target && target.data && target.data.guideId && target.data.handleType) {
        this.selectGuide(target.data.guideId);
        return;  // Let fabric handle the drag
      }

      // Click on a guide path
      if (target && target.data && target.data.guideId && target.data.type === 'guidePath') {
        this.selectGuide(target.data.guideId);
        return;
      }
    }

    // Drawing: first click sets start, second click sets end
    if (this.guideDrawState === 'idle') {
      this.guideStartPoint = { x: pointer.x, y: pointer.y };
      this.guideDrawState = 'placing';

      // Freeze all existing guides while drawing so they can't intercept
      // the second click (or change the cursor away from crosshair). With
      // 20px paths + 5px handles, the catchment area is large enough that
      // landing the endpoint near a sibling guide's endpoint used to get
      // hijacked into "select that guide" instead of completing the line.
      this._freezeGuidesForDrawing(true);

      // Create preview line
      this.guidePreviewLine = new fabric.Line(
        [pointer.x, pointer.y, pointer.x, pointer.y],
        {
          stroke: this.guideColor,
          strokeWidth: 2,
          strokeDashArray: [6, 4],
          selectable: false,
          evented: false,
          excludeFromExport: true,
          strokeUniform: true,
        }
      );
      this.canvas.add(this.guidePreviewLine);
    } else if (this.guideDrawState === 'placing') {
      // Second click: place the guide
      const guide = this.guideLineService.createGuide(
        this.guideStartPoint.x, this.guideStartPoint.y,
        pointer.x, pointer.y,
        this.guideColor, this.guideStrokeWidth
      );
      // Restore interactivity on the previously-frozen guides BEFORE
      // adding the new one — otherwise the new guide's own path/handles
      // would also start out frozen.
      this._freezeGuidesForDrawing(false);
      this.addGuideToCanvas(guide);
      this.selectGuide(guide.id);

      // Cleanup
      if (this.guidePreviewLine) {
        this.canvas.remove(this.guidePreviewLine);
        this.guidePreviewLine = null;
      }
      this.guideStartPoint = null;
      this.guideDrawState = 'idle';
      this.emitGuidesChanged();
    }
  });

  this.canvas.on('mouse:move', (opt) => {
    const evt = opt.e as MouseEvent;

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

    // Update preview line
    if (this.guideDrawState === 'placing' && this.guidePreviewLine) {
      const pointer = this.canvas.getPointer(opt.e);
      this.guidePreviewLine.set({ x2: pointer.x, y2: pointer.y });
      this.canvas.renderAll();
    }
  });

  this.canvas.on('mouse:up', (opt) => {
    if (this.isPanning) {
      this.isPanning = false;
      this.lastPanPosition = null;
      this.canvas.defaultCursor = 'crosshair';
      this.canvas.setViewportTransform(this.canvas.viewportTransform!);
      this.canvas.renderAll();
    }
  });

  // Suppress browser context menu on canvas
  const upperCanvas = this.canvas.getSelectionElement();
  if (upperCanvas) {
    upperCanvas.oncontextmenu = (e) => { e.preventDefault(); return false; };
  }
}

/** Add a fully rendered guide to the canvas. */
addGuideToCanvas(guide: GuideLineData): void {
  const svgPath = this.guideLineService.buildSvgPath(guide.points);
  if (!svgPath) return;

  const path = new fabric.Path(svgPath, {
    fill: '',
    stroke: guide.color,
    strokeWidth: guide.strokeWidth,
    strokeUniform: true,
    selectable: false,
    evented: true,
    objectCaching: false,
    data: { type: 'guidePath', guideId: guide.id },
  });

  this.canvas.add(path);

  // Create control point handles — they inherit the guide's color so
  // the user can tell at a glance which guide they're editing.
  const handles: fabric.Object[] = [];
  guide.points.forEach((pt, ptIdx) => {
    // On-curve point
    const anchor = this.createGuideHandle(pt.x, pt.y, guide.id, 'anchor', ptIdx, guide.color);
    handles.push(anchor);
    this.canvas.add(anchor);

    // cpBefore handle
    if (pt.cpBefore) {
      const cpb = this.createGuideHandle(pt.cpBefore.x, pt.cpBefore.y, guide.id, 'cpBefore', ptIdx, guide.color);
      handles.push(cpb);
      this.canvas.add(cpb);
      // Connector line from anchor to cpBefore
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpBefore.x, pt.cpBefore.y, guide.id, 'connBefore', ptIdx, guide.color);
      handles.push(line);
      this.canvas.add(line);
    }
    // cpAfter handle
    if (pt.cpAfter) {
      const cpa = this.createGuideHandle(pt.cpAfter.x, pt.cpAfter.y, guide.id, 'cpAfter', ptIdx, guide.color);
      handles.push(cpa);
      this.canvas.add(cpa);
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpAfter.x, pt.cpAfter.y, guide.id, 'connAfter', ptIdx, guide.color);
      handles.push(line);
      this.canvas.add(line);
    }
  });

  this.guides.set(guide.id, { data: guide, path, handles });
  this.canvas.renderAll();
}

// Handle circle radii. Used both when sizing the handles and when
// insetting the connector line endpoints so they touch the circle margin
// instead of passing through the centers.
private static readonly _ANCHOR_RADIUS = 5;
private static readonly _CP_RADIUS = 4;

/** Create a small draggable circle handle for a guide control point. */
private createGuideHandle(x: number, y: number, guideId: string, handleType: string, ptIndex: number, color?: string): fabric.Circle {
  const isAnchor = handleType === 'anchor';
  // The anchor stays in the solid guide color (it represents a point on
  // the path itself). The CP handle takes the same color the connector
  // line uses — luminance-flipped from the guide — so the connector +
  // ring read as a single "stem with bulb at the end" visual and never
  // blend into the path.
  const fallback = color || this.guideColor;
  const solid = this.solidifyColor(fallback);
  const { stroke: cpStroke } = this._connectorColorFor(fallback);
  const haloShadow = new fabric.Shadow({
    color: 'rgba(0, 0, 0, 0.85)',
    blur: 3,
    offsetX: 0,
    offsetY: 0,
  });
  const circle = new fabric.Circle({
    left: x,
    top: y,
    radius: isAnchor ? FabricCanvasComponent._ANCHOR_RADIUS : FabricCanvasComponent._CP_RADIUS,
    fill: isAnchor ? solid : '#FFF',
    stroke: isAnchor ? solid : cpStroke,
    strokeWidth: 1.5,
    strokeUniform: true,
    originX: 'center',
    originY: 'center',
    selectable: true,
    evented: true,
    hasBorders: false,
    hasControls: false,
    objectCaching: false,
    shadow: haloShadow,
    data: { guideId, handleType, ptIndex },
  });

  // Live update path while dragging (don't rebuild handles)
  circle.on('moving', () => {
    this.onGuideHandleDrag(guideId, handleType, ptIndex, circle.left, circle.top);
  });

  // Full rebuild after drag ends
  circle.on('modified', () => {
    this.rebuildGuideVisuals(guideId);
    this.emitGuidesChanged();
  });

  return circle;
}

/** Create a thin line connecting an anchor to its control handle. The
 *  line endpoints are inset by each circle's radius so the line ends at
 *  the margin of the anchor and CP circles instead of passing through
 *  their centers — same convention Illustrator/Photoshop use, and makes
 *  it visually obvious which CP a connector belongs to. */
private createHandleConnector(x1: number, y1: number, x2: number, y2: number,
                              guideId: string, connType: string, ptIndex: number,
                              color?: string): fabric.Line {
  const base = color || this.guideColor;
  const { stroke, halo } = this._connectorColorFor(base);
  const seg = this._insetLine(
    x1, y1, x2, y2,
    FabricCanvasComponent._ANCHOR_RADIUS,
    FabricCanvasComponent._CP_RADIUS,
  );
  return new fabric.Line([seg.x1, seg.y1, seg.x2, seg.y2], {
    stroke,
    strokeWidth: 1.5,
    shadow: new fabric.Shadow({ color: halo, blur: 2, offsetX: 0, offsetY: 0 }),
    strokeUniform: true,
    selectable: false,
    evented: false,
    objectCaching: false,
    data: { guideId, handleType: connType, ptIndex },
  });
}

/** Pull a line segment's endpoints inward by r1/r2 along its own direction.
 *  Returns a collapsed (zero-length) segment at the midpoint when the two
 *  circles overlap, so fabric doesn't render a line passing back through
 *  itself when the user drags a CP onto its anchor. */
private _insetLine(x1: number, y1: number, x2: number, y2: number,
                   r1: number, r2: number): { x1: number; y1: number; x2: number; y2: number } {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (len < r1 + r2 || len === 0) {
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    return { x1: mx, y1: my, x2: mx, y2: my };
  }
  const ux = dx / len;
  const uy = dy / len;
  return {
    x1: x1 + ux * r1,
    y1: y1 + uy * r1,
    x2: x2 - ux * r2,
    y2: y2 - uy * r2,
  };
}

/** Pick a connector stroke + halo that contrasts with the guide color.
 *  Returns the guide's hue shifted toward dark or light depending on the
 *  perceived luminance of the input — so the connector stays related to
 *  the guide (kept the affordance) but never identical (no blending into
 *  the path). Halo color flips so the connector itself stays readable. */
private _connectorColorFor(color: string): { stroke: string; halo: string } {
  // Parse R/G/B out of any hex / rgb() / rgba() input.
  let r = 255, g = 0, b = 255;
  const m = color.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (m) {
    r = +m[1]; g = +m[2]; b = +m[3];
  } else {
    const hex = color.startsWith('#') ? color.slice(1) : color;
    const expanded = hex.length === 3 ? hex.split('').map(c => c + c).join('') : hex;
    if (/^[0-9a-fA-F]{6}$/.test(expanded)) {
      r = parseInt(expanded.slice(0, 2), 16);
      g = parseInt(expanded.slice(2, 4), 16);
      b = parseInt(expanded.slice(4, 6), 16);
    }
  }
  // ITU-R BT.601 luma — good enough for "is this perceived as light?".
  const luma = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  let sr: number, sg: number, sb: number;
  if (luma > 0.55) {
    // Light guide → darken connector toward 25% brightness.
    sr = Math.round(r * 0.30);
    sg = Math.round(g * 0.30);
    sb = Math.round(b * 0.30);
  } else {
    // Dark guide → lighten connector by mixing 65% toward white.
    sr = Math.round(r + (255 - r) * 0.65);
    sg = Math.round(g + (255 - g) * 0.65);
    sb = Math.round(b + (255 - b) * 0.65);
  }
  // Halo flips relative to the connector's own lightness, not the guide's,
  // since the connector is what needs framing against the background.
  const connectorLuma = (0.299 * sr + 0.587 * sg + 0.114 * sb) / 255;
  const halo = connectorLuma > 0.55
    ? 'rgba(0, 0, 0, 0.85)'
    : 'rgba(255, 255, 255, 0.9)';
  return { stroke: `rgb(${sr}, ${sg}, ${sb})`, halo };
}

/** Handle dragging of a guide control point — update path in-place without rebuilding handles. */
private onGuideHandleDrag(guideId: string, handleType: string, ptIndex: number, newX: number, newY: number): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;

  const pt = entry.data.points[ptIndex];
  if (!pt) return;

  const RA = FabricCanvasComponent._ANCHOR_RADIUS;
  const RC = FabricCanvasComponent._CP_RADIUS;

  if (handleType === 'anchor') {
    const dx = newX - pt.x;
    const dy = newY - pt.y;
    pt.x = newX;
    pt.y = newY;
    if (pt.cpBefore) { pt.cpBefore.x += dx; pt.cpBefore.y += dy; }
    if (pt.cpAfter) { pt.cpAfter.x += dx; pt.cpAfter.y += dy; }

    // Move related handles (cpBefore, cpAfter, connectors) along with anchor
    entry.handles.forEach(h => {
      if (!h.data || h.data.ptIndex !== ptIndex) return;
      if (h.data.handleType === 'cpBefore' && pt.cpBefore) {
        h.set({ left: pt.cpBefore.x, top: pt.cpBefore.y });
        h.setCoords();
      } else if (h.data.handleType === 'cpAfter' && pt.cpAfter) {
        h.set({ left: pt.cpAfter.x, top: pt.cpAfter.y });
        h.setCoords();
      } else if (h.data.handleType === 'connBefore' && pt.cpBefore) {
        const s = this._insetLine(pt.x, pt.y, pt.cpBefore.x, pt.cpBefore.y, RA, RC);
        (h as any).set({ x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2 });
      } else if (h.data.handleType === 'connAfter' && pt.cpAfter) {
        const s = this._insetLine(pt.x, pt.y, pt.cpAfter.x, pt.cpAfter.y, RA, RC);
        (h as any).set({ x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2 });
      }
    });
  } else if (handleType === 'cpBefore') {
    pt.cpBefore = { x: newX, y: newY };
    // Update connector line — inset both endpoints so the line still
    // touches the margin of the anchor + CP circles, not their centers.
    entry.handles.forEach(h => {
      if (h.data && h.data.ptIndex === ptIndex && h.data.handleType === 'connBefore') {
        const s = this._insetLine(pt.x, pt.y, newX, newY, RA, RC);
        (h as any).set({ x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2 });
      }
    });
  } else if (handleType === 'cpAfter') {
    pt.cpAfter = { x: newX, y: newY };
    entry.handles.forEach(h => {
      if (h.data && h.data.ptIndex === ptIndex && h.data.handleType === 'connAfter') {
        const s = this._insetLine(pt.x, pt.y, newX, newY, RA, RC);
        (h as any).set({ x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2 });
      }
    });
  }

  // Update just the SVG path (replace path object but keep handles alive)
  this.updateGuidePath(guideId);
}

/** Update only the SVG path of a guide without touching handles. */
private updateGuidePath(guideId: string): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;

  const svgPath = this.guideLineService.buildSvgPath(entry.data.points);
  this.canvas.remove(entry.path);
  const newPath = new fabric.Path(svgPath, {
    fill: '',
    stroke: entry.data.color,
    strokeWidth: entry.data.strokeWidth,
    strokeUniform: true,
    selectable: false,
    evented: true,
    objectCaching: false,
    data: { type: 'guidePath', guideId },
  });
  this.canvas.add(newPath);
  // Send path behind handles
  newPath.sendToBack();
  entry.path = newPath;
  // Re-apply the selection glow if this is the currently-selected guide
  // (the previous path object had it, but it was destroyed by the recreate).
  if (this.selectedGuideId === guideId) {
    this._applySelectionStyle(guideId, true);
  }
  this.canvas.renderAll();
}

/** Full rebuild of path + handles (used after drag end, nudge, split). */
private rebuildGuideVisuals(guideId: string): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;

  // Remove old path + handles
  this.canvas.remove(entry.path);
  entry.handles.forEach(h => this.canvas.remove(h));
  entry.handles = [];

  // Recreate path
  const svgPath = this.guideLineService.buildSvgPath(entry.data.points);
  const newPath = new fabric.Path(svgPath, {
    fill: '',
    stroke: entry.data.color,
    strokeWidth: entry.data.strokeWidth,
    strokeUniform: true,
    selectable: false,
    evented: true,
    objectCaching: false,
    data: { type: 'guidePath', guideId },
  });
  this.canvas.add(newPath);
  entry.path = newPath;

  // Recreate handles — pass the guide's current color so the visuals stay
  // in sync after a color change.
  const guideColor = entry.data.color;
  entry.data.points.forEach((pt, ptIdx) => {
    const anchor = this.createGuideHandle(pt.x, pt.y, guideId, 'anchor', ptIdx, guideColor);
    entry.handles.push(anchor);
    this.canvas.add(anchor);

    if (pt.cpBefore) {
      const cpb = this.createGuideHandle(pt.cpBefore.x, pt.cpBefore.y, guideId, 'cpBefore', ptIdx, guideColor);
      entry.handles.push(cpb);
      this.canvas.add(cpb);
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpBefore.x, pt.cpBefore.y, guideId, 'connBefore', ptIdx, guideColor);
      entry.handles.push(line);
      this.canvas.add(line);
    }
    if (pt.cpAfter) {
      const cpa = this.createGuideHandle(pt.cpAfter.x, pt.cpAfter.y, guideId, 'cpAfter', ptIdx, guideColor);
      entry.handles.push(cpa);
      this.canvas.add(cpa);
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpAfter.x, pt.cpAfter.y, guideId, 'connAfter', ptIdx, guideColor);
      entry.handles.push(line);
      this.canvas.add(line);
    }
  });

  // Show/hide handles based on selection
  const showHandles = this.selectedGuideId === guideId;
  entry.handles.forEach(h => h.set({ visible: showHandles, selectable: showHandles, evented: showHandles }));
  // Re-apply selection glow to the rebuilt path if this is the active guide.
  if (showHandles) {
    this._applySelectionStyle(guideId, true);
  }

  this.canvas.renderAll();
}

/** Select a guide (show its handles, enable nudge/delete). */
selectGuide(guideId: string): void {
  // Deselect previous
  if (this.selectedGuideId && this.selectedGuideId !== guideId) {
    this.showGuideHandles(this.selectedGuideId, false);
    this._applySelectionStyle(this.selectedGuideId, false);
  }
  this.selectedGuideId = guideId;
  this.showGuideHandles(guideId, true);
  this._applySelectionStyle(guideId, true);

  // Update guide color selector to match the selected guide. Sync the
  // Custom-picker draft too so the hex picker and alpha slider snap to
  // what's actually on the canvas — without this, dragging the alpha
  // slider starts from a stale value (the previous selection) rather than
  // the selected guide's real opacity.
  const entry = this.guides.get(guideId);
  if (entry) {
    this.guideColor = entry.data.color;
    this.guideHexColor = this.rgbaToHex(entry.data.color);
    this.syncDraftFromColor(entry.data.color);
  }
  this.canvas.renderAll();
}

/** Deselect any selected guide. */
deselectGuide(): void {
  if (this.selectedGuideId) {
    this.showGuideHandles(this.selectedGuideId, false);
    this._applySelectionStyle(this.selectedGuideId, false);
    this.selectedGuideId = null;
    this.canvas.renderAll();
  }
}

/** Toggle the selection-emphasis style on a guide's path. Adds a soft
 *  white glow via fabric.Shadow so the user can tell at a glance which
 *  line they're editing — visible handles alone are too small to spot
 *  when several guides overlap or sit close together. */
private _applySelectionStyle(guideId: string, selected: boolean): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;
  if (selected) {
    entry.path.set({
      shadow: new fabric.Shadow({
        color: 'rgba(255, 255, 255, 0.9)',
        blur: 10,
        offsetX: 0,
        offsetY: 0,
      }),
    });
  } else {
    entry.path.set({ shadow: null as any });
  }
}

/** Show or hide handles for a guide. */
private showGuideHandles(guideId: string, show: boolean): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;
  entry.handles.forEach(h => {
    h.set({ visible: show, selectable: show, evented: show });
  });
}

/** Remove a guide from canvas and data. */
removeGuide(guideId: string): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;
  this.canvas.remove(entry.path);
  entry.handles.forEach(h => this.canvas.remove(h));
  this.guides.delete(guideId);
  if (this.selectedGuideId === guideId) {
    this.selectedGuideId = null;
  }
  this.canvas.renderAll();
  this.emitGuidesChanged();
}

/** Nudge the selected guide up or down. */
nudgeSelectedGuide(dy: number): void {
  if (!this.selectedGuideId) return;
  const entry = this.guides.get(this.selectedGuideId);
  if (!entry) return;
  entry.data = this.guideLineService.nudgeGuide(entry.data, dy);
  this.rebuildGuideVisuals(this.selectedGuideId);
  this.emitGuidesChanged();
}

/** Right-click to add a control point on the closest segment. */
private addControlPointAtClick(px: number, py: number): void {
  // Find the closest guide path
  let bestGuideId: string | null = null;
  let bestSeg = 0;
  let bestT = 0.5;
  let bestDist = Infinity;

  this.guides.forEach((entry, id) => {
    const result = this.guideLineService.findClosestSegment(entry.data, px, py);
    if (result.distance < bestDist) {
      bestDist = result.distance;
      bestGuideId = id;
      bestSeg = result.segIndex;
      bestT = result.t;
    }
  });

  const zoom = this.canvas ? this.canvas.getZoom() : 1;
  if (bestGuideId && bestDist < 30 / zoom) {
    const entry = this.guides.get(bestGuideId);
    entry.data = this.guideLineService.splitSegment(entry.data, bestSeg, bestT);
    this.selectGuide(bestGuideId);
    this.rebuildGuideVisuals(bestGuideId);
    this.emitGuidesChanged();
  }
}

/** Update the color of the selected guide. When no guide is selected this
 *  only updates the brush state (`guideColor`/`guideHexColor`/recents) for
 *  the next-drawn line — existing guides are NOT touched. Previously the
 *  "no selection" fallback would recolor every guide on the canvas, which
 *  was confusing when the user opened an image with previously-drawn guides
 *  and just wanted to set the color for their next line.
 *
 *  `trackRecent: false` skips the recent-strip update — used by live-
 *  preview paths (dragging the alpha slider, scrubbing the picker) so
 *  transient hues don't pollute recents. */
setSelectedGuideColor(color: string, trackRecent: boolean = true): void {
  this.guideColor = color;
  this.guideHexColor = this.rgbaToHex(color);
  if (trackRecent) {
    this.guideLineService.addRecentColor(color);
  }
  if (!this.selectedGuideId) return;
  const entry = this.guides.get(this.selectedGuideId);
  if (!entry) return;
  entry.data.color = color;
  entry.path.set({ stroke: color });
  // Refresh handle colors so they track the guide's new stroke color
  // instead of staying on the previous (or hardcoded) hue.
  this.refreshHandleColors(entry.data.id);
  this.canvas.renderAll();
  this.emitGuidesChanged();
}

/** Temporarily disable (or restore) interaction on every existing guide
 *  path and handle. Called around the two-click guide-draw sequence so
 *  the second click can land anywhere — even on top of a sibling guide's
 *  thick stroke or visible handles — without fabric stealing the cursor
 *  or the event. We snapshot the previous `evented`/`selectable` flags
 *  per object so the restore call can put them back exactly as they were
 *  (handles for non-selected guides are normally non-evented too). */
private _frozenGuideObjects: Array<{ obj: fabric.Object; selectable: boolean; evented: boolean }> = [];
private _freezeGuidesForDrawing(freeze: boolean): void {
  if (freeze) {
    this._frozenGuideObjects = [];
    this.guides.forEach(entry => {
      const objs: fabric.Object[] = [entry.path, ...entry.handles];
      for (const obj of objs) {
        this._frozenGuideObjects.push({
          obj,
          selectable: !!obj.selectable,
          evented: !!obj.evented,
        });
        obj.set({ selectable: false, evented: false });
      }
    });
  } else {
    for (const snap of this._frozenGuideObjects) {
      snap.obj.set({ selectable: snap.selectable, evented: snap.evented });
    }
    this._frozenGuideObjects = [];
  }
}

/** Update the fill/stroke of an existing guide's handles in place — used
 *  after a color change so we don't have to remove/recreate the fabric
 *  objects (which would flicker and reset interaction state). */
private refreshHandleColors(guideId: string): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;
  const color = entry.data.color;
  const solid = this.solidifyColor(color);
  // Connector gets a luminance-flipped tint + matching halo so it stays
  // distinct from the path even when both share the guide's hue.
  const { stroke: connectorStroke, halo: connectorHalo } = this._connectorColorFor(color);
  for (const h of entry.handles) {
    const data: any = (h as any).data || {};
    const type = data.handleType;
    if (type === 'anchor') {
      h.set({ fill: solid, stroke: solid });
    } else if (type === 'cpBefore' || type === 'cpAfter') {
      // CP ring now shares the connector color (luminance-flipped from the
      // guide) so the stem-and-bulb reads as one unit.
      h.set({ stroke: connectorStroke });
    } else if (type === 'connBefore' || type === 'connAfter') {
      h.set({
        stroke: connectorStroke,
        shadow: new fabric.Shadow({ color: connectorHalo, blur: 2, offsetX: 0, offsetY: 0 }),
      });
    }
  }
}

/** Handle color picker input (hex → rgba). DEPRECATED — left in place for
 *  any external callers; new picker UI uses the draft methods below so we
 *  no longer commit (and pollute recents) on every cursor wiggle. */
onGuideColorInput(event: Event): void {
  const hex = (event.target as HTMLInputElement).value;
  this.guideHexColor = hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const rgba = `rgba(${r}, ${g}, ${b}, 0.6)`;
  this.setSelectedGuideColor(rgba);
}

/** Update the draft hex and live-preview it on the selected guide (no
 *  recents added — that only happens on Add). */
setDraftHex(event: Event): void {
  this.draftHex = (event.target as HTMLInputElement).value;
  if (this.selectedGuideId) {
    this.setSelectedGuideColor(this._draftToRgba(), false);
  }
}

/** Update the draft alpha (0–100 from the slider) and live-preview it on
 *  the selected guide so the user sees transparency change as they drag. */
setDraftAlphaPct(event: Event): void {
  const raw = (event.target as HTMLInputElement).value;
  const n = parseInt(raw, 10);
  if (!isNaN(n)) this.draftAlphaPct = Math.max(0, Math.min(100, n));
  if (this.selectedGuideId) {
    this.setSelectedGuideColor(this._draftToRgba(), false);
  }
}

/** Commit the draft hex+alpha as a guide color: apply (or re-apply) it and
 *  add it to the recent strip. This is the only path that touches recents
 *  in the custom-picker flow. */
applyDraftColor(): void {
  this.setSelectedGuideColor(this._draftToRgba(), true);
}

/** Build an rgba() string from the current draft state. */
private _draftToRgba(): string {
  const hex = this.draftHex || '#ff00ff';
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const a = Math.max(0, Math.min(1, this.draftAlphaPct / 100));
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/** Populate draft hex+alpha from a stored guide color so the custom picker
 *  reflects whatever the user just selected. Accepts `#hex` or `rgb()`/
 *  `rgba()` input — alpha defaults to 100% when not present. */
private syncDraftFromColor(color: string): void {
  this.draftHex = this.rgbaToHex(color);
  const m = color.match(/rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d.]+)\s*\)/);
  this.draftAlphaPct = m ? Math.round(parseFloat(m[1]) * 100) : 100;
}

/** Update opacity of the selected guide, or all guides if none selected. */
/** Update opacity of the selected guide only. No-op when nothing is
 *  selected — the slider in that case is purely informational. */
setGuideOpacity(opacity: number): void {
  if (!this.selectedGuideId) return;
  const entry = this.guides.get(this.selectedGuideId);
  if (!entry) return;
  entry.path.set({ opacity });
  this.canvas.renderAll();
  this.emitGuidesChanged();
}

/** Update stroke width. When a guide is selected, applies to it; otherwise
 *  just updates `guideStrokeWidth` so the NEXT-drawn line uses this width
 *  (existing guides stay untouched). */
setGuideStrokeWidth(width: number): void {
  this.guideStrokeWidth = width;
  if (!this.selectedGuideId) return;
  const entry = this.guides.get(this.selectedGuideId);
  if (!entry) return;
  entry.data.strokeWidth = width;
  entry.path.set({ strokeWidth: width });
  this.canvas.renderAll();
  this.emitGuidesChanged();
}

/** Return `color` as an opaque (or alpha-overridden) `rgb()` / `rgba()`
 *  string. Accepts hex (`#RRGGBB`), `rgb(...)`, or `rgba(...)` input.
 *  Used for guide handles so they render at full opacity even though
 *  the guide line itself uses a low-alpha stroke for see-through reading. */
private solidifyColor(color: string, alpha: number = 1): string {
  if (!color) return alpha === 1 ? 'rgb(255, 0, 255)' : `rgba(255, 0, 255, ${alpha})`;
  // rgb()/rgba() — pull the first three numeric channels
  const rgbaMatch = color.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (rgbaMatch) {
    const [, r, g, b] = rgbaMatch;
    return alpha === 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  // Hex (#RGB or #RRGGBB)
  const hex = color.startsWith('#') ? color.slice(1) : color;
  const expanded = hex.length === 3
    ? hex.split('').map(c => c + c).join('')
    : hex;
  if (/^[0-9a-fA-F]{6}$/.test(expanded)) {
    const r = parseInt(expanded.slice(0, 2), 16);
    const g = parseInt(expanded.slice(2, 4), 16);
    const b = parseInt(expanded.slice(4, 6), 16);
    return alpha === 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return color;
}

private rgbaToHex(rgba: string): string {
  const match = rgba.match(/\d+/g);
  if (!match || match.length < 3) return '#ff00ff';
  const r = parseInt(match[0]).toString(16).padStart(2, '0');
  const g = parseInt(match[1]).toString(16).padStart(2, '0');
  const b = parseInt(match[2]).toString(16).padStart(2, '0');
  return `#${r}${g}${b}`;
}

/** Get all guides as serializable data. */
getGuides(): GuideLineData[] {
  return Array.from(this.guides.values()).map(e => e.data);
}

/** Load guides from saved data. */
loadGuides(guidesData: GuideLineData[]): void {
  // Clear existing guides
  this.clearGuides();
  if (!guidesData || !guidesData.length) return;
  guidesData.forEach(g => {
    this.addGuideToCanvas(g);
    this.showGuideHandles(g.id, false);  // Start with handles hidden
  });
}

/** Remove all guides from canvas. */
clearGuides(): void {
  this.guides.forEach((entry) => {
    this.canvas.remove(entry.path);
    entry.handles.forEach(h => this.canvas.remove(h));
  });
  this.guides.clear();
  this.selectedGuideId = null;
  if (this.guidePreviewLine) {
    this.canvas.remove(this.guidePreviewLine);
    this.guidePreviewLine = null;
  }
  this.guideDrawState = 'idle';
  this.guideStartPoint = null;
}

private emitGuidesChanged(): void {
  this.guidesChanged.emit(this.getGuides());
}

}
