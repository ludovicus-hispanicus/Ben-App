import { Injectable } from '@angular/core';
import { fabric } from 'fabric';

export interface BoxConfig {
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  cornerSize?: number;
  cornerColor?: string;
  cornerStrokeColor?: string;
  data?: any;
}

export interface ZoomPanConfig {
  minZoom: number;
  maxZoom: number;
}

/**
 * Shared service for canvas box operations.
 * Used by both CuReD (fabric-canvas) and YOLO annotation canvas.
 */
@Injectable({
  providedIn: 'root'
})
export class CanvasBoxService {

  private defaultBoxConfig: BoxConfig = {
    fill: 'rgba(0,0,255,0.2)',  // Slightly more visible fill (matching YOLO style)
    stroke: '#2196F3',          // Material blue for better visibility
    strokeWidth: 2,             // Thicker stroke like YOLO
    cornerSize: 12,
    cornerColor: '#2196F3',
    cornerStrokeColor: '#1565C0'
  };

  /**
   * Create a rectangle with consistent styling and behavior
   */
  createBox(
    left: number,
    top: number,
    width: number,
    height: number,
    config: BoxConfig = {}
  ): fabric.Rect {
    const mergedConfig = { ...this.defaultBoxConfig, ...config };

    const rect = new fabric.Rect({
      left,
      top,
      width,
      height,
      originX: 'left',
      originY: 'top',
      angle: 0,
      fill: mergedConfig.fill,
      stroke: mergedConfig.stroke,
      strokeWidth: mergedConfig.strokeWidth,
      strokeUniform: true,
      transparentCorners: false,
      cornerSize: mergedConfig.cornerSize,
      cornerColor: mergedConfig.cornerColor,
      cornerStrokeColor: mergedConfig.cornerStrokeColor,
      borderColor: 'transparent',
      cornerStyle: 'circle',
      padding: 0,
      borderScaleFactor: 0,
      lockRotation: true,
      hasRotatingPoint: false,
      selectionBackgroundColor: 'rgba(0,255,0,0.3)',
      data: mergedConfig.data
    });

    // Disable rotation control, keep all resize handles
    rect.setControlsVisibility({
      mtr: false,  // no rotation
      ml: true,    // middle left
      mr: true,    // middle right
      mt: true,    // middle top
      mb: true,    // middle bottom
      tl: true,    // top left corner
      tr: true,    // top right corner
      bl: true,    // bottom left corner
      br: true     // bottom right corner
    });

    return rect;
  }

  /**
   * Setup wheel zooming and panning for a canvas.
   * - Ctrl + mouse wheel = zoom
   * - Pinch gesture = zoom
   * - Plain mouse wheel = pan vertically
   * - Two-finger scroll = pan
   *
   * Detection logic:
   * - Pinch gestures: ctrlKey=true, small deltaY, no deltaX
   * - Two-finger scroll: may have ctrlKey=true on some trackpads, but has deltaX or larger deltaY
   * - We use deltaX presence and deltaY magnitude to distinguish
   */
  setupWheelZoomPan(canvas: fabric.Canvas, config: ZoomPanConfig): void {
    canvas.on('mouse:wheel', (opt) => {
      const evt = opt.e as WheelEvent;
      evt.preventDefault();
      evt.stopPropagation();

      // Detect if this is likely a pinch gesture vs two-finger scroll
      // Pinch: ctrlKey=true, deltaX=0, small deltaY (typically < 10)
      // Two-finger scroll: may have ctrlKey, has deltaX OR larger deltaY
      const hasHorizontalMovement = Math.abs(evt.deltaX) > 0;
      const hasLargeVerticalMovement = Math.abs(evt.deltaY) > 50;
      const isLikelyTwoFingerScroll = hasHorizontalMovement || hasLargeVerticalMovement;

      // Zoom only on Ctrl+wheel when it's NOT a two-finger scroll pattern
      if ((evt.ctrlKey || evt.metaKey) && !isLikelyTwoFingerScroll) {
        const delta = evt.deltaY;
        let zoom = canvas.getZoom();
        zoom *= 0.99 ** delta;
        zoom = this.clampZoom(zoom, config);
        canvas.zoomToPoint({ x: evt.offsetX, y: evt.offsetY } as fabric.Point, zoom);
        return;
      }

      // Everything else = pan (two-finger scroll, plain wheel, etc.)
      const vpt = canvas.viewportTransform;
      if (vpt) {
        vpt[4] -= evt.deltaX;
        vpt[5] -= evt.deltaY;
        canvas.setViewportTransform(vpt);
      }
    });
  }

  /**
   * Setup mouse drag panning (for use with space key or pan mode)
   */
  setupMouseDragPan(
    canvas: fabric.Canvas,
    isPanningFn: () => boolean,
    getLastPos: () => { x: number; y: number } | null,
    setLastPos: (pos: { x: number; y: number } | null) => void
  ): void {
    canvas.on('mouse:move', (opt) => {
      if (!isPanningFn()) return;

      const lastPos = getLastPos();
      if (!lastPos) return;

      const evt = opt.e as MouseEvent;
      const vpt = canvas.viewportTransform;
      if (vpt) {
        vpt[4] += evt.clientX - lastPos.x;
        vpt[5] += evt.clientY - lastPos.y;
        canvas.setViewportTransform(vpt);
      }
      setLastPos({ x: evt.clientX, y: evt.clientY });
    });
  }

  /**
   * Clamp zoom level to min/max bounds
   */
  clampZoom(zoom: number, config: ZoomPanConfig): number {
    if (zoom > config.maxZoom) return config.maxZoom;
    if (zoom < config.minZoom) return config.minZoom;
    return zoom;
  }

  /**
   * Zoom in by a factor
   */
  zoomIn(canvas: fabric.Canvas, config: ZoomPanConfig, factor: number = 1.2): number {
    let zoom = canvas.getZoom() * factor;
    zoom = this.clampZoom(zoom, config);
    canvas.setZoom(zoom);
    return zoom;
  }

  /**
   * Zoom out by a factor
   */
  zoomOut(canvas: fabric.Canvas, config: ZoomPanConfig, factor: number = 1.2): number {
    let zoom = canvas.getZoom() / factor;
    zoom = this.clampZoom(zoom, config);
    canvas.setZoom(zoom);
    return zoom;
  }

  /**
   * Reset zoom to fit content
   */
  resetZoom(
    canvas: fabric.Canvas,
    canvasWidth: number,
    canvasHeight: number,
    imageWidth: number,
    imageHeight: number
  ): number {
    const zoom = Math.min(
      canvasWidth / imageWidth,
      canvasHeight / imageHeight
    ) * 0.95;
    canvas.setZoom(zoom);
    canvas.setViewportTransform([zoom, 0, 0, zoom, 0, 0]);
    return zoom;
  }

  /**
   * Check if a box meets minimum size requirements
   */
  isValidBoxSize(rect: fabric.Rect, minSize: number = 7): boolean {
    return rect.getScaledWidth() >= minSize && rect.getScaledHeight() >= minSize;
  }
}
