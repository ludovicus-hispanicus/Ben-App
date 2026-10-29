import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { forkJoin, Observable, of, ReplaySubject } from 'rxjs';
import { catchError } from 'rxjs/operators';
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
  { id: 'qwen', name: 'Qwen (local)', description: 'Qwen3-VL LoRA training & OCR on your own GPU', icon: 'smart_toy', core: false, installed: true },
];

@Injectable({ providedIn: 'root' })
export class ModuleService {
  // Emit only once loaded, so nothing shows a module before we know it exists
  private enabledModules = new ReplaySubject<Record<string, boolean>>(1);
  private installedModules = new ReplaySubject<Record<string, boolean>>(1);
  /** Usable modules: installed and switched on in Settings. */
  enabledModules$ = this.enabledModules.asObservable();
  /** Installed modules (their code and libraries are present). */
  installedModules$ = this.installedModules.asObservable();

  private preferences: Record<string, boolean> = {};
  private installed: Record<string, boolean> = {};
  private effective: Record<string, boolean> = {};

  constructor(private http: HttpClient) {
    this.loadModules();
  }

  private loadModules(): void {
    const allOn: Record<string, boolean> = {};
    APP_MODULES.forEach(m => allOn[m.id] = true);
    forkJoin({
      preferences: this.http.get<Record<string, boolean>>(`${environment.apiUrl}/settings/modules`)
        .pipe(catchError(() => of(allOn))),
      // An older backend without this route: treat everything as installed
      installed: this.http.get<Record<string, boolean>>(`${environment.apiUrl}/settings/modules/installed`)
        .pipe(catchError(() => of(allOn))),
    }).subscribe(({ preferences, installed }) => {
      this.installed = installed;
      this.installedModules.next(installed);
      this.publish(preferences);
    });
  }

  private publish(preferences: Record<string, boolean>): void {
    this.preferences = preferences;
    const effective: Record<string, boolean> = {};
    APP_MODULES.forEach(m => {
      effective[m.id] = this.installed[m.id] !== false && preferences[m.id] !== false;
    });
    this.effective = effective;
    this.enabledModules.next(effective);
  }

  /** Installed and switched on. */
  isEnabled(moduleId: string): boolean {
    return this.effective[moduleId] !== false;
  }

  /** The user's on/off choices from Settings (regardless of what is installed). */
  get modulePreferences(): Record<string, boolean> {
    return { ...this.preferences };
  }

  updateModules(modules: Record<string, boolean>): Observable<Record<string, boolean>> {
    const req = this.http.put<Record<string, boolean>>(
      `${environment.apiUrl}/settings/modules`,
      { modules }
    );
    req.subscribe({
      next: (updated) => this.publish(updated),
    });
    return req;
  }
}
