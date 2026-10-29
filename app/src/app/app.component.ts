import { Component, HostListener } from '@angular/core';
import { Title } from "@angular/platform-browser";
import { ToolbarService, ToolbarState } from './services/toolbar.service';
import { ModuleService } from './services/module.service';
import { Observable } from 'rxjs';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})
export class AppComponent {
  title = 'Babylonian Engine';
  toolbarState$: Observable<ToolbarState>;
  isLoading$: Observable<boolean>;
  enabledModules$: Observable<Record<string, boolean>>;

  // The desktop app (Electron) has no browser back button or history shortcuts,
  // so Alt+← and the mouse back button trigger the toolbar's back action there.
  // In a browser they are left alone: the browser's own back already applies.
  readonly isDesktop = !!(window as any).electronAPI || /Electron/i.test(navigator.userAgent);

  constructor(
    private titleService: Title,
    private toolbarService: ToolbarService,
    public moduleService: ModuleService
  ) {
    this.titleService.setTitle("Babylonian Engine");
    this.toolbarState$ = this.toolbarService.state$;
    this.isLoading$ = this.toolbarService.loading$;
    this.enabledModules$ = this.moduleService.enabledModules$;
  }

  @HostListener('document:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if (this.isDesktop && event.altKey && event.key === 'ArrowLeft') {
      this.goBack(event);
    }
  }

  @HostListener('document:mouseup', ['$event'])
  onMouseUp(event: MouseEvent): void {
    if (this.isDesktop && event.button === 3) {  // mouse "back" button
      this.goBack(event);
    }
  }

  private goBack(event: Event): void {
    const back = this.toolbarService.current.backAction;
    if (back) {
      event.preventDefault();
      back();
    }
  }
}
