import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface ToolbarButton {
  label: string;
  icon?: string;
  action: () => void;
  color?: 'primary' | 'accent' | 'warn' | 'pink' | 'default';
  disabled?: boolean;
}

export interface ToolbarState {
  buttons: ToolbarButton[];
  message?: string;
  backAction?: () => void;
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

  clearButtons() {
    this.stateSubject.next({ buttons: [] });
  }

  setLoading(loading: boolean) {
    this.loadingSubject.next(loading);
  }
}
