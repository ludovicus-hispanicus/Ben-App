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
  public guideColor: string = 'rgba(255, 165, 0, 0.4)';
  public guideHexColor: string = '#ffa500';
  public guideStrokeWidth: number = 3;

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

  // Show existing guide handles
  this.guides.forEach(g => this.showGuideHandles(g.data.id, true));

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

    // Drawing: first click sets start, second click sets end
    if (this.guideDrawState === 'idle') {
      this.guideStartPoint = { x: pointer.x, y: pointer.y };
      this.guideDrawState = 'placing';

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

  // Create control point handles
  const handles: fabric.Object[] = [];
  guide.points.forEach((pt, ptIdx) => {
    // On-curve point
    const anchor = this.createGuideHandle(pt.x, pt.y, guide.id, 'anchor', ptIdx);
    handles.push(anchor);
    this.canvas.add(anchor);

    // cpBefore handle
    if (pt.cpBefore) {
      const cpb = this.createGuideHandle(pt.cpBefore.x, pt.cpBefore.y, guide.id, 'cpBefore', ptIdx);
      handles.push(cpb);
      this.canvas.add(cpb);
      // Connector line from anchor to cpBefore
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpBefore.x, pt.cpBefore.y, guide.id, 'connBefore', ptIdx);
      handles.push(line);
      this.canvas.add(line);
    }
    // cpAfter handle
    if (pt.cpAfter) {
      const cpa = this.createGuideHandle(pt.cpAfter.x, pt.cpAfter.y, guide.id, 'cpAfter', ptIdx);
      handles.push(cpa);
      this.canvas.add(cpa);
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpAfter.x, pt.cpAfter.y, guide.id, 'connAfter', ptIdx);
      handles.push(line);
      this.canvas.add(line);
    }
  });

  this.guides.set(guide.id, { data: guide, path, handles });
  this.canvas.renderAll();
}

/** Create a small draggable circle handle for a guide control point. */
private createGuideHandle(x: number, y: number, guideId: string, handleType: string, ptIndex: number): fabric.Circle {
  const isAnchor = handleType === 'anchor';
  const circle = new fabric.Circle({
    left: x,
    top: y,
    radius: isAnchor ? 5 : 4,
    fill: isAnchor ? '#FF9800' : '#FFF',
    stroke: '#FF9800',
    strokeWidth: 1.5,
    strokeUniform: true,
    originX: 'center',
    originY: 'center',
    selectable: true,
    evented: true,
    hasBorders: false,
    hasControls: false,
    objectCaching: false,
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

/** Create a thin line connecting an anchor to its control handle. */
private createHandleConnector(x1: number, y1: number, x2: number, y2: number,
                              guideId: string, connType: string, ptIndex: number): fabric.Line {
  return new fabric.Line([x1, y1, x2, y2], {
    stroke: 'rgba(255, 152, 0, 0.5)',
    strokeWidth: 1,
    strokeUniform: true,
    selectable: false,
    evented: false,
    objectCaching: false,
    data: { guideId, handleType: connType, ptIndex },
  });
}

/** Handle dragging of a guide control point — update path in-place without rebuilding handles. */
private onGuideHandleDrag(guideId: string, handleType: string, ptIndex: number, newX: number, newY: number): void {
  const entry = this.guides.get(guideId);
  if (!entry) return;

  const pt = entry.data.points[ptIndex];
  if (!pt) return;

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
        (h as any).set({ x1: pt.x, y1: pt.y, x2: pt.cpBefore.x, y2: pt.cpBefore.y });
      } else if (h.data.handleType === 'connAfter' && pt.cpAfter) {
        (h as any).set({ x1: pt.x, y1: pt.y, x2: pt.cpAfter.x, y2: pt.cpAfter.y });
      }
    });
  } else if (handleType === 'cpBefore') {
    pt.cpBefore = { x: newX, y: newY };
    // Update connector line
    entry.handles.forEach(h => {
      if (h.data && h.data.ptIndex === ptIndex && h.data.handleType === 'connBefore') {
        (h as any).set({ x2: newX, y2: newY });
      }
    });
  } else if (handleType === 'cpAfter') {
    pt.cpAfter = { x: newX, y: newY };
    entry.handles.forEach(h => {
      if (h.data && h.data.ptIndex === ptIndex && h.data.handleType === 'connAfter') {
        (h as any).set({ x2: newX, y2: newY });
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

  // Recreate handles
  entry.data.points.forEach((pt, ptIdx) => {
    const anchor = this.createGuideHandle(pt.x, pt.y, guideId, 'anchor', ptIdx);
    entry.handles.push(anchor);
    this.canvas.add(anchor);

    if (pt.cpBefore) {
      const cpb = this.createGuideHandle(pt.cpBefore.x, pt.cpBefore.y, guideId, 'cpBefore', ptIdx);
      entry.handles.push(cpb);
      this.canvas.add(cpb);
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpBefore.x, pt.cpBefore.y, guideId, 'connBefore', ptIdx);
      entry.handles.push(line);
      this.canvas.add(line);
    }
    if (pt.cpAfter) {
      const cpa = this.createGuideHandle(pt.cpAfter.x, pt.cpAfter.y, guideId, 'cpAfter', ptIdx);
      entry.handles.push(cpa);
      this.canvas.add(cpa);
      const line = this.createHandleConnector(pt.x, pt.y, pt.cpAfter.x, pt.cpAfter.y, guideId, 'connAfter', ptIdx);
      entry.handles.push(line);
      this.canvas.add(line);
    }
  });

  // Show/hide handles based on selection
  const showHandles = this.selectedGuideId === guideId;
  entry.handles.forEach(h => h.set({ visible: showHandles, selectable: showHandles, evented: showHandles }));

  this.canvas.renderAll();
}

/** Select a guide (show its handles, enable nudge/delete). */
selectGuide(guideId: string): void {
  // Deselect previous
  if (this.selectedGuideId && this.selectedGuideId !== guideId) {
    this.showGuideHandles(this.selectedGuideId, false);
  }
  this.selectedGuideId = guideId;
  this.showGuideHandles(guideId, true);

  // Update guide color selector to match
  const entry = this.guides.get(guideId);
  if (entry) {
    this.guideColor = entry.data.color;
  }
  this.canvas.renderAll();
}

/** Deselect any selected guide. */
deselectGuide(): void {
  if (this.selectedGuideId) {
    this.showGuideHandles(this.selectedGuideId, false);
    this.selectedGuideId = null;
    this.canvas.renderAll();
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

/** Update the color of the selected guide, or all guides if none selected. */
setSelectedGuideColor(color: string): void {
  this.guideColor = color;
  this.guideHexColor = this.rgbaToHex(color);
  const targets = this.selectedGuideId
    ? [this.guides.get(this.selectedGuideId)].filter(Boolean)
    : Array.from(this.guides.values());
  if (!targets.length) return;
  targets.forEach(entry => {
    entry.data.color = color;
    entry.path.set({ stroke: color });
  });
  this.canvas.renderAll();
  this.emitGuidesChanged();
}

/** Handle color picker input (hex → rgba). */
onGuideColorInput(event: Event): void {
  const hex = (event.target as HTMLInputElement).value;
  this.guideHexColor = hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const rgba = `rgba(${r}, ${g}, ${b}, 0.6)`;
  this.setSelectedGuideColor(rgba);
}

/** Update opacity of the selected guide, or all guides if none selected. */
setGuideOpacity(opacity: number): void {
  const targets = this.selectedGuideId
    ? [this.guides.get(this.selectedGuideId)].filter(Boolean)
    : Array.from(this.guides.values());
  if (!targets.length) return;
  targets.forEach(entry => { entry.path.set({ opacity }); });
  this.canvas.renderAll();
  this.emitGuidesChanged();
}

/** Update stroke width of the selected guide, or all guides if none selected. */
setGuideStrokeWidth(width: number): void {
  this.guideStrokeWidth = width;
  const targets = this.selectedGuideId
    ? [this.guides.get(this.selectedGuideId)].filter(Boolean)
    : Array.from(this.guides.values());
  if (!targets.length) return;
  targets.forEach(entry => {
    entry.data.strokeWidth = width;
    entry.path.set({ strokeWidth: width });
  });
  this.canvas.renderAll();
  this.emitGuidesChanged();
}

private rgbaToHex(rgba: string): string {
  const match = rgba.match(/\d+/g);
  if (!match || match.length < 3) return '#ffa500';
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
