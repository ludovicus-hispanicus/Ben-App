import { Injectable } from '@angular/core';
import { GuideControlPoint, GuideLineData } from '../models/cured';

/**
 * Pure logic service for bezier guide lines on the CuReD canvas.
 * Handles SVG path building, serialization, and geometric operations.
 */
@Injectable({ providedIn: 'root' })
export class GuideLineService {

  /** Generate a unique ID for a new guide. */
  generateId(): string {
    return Math.random().toString(36).substring(2, 10);
  }

  /** Default color: semi-transparent fuchsia for reading. Fuchsia is rarely
   *  present in cuneiform tablet imagery (clay browns / orange-tinted
   *  lighting), so the guide stays visible across every photograph. */
  readonly DEFAULT_COLOR = 'rgba(255, 0, 255, 0.4)';
  readonly DEFAULT_STROKE_WIDTH = 20;

  /** Fixed common-color presets shown between the default fuchsia and the
   *  recent strip. Reading alpha (0.4) so the guide stays see-through over
   *  text; the user can dial transparency in the custom picker if they want
   *  a solid line for "done" markings. Order chosen to roughly follow the
   *  visible spectrum (red → purple) so the row reads as a colour ramp. */
  readonly COMMON_PRESETS: { color: string; label: string }[] = [
    { color: 'rgba(244, 67, 54, 0.4)',  label: 'Red' },
    { color: 'rgba(255, 152, 0, 0.4)',  label: 'Orange' },
    { color: 'rgba(255, 235, 59, 0.4)', label: 'Yellow' },
    { color: 'rgba(76, 175, 80, 0.4)',  label: 'Green' },
    { color: 'rgba(0, 188, 212, 0.4)',  label: 'Cyan' },
    { color: 'rgba(33, 150, 243, 0.4)', label: 'Blue' },
    { color: 'rgba(156, 39, 176, 0.4)', label: 'Purple' },
  ];

  /** localStorage key + cap for the user's recent-colors strip. The strip
   *  is MRU-ordered: a freshly picked color goes to the front; picking a
   *  color that already exists moves it to the front (not duplicated).
   *  The default fuchsia is never tracked here — it already has its own
   *  dedicated chip in the picker, so listing it twice would waste a slot. */
  private static readonly RECENT_KEY = 'guide_recent_colors';
  static readonly MAX_RECENT = 8;

  /** Return the user's recent guide colors (MRU first, max 5). */
  getRecentColors(): string[] {
    try {
      const raw = localStorage.getItem(GuideLineService.RECENT_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(c => typeof c === 'string').slice(0, GuideLineService.MAX_RECENT);
    } catch {
      return [];
    }
  }

  /** Move `color` to the front of the recent list (dedup, cap, persist).
   *  No-op for any color that already has a permanent chip (default fuchsia
   *  or one of the COMMON_PRESETS) — they'd waste a recent slot otherwise. */
  addRecentColor(color: string): void {
    if (!color || color === this.DEFAULT_COLOR) return;
    if (this.COMMON_PRESETS.some(p => p.color === color)) return;
    const current = this.getRecentColors().filter(c => c !== color);
    const next = [color, ...current].slice(0, GuideLineService.MAX_RECENT);
    try {
      localStorage.setItem(GuideLineService.RECENT_KEY, JSON.stringify(next));
    } catch {
      /* localStorage unavailable (private mode, quota) — silently drop */
    }
  }

  /**
   * Create a new guide from two endpoint clicks.
   * Returns a GuideLineData with auto-generated bezier handles at 1/3 and 2/3.
   */
  createGuide(startX: number, startY: number, endX: number, endY: number, color?: string, strokeWidth?: number): GuideLineData {
    const dx = endX - startX;
    const dy = endY - startY;
    const p0: GuideControlPoint = {
      x: startX, y: startY,
      cpAfter: { x: startX + dx / 3, y: startY + dy / 3 },
    };
    const p1: GuideControlPoint = {
      x: endX, y: endY,
      cpBefore: { x: endX - dx / 3, y: endY - dy / 3 },
    };
    return {
      id: this.generateId(),
      points: [p0, p1],
      color: color || this.DEFAULT_COLOR,
      strokeWidth: strokeWidth || this.DEFAULT_STROKE_WIDTH,
    };
  }

  /**
   * Build an SVG path string from control points.
   * Uses cubic bezier segments (C command) between consecutive points.
   */
  buildSvgPath(points: GuideControlPoint[]): string {
    if (points.length < 2) return '';
    let d = `M ${points[0].x} ${points[0].y}`;
    for (let i = 0; i < points.length - 1; i++) {
      const curr = points[i];
      const next = points[i + 1];
      // Control point 1: cpAfter of current (or midpoint fallback)
      const cp1 = curr.cpAfter || { x: (curr.x + next.x) / 2, y: (curr.y + next.y) / 2 };
      // Control point 2: cpBefore of next (or midpoint fallback)
      const cp2 = next.cpBefore || { x: (curr.x + next.x) / 2, y: (curr.y + next.y) / 2 };
      d += ` C ${cp1.x} ${cp1.y}, ${cp2.x} ${cp2.y}, ${next.x} ${next.y}`;
    }
    return d;
  }

  /**
   * Insert a new control point on a guide by splitting a segment.
   * Uses de Casteljau subdivision at parameter t (0–1) on the segment between points[segIndex] and points[segIndex+1].
   */
  splitSegment(guide: GuideLineData, segIndex: number, t: number = 0.5): GuideLineData {
    const pts = guide.points;
    if (segIndex < 0 || segIndex >= pts.length - 1) return guide;

    const p0 = pts[segIndex];
    const p3 = pts[segIndex + 1];
    const cp1 = p0.cpAfter || { x: (p0.x + p3.x) / 2, y: (p0.y + p3.y) / 2 };
    const cp2 = p3.cpBefore || { x: (p0.x + p3.x) / 2, y: (p0.y + p3.y) / 2 };

    // de Casteljau subdivision
    const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
    const lerpPt = (a: {x: number; y: number}, b: {x: number; y: number}, t: number) =>
      ({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) });

    const q0 = lerpPt(p0, cp1, t);
    const q1 = lerpPt(cp1, cp2, t);
    const q2 = lerpPt(cp2, p3, t);
    const r0 = lerpPt(q0, q1, t);
    const r1 = lerpPt(q1, q2, t);
    const s = lerpPt(r0, r1, t);  // the new on-curve point

    // Update existing points' handles
    const newP0: GuideControlPoint = { ...p0, cpAfter: q0 };
    const newMid: GuideControlPoint = { x: s.x, y: s.y, cpBefore: r0, cpAfter: r1 };
    const newP3: GuideControlPoint = { ...p3, cpBefore: q2 };

    const newPoints = [...pts];
    newPoints[segIndex] = newP0;
    newPoints[segIndex + 1] = newP3;
    newPoints.splice(segIndex + 1, 0, newMid);

    return { ...guide, points: newPoints };
  }

  /**
   * Find which segment of a guide is closest to a point, and the t parameter.
   * Returns { segIndex, t, distance }.
   */
  findClosestSegment(guide: GuideLineData, px: number, py: number, samples: number = 20): { segIndex: number; t: number; distance: number } {
    let bestSeg = 0, bestT = 0, bestDist = Infinity;
    for (let i = 0; i < guide.points.length - 1; i++) {
      const p0 = guide.points[i];
      const p3 = guide.points[i + 1];
      const cp1 = p0.cpAfter || { x: (p0.x + p3.x) / 2, y: (p0.y + p3.y) / 2 };
      const cp2 = p3.cpBefore || { x: (p0.x + p3.x) / 2, y: (p0.y + p3.y) / 2 };

      for (let s = 0; s <= samples; s++) {
        const t = s / samples;
        const it = 1 - t;
        const x = it*it*it*p0.x + 3*it*it*t*cp1.x + 3*it*t*t*cp2.x + t*t*t*p3.x;
        const y = it*it*it*p0.y + 3*it*it*t*cp1.y + 3*it*t*t*cp2.y + t*t*t*p3.y;
        const d = Math.sqrt((x - px) * (x - px) + (y - py) * (y - py));
        if (d < bestDist) {
          bestDist = d;
          bestSeg = i;
          bestT = t;
        }
      }
    }
    return { segIndex: bestSeg, t: bestT, distance: bestDist };
  }

  /** Nudge all points of a guide by dy pixels. */
  nudgeGuide(guide: GuideLineData, dy: number): GuideLineData {
    const newPoints = guide.points.map(p => ({
      ...p,
      y: p.y + dy,
      cpBefore: p.cpBefore ? { x: p.cpBefore.x, y: p.cpBefore.y + dy } : undefined,
      cpAfter: p.cpAfter ? { x: p.cpAfter.x, y: p.cpAfter.y + dy } : undefined,
    }));
    return { ...guide, points: newPoints };
  }
}
