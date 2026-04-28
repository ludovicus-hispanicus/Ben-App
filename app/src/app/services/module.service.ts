import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface ModuleConfig {
  id: string;
  name: string;
  description: string;
  icon: string;
  core: boolean; // core modules cannot be disabled
  installed: boolean; // false → show Install button instead of toggle
}

export const APP_MODULES: ModuleConfig[] = [
  { id: 'cured', name: 'CuReD', description: 'OCR curation, training & text production', icon: 'auto_stories', core: true, installed: true },
  { id: 'library', name: 'Library', description: 'Document & image browser', icon: 'photo_library', core: true, installed: true },
  { id: 'cure', name: 'CuRe', description: 'Sign classifier editor', icon: 'gesture', core: false, installed: true },
  { id: 'yolo', name: 'Layout', description: 'YOLO layout detection & training', icon: 'grid_view', core: false, installed: true },
  { id: 'line_segmentation', name: 'Segmentation', description: 'Line segmentation annotation tool', icon: 'splitscreen', core: false, installed: true },
];

@Injectable({ providedIn: 'root' })
export class ModuleService {
  private enabledModules = new BehaviorSubject<Record<string, boolean>>({});
  enabledModules$ = this.enabledModules.asObservable();

  constructor(private http: HttpClient) {
    this.loadModules();
  }

  private loadModules(): void {
    this.http.get<Record<string, boolean>>(`${environment.apiUrl}/settings/modules`)
      .subscribe({
        next: (modules) => this.enabledModules.next(modules),
        error: () => {
          // Default: everything enabled
          const defaults: Record<string, boolean> = {};
          APP_MODULES.forEach(m => defaults[m.id] = true);
          this.enabledModules.next(defaults);
        }
      });
  }

  isEnabled(moduleId: string): boolean {
    return this.enabledModules.value[moduleId] !== false;
  }

  updateModules(modules: Record<string, boolean>): Observable<Record<string, boolean>> {
    const req = this.http.put<Record<string, boolean>>(
      `${environment.apiUrl}/settings/modules`,
      { modules }
    );
    req.subscribe({
      next: (updated) => this.enabledModules.next(updated),
    });
    return req;
  }
}
