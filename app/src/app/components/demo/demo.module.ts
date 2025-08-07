import { NgModule } from "@angular/core";
import { MatButtonModule } from "@angular/material/button";
import { BrowserModule } from "@angular/platform-browser";
import { AmendmentModule } from "../amendment/amendment.module";


import { MatSelectModule } from '@angular/material/select';
import { MatAutocompleteModule } from '@angular/material/autocomplete'
import { MatOptionModule } from "@angular/material/core";
import { ReactiveFormsModule } from "@angular/forms";
import { MatInputModule } from '@angular/material/input';
import { FormsModule } from '@angular/forms';

import { DragDropModule } from "@angular/cdk/drag-drop";
import { MatIconModule } from "@angular/material/icon";
import { MatTooltipModule } from "@angular/material/tooltip";
import { FabricCanvasModule } from "../fabric-canvas/fabric-canvas.module";
import { DemoComponent } from "./demo.component";
import { MatProgressSpinnerModule } from "@angular/material/progress-spinner";
import { MatButtonToggleModule } from "@angular/material/button-toggle";
import { DemoDialogContentModule } from "./dialog-content/demo-dialog-content.module";


@NgModule({
    imports: [
        BrowserModule,
        MatButtonModule,
        FabricCanvasModule,
        ReactiveFormsModule,
        MatAutocompleteModule,
        MatSelectModule,
        MatOptionModule,
        MatInputModule,
        MatProgressSpinnerModule,
        FormsModule,
        DragDropModule,
        MatIconModule,
        MatTooltipModule,
        MatButtonToggleModule,
        AmendmentModule,
        DemoDialogContentModule
    ],
    declarations: [
        DemoComponent
    ],
    exports: [DemoComponent],
    providers: [],
 })
 
 export class DemoModule {
 }