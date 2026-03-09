# Image Canvas Architecture

This document describes the three separate image viewing/manipulation implementations in the BEn-app codebase.

## Overview

There are **3 distinct image handling locations**, each with different underlying technology:

| Location | Route | Technology | Shared Service |
|----------|-------|------------|----------------|
| Production (CuReD) | `/cured` | HTML img + CSS transforms | No |
| Training Data | `/training-data` | Fabric.js canvas | Yes |
| YOLO Annotation | `/training` (YOLO tab) | Fabric.js canvas | Yes |

---

## 1. ProductionComponent (Simple Image Viewer)

**Route:** `/cured`, `/cured?productionId=...`

**Files:**
- `app/src/app/components/production/production.component.ts`
- `app/src/app/components/production/production.component.html`
- `app/src/app/components/production/production.component.scss`

**Technology:** Simple HTML `<img>` tag with CSS transforms (NO Fabric.js)

### Key Properties
```typescript
// Zoom level (CSS scale transform)
imageZoom: number = 1;

// Pan state
isPanning: boolean = false;
panStartX: number = 0;
panStartY: number = 0;
scrollStartX: number = 0;
scrollStartY: number = 0;
```

### Key Methods

| Method | Location | Description |
|--------|----------|-------------|
| `onImageWheel()` | Line ~733 | Handles wheel events - two-finger scroll = pan, Ctrl+wheel = zoom |
| `zoomIn()` | Line ~717 | Increases `imageZoom` by 0.25 (max 4) |
| `zoomOut()` | Line ~723 | Decreases `imageZoom` by 0.25 (min 0.25) |
| `resetZoom()` | Line ~729 | Resets `imageZoom` to 1 |
| `onPanStart()` | Line ~767 | Starts click-drag panning |
| `onPanMove()` | Line ~762 | Handles pan movement |
| `onPanEnd()` | Line ~773 | Ends panning |

### Template Binding (production.component.html ~152-165)
```html
<div class="source-image-container"
     (wheel)="onImageWheel($event)"
     (mousedown)="onPanStart($event)"
     (mousemove)="onPanMove($event)"
     (mouseup)="onPanEnd()"
     (mouseleave)="onPanEnd()">
    <img [style.transform]="'scale(' + imageZoom + ')'" ...>
</div>
```

### How Zoom/Pan Works
- **Zoom:** CSS `transform: scale(imageZoom)` on the `<img>` element
- **Pan:** Native scroll on the container (`scrollLeft`, `scrollTop`)

---

## 2. FabricCanvasComponent (Training Data / CuReD Editor)

**Routes:** `/training-data`, `/training-data/editor`

**Files:**
- `app/src/app/components/fabric-canvas/fabric-canvas.component.ts`
- `app/src/app/components/fabric-canvas/fabric-canvas.component.html`
- `app/src/app/components/cure-d/cured.component.ts` (parent that uses it)
- `app/src/app/services/canvas-box.service.ts` (shared gesture handling)

**Technology:** Fabric.js canvas

### Key Properties
```typescript
private canvas: fabric.Canvas;
private wheelZoomSetup = false;

// Pan/zoom state
private spacePressed = false;
private isPanning = false;
private lastPanPosition: { x: number; y: number } | null = null;
private isDrawingBox = false;
private drawStart: { x: number; y: number } | null = null;
```

### Key Methods

| Method | Location | Description |
|--------|----------|-------------|
| `initAll()` | Line ~296 | Initializes Fabric canvas, calls `setWheelZooming()` |
| `setWheelZooming()` | Line ~378 | Sets up wheel zoom/pan via shared service |
| `setFreeHandMode()` | Line ~425 | Sets up mouse handlers for pan mode |
| `onFreeHandMouseDown()` | Line ~454 | Handles mouse down - shift+click = draw, click = pan |
| `onFreeHandMouseMove()` | Line ~488 | Handles mouse move for pan/draw |
| `onFreeHandMouseUp()` | Line ~510 | Finalizes pan/draw operation |
| `zoomIn()` / `zoomOut()` | Line ~366-375 | Button-triggered zoom |
| `forceZoomOut()` | Line ~359 | Resets viewport transform |

### Gesture Behavior
- **Two-finger scroll:** Pan (via shared service)
- **Ctrl + wheel / Pinch:** Zoom (via shared service)
- **Plain click + drag:** Pan
- **Shift + click + drag:** Draw new bounding box
- **Space + click + drag:** Pan
- **Middle mouse + drag:** Pan

### Uses Shared Service
```typescript
// In setWheelZooming():
this.canvasBoxService.setupWheelZoomPan(this.canvas, {
  minZoom: this.props.minZoom,
  maxZoom: this.props.maxZoom
});
```

---

## 3. AnnotationCanvasComponent (YOLO Training)

**Route:** `/training` (inside YOLO tab)

**Files:**
- `app/src/app/components/yolo-training/annotation-canvas/annotation-canvas.component.ts`
- `app/src/app/components/yolo-training/annotation-canvas/annotation-canvas.component.html`
- `app/src/app/services/canvas-box.service.ts` (shared gesture handling)

**Technology:** Fabric.js canvas (built directly, not using FabricCanvasComponent)

### Key Properties
```typescript
private canvas: fabric.Canvas;
private currentImage: fabric.Image | null = null;

// Pan/zoom state
private spacePressed = false;
private panModeActive = false;
private isPanning = false;
private lastPanPosition: { x: number; y: number } | null = null;
private isDrawing = false;
private drawStart: { x: number; y: number } | null = null;
```

### Key Methods

| Method | Location | Description |
|--------|----------|-------------|
| `initCanvas()` | Line ~230 | Initializes canvas, sets up wheel zoom via shared service |
| `onMouseDown()` | Line ~742 | Handles mouse down - shift+click = draw, click = pan |
| `onMouseMove()` | Line ~793 | Handles mouse move for pan/draw |
| `onMouseUp()` | Line ~824 | Finalizes pan/draw operation |

### Gesture Behavior
Same as FabricCanvasComponent (uses same shared service):
- **Two-finger scroll:** Pan
- **Ctrl + wheel / Pinch:** Zoom
- **Plain click + drag:** Pan
- **Shift + click + drag:** Draw new annotation box
- **Space + click + drag:** Pan

### Uses Shared Service
```typescript
// In initCanvas():
this.canvasBoxService.setupWheelZoomPan(this.canvas, {
  minZoom: this.minZoom,
  maxZoom: this.maxZoom
});
```

---

## Shared Service: CanvasBoxService

**File:** `app/src/app/services/canvas-box.service.ts`

This service provides consistent gesture handling for all Fabric.js canvases.

### Key Method: `setupWheelZoomPan()`

```typescript
setupWheelZoomPan(canvas: fabric.Canvas, config: ZoomPanConfig): void {
  canvas.on('mouse:wheel', (opt) => {
    const evt = opt.e as WheelEvent;
    evt.preventDefault();
    evt.stopPropagation();

    // Detect pinch vs two-finger scroll
    const hasHorizontalMovement = Math.abs(evt.deltaX) > 0;
    const hasLargeVerticalMovement = Math.abs(evt.deltaY) > 50;
    const isLikelyTwoFingerScroll = hasHorizontalMovement || hasLargeVerticalMovement;

    // Ctrl+wheel (not two-finger scroll) = zoom
    if ((evt.ctrlKey || evt.metaKey) && !isLikelyTwoFingerScroll) {
      // Zoom logic...
      return;
    }

    // Everything else = pan
    const vpt = canvas.viewportTransform;
    if (vpt) {
      vpt[4] -= evt.deltaX;
      vpt[5] -= evt.deltaY;
      canvas.setViewportTransform(vpt);
    }
  });
}
```

### Other Methods
- `createBox()` - Creates consistent styled bounding boxes
- `setupMouseDragPan()` - Sets up click-drag panning
- `clampZoom()` - Clamps zoom to min/max bounds
- `zoomIn()` / `zoomOut()` - Programmatic zoom
- `resetZoom()` - Reset to fit content
- `isValidBoxSize()` - Check minimum box size

---

## Unified Gesture Behavior

All three implementations now follow the same gesture conventions:

| Gesture | Action |
|---------|--------|
| Two-finger scroll (trackpad) | Pan |
| Plain mouse wheel | Pan |
| Ctrl + mouse wheel | Zoom |
| Cmd + mouse wheel (Mac) | Zoom |
| Pinch gesture | Zoom |
| Click + drag (empty area) | Pan |
| Shift + click + drag | Draw box (Fabric.js canvases only) |
| Space + click + drag | Pan |
| Middle mouse + drag | Pan |

---

## Quick Reference: Which File to Modify

| Task | File(s) |
|------|---------|
| Change Production image zoom/pan | `production.component.ts` → `onImageWheel()`, `onPanStart/Move/End()` |
| Change Training Data canvas behavior | `fabric-canvas.component.ts` → `onFreeHandMouse*()` methods |
| Change YOLO annotation behavior | `annotation-canvas.component.ts` → `onMouse*()` methods |
| Change wheel gesture detection (all Fabric canvases) | `canvas-box.service.ts` → `setupWheelZoomPan()` |
| Change box styling | `canvas-box.service.ts` → `createBox()` |

---

## Note on app/ vs app/

The `app/` folder is the older version. The `app/` folder is the newer refactored version. Both should be kept in sync for now. Key files exist in both:

- `app/src/app/components/fabric-canvas/fabric-canvas.component.ts`
- `app/src/app/services/canvas-box.service.ts`
- `app/src/app/components/fabric-canvas/fabric-canvas.component.ts`
- `app/src/app/services/canvas-box.service.ts`

The ProductionComponent only exists in `app/`.
