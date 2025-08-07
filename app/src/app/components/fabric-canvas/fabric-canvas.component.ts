import { AfterContentChecked, AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter, Input, Output, ViewChild } from '@angular/core';
import { fabric } from 'fabric';
import { Point, Rect } from 'fabric/fabric-impl';
import { Index, LineStats } from 'src/app/models/letter';
import { ShortcutInput, ShortcutEventOutput, KeyboardShortcutsComponent, AllowIn } from "ng-keyboard-shortcuts";  
import { NotificationService } from 'src/app/services/notification.service';



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
    this.addMode
  ]

  private tempTemplate = null;
 
  private newRect = null;
  private deleteLine: fabric.Line = null;
  
  public RECT_STROKE_WIDTH = 1;
  public DEFAULT_RECT_FILL = "rgba(0,0,255,0.1)"


  private mode: CanvasMode = CanvasMode.Pan;

  constructor(private cdref: ChangeDetectorRef,
    public notificationService: NotificationService) {}

  ngAfterViewInit(): void {
    this.initAll();
    this.cdref.detectChanges();
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
      }
    )
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

  initAll() {
    this.canvas = new fabric.Canvas(this.htmlCanvas.nativeElement, {
      hoverCursor: 'pointer',
      selectionBorderColor: 'blue',
      backgroundColor: '#ebebef',
      preserveObjectStacking: true,
    });
    
    if(this.canvasType) {
      this.updateActionsAccordingToType();
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
  }

  getCanvas() {
    return this.canvas;
  }

  clearCanvas() {
    this.canvas.clear();
    this.canvas.setBackgroundColor("#ebebef", undefined);
  }

  forceZoomOut(zoom=0.3) {
    this.canvas.zoomToPoint({ x: 0, y: 0} as Point, zoom);
  }

  setWheelZooming() {
    this.canvas.on('mouse:wheel', (opt) => {
      let wheelEvent = (opt.e as unknown) as WheelEvent;
      const delta = wheelEvent.deltaY
      
      let zoom = this.canvas.getZoom();
      zoom *= 0.999 ** delta;
      if (zoom > this.props.maxZoom) zoom = this.props.maxZoom;
      if (zoom < this.props.minZoom) zoom = this.props.minZoom;
      this.canvas.zoomToPoint({ x: wheelEvent.offsetX, y: wheelEvent.offsetY } as Point, zoom);

      opt.e.preventDefault();
      opt.e.stopPropagation();
    })
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
    if(this.canvasType == CanvasType.Drawing) return;

    let self = this;
    let isMouseDown = false;

    this.canvas.on('mouse:down', function(opt) {    
      isMouseDown = true;

      let mouseEvent = (opt.e as unknown) as MouseEvent;
      this.lastPosX = mouseEvent.clientX;
      this.lastPosY = mouseEvent.clientY;
    });

    this.canvas.on('mouse:move', function(opt) {
      if (isMouseDown) {
        let mouseEvent = (opt.e as unknown) as MouseEvent;
        var vpt = this.viewportTransform;
        
        vpt[4] += mouseEvent.clientX - this.lastPosX;
        vpt[5] += mouseEvent.clientY - this.lastPosY;
        this.requestRenderAll();

        this.lastPosX = mouseEvent.clientX;
        this.lastPosY = mouseEvent.clientY;
      }
    });

    this.canvas.on('mouse:up', function(opt) {
      // on mouse up we want to recalculate new interaction
      // for all objects, so we call setViewportTransform
      this.setViewportTransform(this.viewportTransform);
      isMouseDown = false;
    });

    this.canvas.on('selection:created', function(obj) {
      let possiblyRect = (obj['selected'][0] as fabric.Rect);
      if(possiblyRect.type == "text") return;
      self.emitSelectionChanged(possiblyRect.data.index);
    });

    this.canvas.on('selection:updated', function(obj) {
      let possiblyRect = (obj['selected'][0] as fabric.Rect);
      if(possiblyRect.type == "text") return;
      self.emitSelectionChanged(possiblyRect.data.index);
    });

    this.canvas.on('selection:cleared', function(obj) {
      self.emitSelectionClear();
    });
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
        self.newRect = self.makeRectangle(originX, originY, pointer.x-originX, pointer.y-originY, self.DEFAULT_RECT_FILL, 'blue', false);
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
      if(self.canvasType == CanvasType.SingleSelection) {
        self.changeMode(CanvasMode.Pan);
      }
    });    
  }

makeRectangle(left: number, top: number, width: number, height: number, fill: string = 'rgba(0,0,255,0.1)',
  stroke: string = 'blue', addListeners: boolean = true, index: Index = null, trustedDimensions: boolean = false) {
  if(!trustedDimensions) {
    if(left < 0) left = 0;
    if(top < 0) top = 0;
    let canvasWidth = this.canvasContainer.nativeElement.offsetWidth - 30;
    if(left + width > canvasWidth) width = canvasWidth - left;
  }

  let newRect = new fabric.Rect({
    data: index,
    left: left,
    top: top,
    originX: 'left',
    originY: 'top',
    width: width,
    height: height,
    angle: 0,
    fill: fill,
    selectionBackgroundColor: 'rgba(0,255,0,0.3)',
    stroke: stroke,
    strokeWidth: this.RECT_STROKE_WIDTH,
    strokeUniform: true,
    transparentCorners: false
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
        self.emitSelectionChanged(rect.data.index);
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

    if(self.mode == CanvasMode.Delete || ((self.mode == CanvasMode.Combine || self.mode == CanvasMode.Mark) && !rect.data.selectedForAction)) {
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

      self.boxDeleted.emit(rect.data.index);
      self.boxAdded.emit(rightRect);
      self.boxAdded.emit(leftRect);

      self.deleteLine = null;
      self.canvas.renderAll();
      this.setAllRectsSelectableState(false);
      // self.changeMode(CanvasMode.Pan);
    }

    if(self.mode == CanvasMode.Delete) {
      self.canvas.remove(rect);
      self.boxDeleted.emit(rect.data.index);
      rect = null;
    }
    
    else if(self.mode == CanvasMode.Combine || self.mode == CanvasMode.Mark) {
      self.boxMarkToggle.emit(rect.data.index);
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
      rect.set("stroke", 'blue');
      break;
    case RectColor.Delete:
      rect.set("fill", 'rgba(255,0,0,0.1)');
      rect.set("stroke", 'red');
      break;
    case RectColor.Mark:
      rect.set("fill", 'rgba(200,255,0,0.2)');
      rect.set("stroke", 'black');
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
