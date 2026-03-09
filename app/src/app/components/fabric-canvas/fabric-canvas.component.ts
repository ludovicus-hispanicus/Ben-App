import { AfterContentChecked, AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter, HostListener, Input, Output, ViewChild } from '@angular/core';
import { fabric } from 'fabric';
import { Point, Rect } from 'fabric/fabric-impl';
import { Index, LineStats } from 'src/app/models/letter';
import { ShortcutInput, ShortcutEventOutput, KeyboardShortcutsComponent, AllowIn } from "ng-keyboard-shortcuts";
import { NotificationService } from 'src/app/services/notification.service';
import { CanvasBoxService } from 'src/app/services/canvas-box.service';



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
  AddTemplate = "AddTemplate"
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
    this.deleteMode
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

  constructor(
    private cdref: ChangeDetectorRef,
    public notificationService: NotificationService,
    private canvasBoxService: CanvasBoxService
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
      }
    )
  }

  deleteActiveObject() {
    console.log('[DELETE] deleteActiveObject called');
    let activeObj = this.canvas.getActiveObject();
    console.log('[DELETE] activeObj:', activeObj);
    if (activeObj) {
      console.log('[DELETE] type:', activeObj.type, 'data:', activeObj.data);
    }
    if (activeObj && activeObj.type === 'rect') {
      console.log('[DELETE] Removing rect from canvas');
      this.canvas.remove(activeObj);
      this.canvas.discardActiveObject();
      this.canvas.requestRenderAll();
      if (activeObj.data) {
        console.log('[DELETE] Emitting boxDeleted with index:', activeObj.data.index);
        this.boxDeleted.emit(activeObj.data.index);
      }
    } else {
      console.log('[DELETE] No active rect to delete');
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


}
