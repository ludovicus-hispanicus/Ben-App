import { NgModule } from "@angular/core";
import { BrowserModule } from "@angular/platform-browser";
import { MatButtonModule } from "@angular/material/button";
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import { AdminPanelComponent } from "./admin-panel.component";
import { MatTableModule } from "@angular/material/table";
import { MatInputModule } from "@angular/material/input";
import { MatFormFieldModule } from "@angular/material/form-field";
import { FormsModule } from "@angular/forms";
import {MatCheckboxModule} from '@angular/material/checkbox';
import { MatIconModule } from "@angular/material/icon";
import { MatTooltipModule } from "@angular/material/tooltip";


@NgModule({
    imports: [
        BrowserModule,
        MatButtonModule,
        MatProgressSpinnerModule,
        MatTableModule,
        MatFormFieldModule,
        MatInputModule,
        FormsModule,
        MatCheckboxModule,
        MatIconModule,
        MatTooltipModule
        ],
    declarations: [AdminPanelComponent],
    exports: [],
    providers: [],
 })
 
 export class AdminPanelModule {
 }