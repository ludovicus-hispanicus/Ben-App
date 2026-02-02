import { NgModule } from "@angular/core";
import { BrowserModule } from "@angular/platform-browser";
import { MatButtonModule } from "@angular/material/button";
import { AdminPanelComponent } from "./admin-panel.component";
import { MatIconModule } from "@angular/material/icon";
import { RouterModule } from "@angular/router";


@NgModule({
    imports: [
        BrowserModule,
        MatButtonModule,
        MatIconModule,
        RouterModule
    ],
    declarations: [AdminPanelComponent],
    exports: [],
    providers: [],
})

export class AdminPanelModule {
}
