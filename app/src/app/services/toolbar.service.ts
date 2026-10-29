import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface ToolbarButton {
  label: string;
  icon?: string;
  action: () => void;
  color?: 'primary' | 'accent' | 'warn' | 'pink' | 'default';
  disabled?: boolean;
}

export interface Breadcrumb {
  label: string;
  action?: () => void; // omitted for the current (last) crumb
}

export interface ToolbarState {
  buttons: ToolbarButton[];
  message?: string;
  backAction?: () => void;
  backLabel?: string; // destination shown next to the back arrow, e.g. "CUSAS-18"
  breadcrumbs?: Breadcrumb[];
}

@Injectable({
  providedIn: 'root'
})
export class ToolbarService {
  private stateSubject = new BehaviorSubject<ToolbarState>({ buttons: [] });
  private loadingSubject = new BehaviorSubject<boolean>(false);

  state$ = this.stateSubject.asObservable();
  loading$ = this.loadingSubject.asObservable();

  setToolbar(state: ToolbarState) {
    this.stateSubject.next(state);
  }

  setButtons(buttons: ToolbarButton[]) {
    const current = this.stateSubject.value;
    this.stateSubject.next({ ...current, buttons });
  }

  setMessage(message: string) {
    const current = this.stateSubject.value;
    this.stateSubject.next({ ...current, message });
  }

  setBackAction(action: (() => void) | undefined) {
    const current = this.stateSubject.value;
    this.stateSubject.next({ ...current, backAction: action });
  }

  /** Set the back button (with its destination label) and the breadcrumb trail. */
  setNavigation(back: { label: string; action: () => void } | undefined, breadcrumbs: Breadcrumb[] = []) {
    const current = this.stateSubject.value;
    this.stateSubject.next({
      ...current,
      backAction: back?.action,
      backLabel: back?.label,
      breadcrumbs,
    });
  }

  /** Current toolbar state (e.g. for keyboard / mouse back shortcuts). */
  get current(): ToolbarState {
    return this.stateSubject.value;
  }

  clearButtons() {
    this.stateSubject.next({ buttons: [] });
  }

  setLoading(loading: boolean) {
    this.loadingSubject.next(loading);
  }
}
