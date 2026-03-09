# Canvas Architecture (app)

> Reference document for AI agents. Describes the Fabric.js-based canvas system used for image viewing, annotation, and bounding-box editing across the Angular app in `app/`.

---

## File Map

```
app/src/app/
├── services/
│   └── canvas-box.service.ts          # Shared service – box creation, zoom/pan helpers
│
├── components/
│   ├── fabric-canvas/                 # Reusable canvas component (Fabric.js wrapper)
│   │   ├── fabric-canvas.component.ts
│   │   ├── fabric-canvas.component.html
│   │   ├── fabric-canvas.component.scss
│   │   └── fabric-canvas.module.ts
│   │
│   ├── cure-d/                        # CuReD – OCR training-data / transliteration tool
│   │   ├── cured.component.ts         # Uses <fabric-canvas> with SingleSelection & ViewAmendment
│   │   ├── cured.component.html
│   │   ├── cured.module.ts
│   │   └── text-editor/               # Sub-component for transliteration editing
│   │
│   ├── cure/                          # CuRe – Sign detection & classification
│   │   ├── cure.component.ts          # Uses <fabric-canvas> with SingleSelection
│   │   ├── cure.component.html
│   │   ├── cure.module.ts
│   │   └── ...
│   │
│   └── yolo-training/                 # YOLO dataset annotation tool
│       ├── yolo-training.component.ts # Parent – dataset management UI
│       ├── yolo-training.module.ts
│       └── annotation-canvas/         # Standalone canvas (does NOT use fabric-canvas component)
│           ├── annotation-canvas.component.ts
│           ├── annotation-canvas.component.html
│           └── annotation-canvas.component.scss
│
└── models/
    └── yolo-training.ts               # YoloClass, YoloAnnotation, Detection, CLASS_COLORS
```

---

## Routing

Defined in `app/src/app/app-routing.module.ts`:

| Route | Component | Canvas used |
|---|---|---|
| `/cured` | CuredComponent | `<fabric-canvas>` (SingleSelection / ViewAmendment) |
| `/training-data` | CuredComponent | same |
| `/training-data/:textId/:transId` | CuredComponent | same |
| `/training-data/:textId/:transId/:viewOnly` | CuredComponent | same |
| `/cure` | CureComponent | `<fabric-canvas>` (SingleSelection) |
| `/cure/editor` | CureComponent | same |
| `/yolo-training` | YoloTrainingComponent | `<app-annotation-canvas>` |

---

## Component Hierarchy

```
AppComponent
│
├─ CuredComponent (/cured, /training-data)
│  └─ <fabric-canvas>          [canvasType]="SingleSelection | ViewAmendment"
│     └─ CanvasBoxService
│
├─ CureComponent (/cure)
│  └─ <fabric-canvas>          [canvasType]="SingleSelection"
│     └─ CanvasBoxService
│
└─ YoloTrainingComponent (/yolo-training)
   └─ <app-annotation-canvas>  [datasetName] [classes]
      └─ CanvasBoxService
```

---

## 1. CanvasBoxService (shared service)

**File:** `services/canvas-box.service.ts`

Stateless utility injected by both canvas components. Provides consistent box styling and zoom/pan behavior across the app.

### Interfaces

```ts
interface BoxConfig {
  fill?: string;              // default 'rgba(0,0,255,0.2)'
  stroke?: string;            // default '#2196F3'
  strokeWidth?: number;       // default 2
  cornerSize?: number;        // default 12
  cornerColor?: string;       // default '#2196F3'
  cornerStrokeColor?: string; // default '#1565C0'
  data?: any;                 // arbitrary payload attached to the rect
}

interface ZoomPanConfig {
  minZoom: number;
  maxZoom: number;
}
```

### Public Methods

| Method | Signature | What it does |
|---|---|---|
| `createBox` | `(left, top, width, height, config?) → fabric.Rect` | Creates a styled rectangle. Disables rotation, enables 8 resize handles. |
| `setupWheelZoomPan` | `(canvas, config) → void` | Binds mouse-wheel events. Ctrl+wheel = zoom, plain wheel = pan. Detects trackpad pinch. |
| `setupMouseDragPan` | `(canvas, isPanningFn, getLastPos, setLastPos) → void` | Binds mouse-drag panning (for space-key or pan-mode). |
| `clampZoom` | `(zoom, config) → number` | Clamps zoom to min/max. |
| `zoomIn` | `(canvas, config, factor=1.2) → number` | Zooms in to canvas center. Returns new zoom. |
| `zoomOut` | `(canvas, config, factor=1.2) → number` | Zooms out from canvas center. Returns new zoom. |
| `resetZoom` | `(canvas, cW, cH, imgW, imgH) → number` | Fits image into canvas at 95% margin. |
| `isValidBoxSize` | `(rect, minSize=7) → boolean` | Returns false if rect is smaller than minSize px. |

---

## 2. FabricCanvasComponent (reusable)

**File:** `components/fabric-canvas/fabric-canvas.component.ts`
**Selector:** `<fabric-canvas>`
**Module:** `FabricCanvasModule`

Generic Fabric.js canvas wrapper. The parent component controls what it does via `canvasType`.

### Inputs / Outputs

```ts
// Inputs
@Input() canvasType: CanvasType;   // determines toolbar buttons & default mode
@Input() isLoading: boolean;       // shows spinner overlay

// Outputs
@Output() modeChange:        EventEmitter<string>;       // current mode name
@Output() selectionChange:   EventEmitter<number>;        // selected box index (or undefined)
@Output() boxDeleted:        EventEmitter<number>;        // deleted box index
@Output() boxAdded:          EventEmitter<fabric.Rect>;   // newly drawn rect
@Output() boxMarkToggle:     EventEmitter<fabric.Rect>;   // mark/unmark for combine
@Output() combineBoxesEmitter: EventEmitter<any>;         // combine button clicked
@Output() mouseUp:           EventEmitter<any>;           // mouse-up (drawing mode)
```

### CanvasType Enum

| Value | Default Mode | Toolbar Actions | Used by |
|---|---|---|---|
| `Amendment` | Pan | Pan, Adjust, Add, Split, Combine, Delete | *(not used at this time – reserved)* |
| `ViewAmendment` | Pan | Pan only (read-only) | CuredComponent (view-only mode) |
| `Drawing` | Draw | Draw, Erase, AddTemplate, Adjust, Delete | *(not used at this time – reserved)* |
| `SingleSelection` | Pan | Pan, Add | CuredComponent, CureComponent |

### CanvasMode Enum

`Pan` · `Add` · `Adjust` · `Draw` · `Erase` · `Split` · `Combine` · `Delete` · `Mark` · `AddTemplate`

### Keyboard Shortcuts

| Key | Action |
|---|---|
| `Alt+Z` | Pan mode |
| `Alt+X` | Adjust mode |
| `Alt+A` | Add / AddTemplate mode |
| `Alt+S` | Split mode |
| `Alt+C` | Combine mode |
| `Alt+E` | Erase mode |
| `Alt+D` | Delete mode |
| `Alt+R` | Draw mode |
| `Alt+1–7` | Select drawing template |
| `Delete` | Delete selected box |
| `Space` (hold) | Temporary pan |
| `Shift+click+drag` | Draw box (works in any mode) |

### Key Public Methods (called by parent via @ViewChild)

| Method | What it does |
|---|---|
| `setCanvasImage(imageData)` | Sets background image from base64/URL |
| `addRectangles(rects[])` | Batch-add rectangles |
| `removeAllRects()` | Clear all rectangles |
| `clearCanvas()` | Clear everything |
| `hardReset()` | Clear + re-init wheel zoom |
| `zoomIn()` / `zoomOut()` | Zoom by 1.3× |
| `forceZoomOut(zoom?)` | Set exact zoom level |
| `resetCanvasSelection()` | Deselect all |
| `getCanvas()` | Returns raw `fabric.Canvas` |
| `setCanvasSize()` | Auto-size to container width |
| `forceCanvasSize()` | Force exact dimensions |
| `updateLines(lines)` | Overlay line-number labels |
| `combineBoxes(rects)` | Merge multiple rects into one |
| `fillBox(rect, color)` | Change box color state (Regular/Delete/Mark) |

### Box Color States

| State | Fill | Stroke |
|---|---|---|
| Regular | `rgba(33,150,243,0.2)` | `#2196F3` (blue) |
| Delete | `rgba(244,67,54,0.2)` | `#F44336` (red) |
| Mark | `rgba(255,235,59,0.3)` | `#FFC107` (yellow) |

### Drawing Behavior

- **Add mode / Shift+drag:** Click origin → drag → release creates a rect. Min size 7px enforced.
- **Pan mode:** Click+drag moves viewport. Space key enables temporary pan in any mode.
- **Split mode:** Hover shows vertical split line, click splits box into left/right halves.
- **Combine mode:** Click boxes to mark (yellow), then trigger combine via parent.
- **Delete mode:** Hover turns box red, click removes it.

---

## 3. AnnotationCanvasComponent (standalone)

**File:** `components/yolo-training/annotation-canvas/annotation-canvas.component.ts`
**Selector:** `<app-annotation-canvas>`
**Declared in:** `YoloTrainingModule`

Self-contained annotation canvas for YOLO dataset creation. Does **not** wrap `<fabric-canvas>` — it creates its own `fabric.Canvas` internally but uses `CanvasBoxService` for box creation and zoom.

### Inputs / Outputs

```ts
@Input() datasetName: string;     // target dataset name for saving
@Input() classes: YoloClass[];    // available annotation classes

@Output() saved:     EventEmitter<void>;   // after successful save
@Output() cancelled: EventEmitter<void>;   // user cancelled
```

### Features

| Feature | Details |
|---|---|
| **Box drawing** | Shift+click+drag to create. Color per class. Min 10×10px. |
| **Zoom** | Ctrl+wheel / pinch (0.1×–5×). Also `+`/`-`/`0` keys. |
| **Pan** | Space+click, middle-mouse, or toggle pan-mode button. |
| **Class selection** | Number keys `1–4`, or click class chip. Box color follows class. |
| **Image queue** | Upload multiple images, switch between them, per-image annotations preserved. |
| **PDF support** | Upload PDF → page selector (±5 page window) → convert pages to images. |
| **Dataset browser** | View/edit/delete previously saved images + annotations. |
| **Train/Val split** | Toggle between `train` and `val` split before saving. |

### Keyboard Shortcuts

| Key | Action |
|---|---|
| `Delete` / `Backspace` | Delete selected annotation |
| `Escape` | Deselect |
| `1–4` | Select class |
| `+` | Zoom in |
| `-` | Zoom out |
| `0` | Reset zoom |
| `Space` (hold) | Temporary pan |
| `Shift+click+drag` | Draw annotation box |

### Coordinate System & YOLO Format

Annotations are stored internally in pixel coordinates on the canvas. On save they are converted to **YOLO normalized format**:

```
x_center  = (rect_center_x - image_left) / (image_width × scale) / original_image_width
y_center  = (rect_center_y - image_top)  / (image_height × scale) / original_image_height
width     = rect_width  / (image_width × scale)  / original_image_width
height    = rect_height / (image_height × scale) / original_image_height
```

All values are in range `[0, 1]` relative to the original image dimensions.

**Saved annotation shape:**
```ts
{ class_id: number, x_center: number, y_center: number, width: number, height: number }
```

### Class Colors

Defined in `models/yolo-training.ts` via `CLASS_COLORS` map and `getClassColor()`:

| Class | Color |
|---|---|
| `entry` | `#0000FF` (blue) |
| `subentry` | `#00FFFF` (cyan) |
| `guidewords` | `#808080` (gray) |
| *(other)* | `#00FF00` (green) |

Box fill = class color + `'33'` (hex alpha for ~20% opacity).

---

## 4. Parent Components That Use Canvas

### CuredComponent (`/cured`, `/training-data`)

**File:** `components/cure-d/cured.component.ts`

```html
<fabric-canvas #canvas
  [canvasType]="canvasType"
  (modeChange)="modeChanged($event)"
  (selectionChange)="boxSelectionChanged($event)"
  (boxAdded)="boxAdded($event)"
  (boxDeleted)="boxDeleted($event)">
</fabric-canvas>
```

- Default `canvasType = CanvasType.SingleSelection`
- Switches to `CanvasType.ViewAmendment` when opened in view-only mode
- Accesses canvas via `@ViewChild('canvas') canvas: FabricCanvasComponent`
- Calls `setCanvasImage()`, `addRectangles()`, `removeAllRects()`, `zoomIn/Out()`

### CureComponent (`/cure`)

**File:** `components/cure/cure.component.ts`

```html
<fabric-canvas #canvas
  [canvasType]="canvasType"
  (selectionChange)="onBoxSelectionChanged($event)"
  (boxAdded)="onBoxAdded($event)">
</fabric-canvas>
```

- Always `canvasType = CanvasType.SingleSelection`
- User draws a single selection box to crop region for ML detection
- Detection results rendered as read-only boxes color-coded by confidence:
  - High (>90%): `rgb(76,175,80)` green
  - Medium (70–90%): `rgb(255,193,7)` amber
  - Low (<70%): `rgb(244,67,54)` red

### YoloTrainingComponent (`/yolo-training`)

**File:** `components/yolo-training/yolo-training.component.ts`

```html
<app-annotation-canvas
  [datasetName]="annotationDataset"
  [classes]="annotationClasses"
  (saved)="onAnnotationSaved()"
  (cancelled)="onAnnotationCancelled()">
</app-annotation-canvas>
```

- Passes dataset name and class list
- Listens to save/cancel events to refresh dataset list

---

## 5. Shared Patterns

### Box Drawing
All canvases use the same interaction: **Shift + click + drag** to draw a new bounding box. This is consistent across every canvas in the app.

### Zoom & Pan
All canvases delegate to `CanvasBoxService.setupWheelZoomPan()`:
- **Ctrl + wheel** = zoom
- **Plain wheel** = vertical pan (scroll)
- **Trackpad pinch** = zoom (detected via `ctrlKey + small deltaY`)
- **Space + drag** = temporary pan mode

### Module Registration
- `FabricCanvasModule` is imported by `CureModule` and `CuredModule`
- `AnnotationCanvasComponent` is declared directly in `YoloTrainingModule`
- All are imported in the root `AppModule`

### Minimum Box Sizes
- `FabricCanvasComponent`: 7px (via `CanvasBoxService.isValidBoxSize`)
- `AnnotationCanvasComponent`: 10×10px (hardcoded check)
