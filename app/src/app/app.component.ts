import { Component, HostListener, NgZone, OnDestroy } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { Title } from "@angular/platform-browser";
import { ToolbarService, ToolbarState } from './services/toolbar.service';
import { ModuleService } from './services/module.service';
import { Observable, Subscription } from 'rxjs';
import { filter } from 'rxjs/operators';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnDestroy {
  title = 'Babylonian Engine';
  toolbarState$: Observable<ToolbarState>;
  isLoading$: Observable<boolean>;
  enabledModules$: Observable<Record<string, boolean>>;

  // The desktop app (Electron) has no browser back button or history shortcuts,
  // so Alt+← and the mouse back button trigger the toolbar's back action there.
  // In a browser they are left alone: the browser's own back already applies.
  readonly isDesktop = !!(window as any).electronAPI || /Electron/i.test(navigator.userAgent);

  // Right margin that lines up the back button + path with the right edge of the page's
  // middle column (the element marked data-nav-anchor). Measured, since pages differ.
  trailOffset = 0;
  private trailObserver?: ResizeObserver;
  private observedAnchor: Element | null = null;
  private subs = new Subscription();

  constructor(
    private titleService: Title,
    private toolbarService: ToolbarService,
    public moduleService: ModuleService,
    private router: Router,
    private zone: NgZone
  ) {
    this.titleService.setTitle("Babylonian Engine");
    this.toolbarState$ = this.toolbarService.state$;
    this.isLoading$ = this.toolbarService.loading$;
    this.enabledModules$ = this.moduleService.enabledModules$;

    // Re-align after the bar or the page has rendered
    this.subs.add(this.toolbarState$.subscribe(() => setTimeout(() => this.alignTrail())));
    this.subs.add(this.router.events.pipe(filter(e => e instanceof NavigationEnd))
      .subscribe(() => setTimeout(() => this.alignTrail())));
    if (typeof ResizeObserver !== 'undefined') {
      this.trailObserver = new ResizeObserver(() => this.zone.run(() => this.alignTrail()));
    }
  }

  ngOnDestroy(): void {
    this.subs.unsubscribe();
    this.trailObserver?.disconnect();
  }

  @HostListener('window:resize')
  alignTrail(): void {
    const toolbar = document.querySelector('.navbar-toolbar');
    const anchor = document.querySelector('.main-content [data-nav-anchor]');
    this.observeAnchor(anchor);
    if (!toolbar || !anchor) {
      this.trailOffset = 0;
      return;
    }
    const anchorRight = anchor.getBoundingClientRect().right
      - parseFloat(getComputedStyle(anchor).paddingRight || '0');
    // Never past Settings / About: at most the toolbar's own right edge
    this.trailOffset = Math.max(0, Math.round(toolbar.getBoundingClientRect().right - anchorRight));
  }

  private observeAnchor(anchor: Element | null): void {
    if (!this.trailObserver || anchor === this.observedAnchor) {
      return;
    }
    this.trailObserver.disconnect();
    this.observedAnchor = anchor;
    if (anchor) {
      this.trailObserver.observe(anchor);
      // The main column moves when its scrollbar appears or goes
      const main = document.querySelector('.main-content');
      if (main) {
        this.trailObserver.observe(main);
      }
    }
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
