import { Component } from '@angular/core';
import { Title } from "@angular/platform-browser";
import { ToolbarService, ToolbarState } from './services/toolbar.service';
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

  constructor(
    private titleService: Title,
    private toolbarService: ToolbarService
  ) {
    this.titleService.setTitle("Babylonian Engine");
    this.toolbarState$ = this.toolbarService.state$;
    this.isLoading$ = this.toolbarService.loading$;
  }
}
