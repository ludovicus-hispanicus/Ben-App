import { NgModule } from "@angular/core";
import { MatButtonModule } from "@angular/material/button";
import { BrowserModule } from "@angular/platform-browser";
import { FabricCanvasModule } from "../fabric-canvas/fabric-canvas.module";
import { AmendmentComponent, SettingsDialog } from "./amendment.component";
import { LetterViewerComponent } from "./letter-viewer/letter-viewer.component";
import { MatSelectModule } from '@angular/material/select';
import { MatAutocompleteModule } from '@angular/material/autocomplete'
import { MatOptionModule } from "@angular/material/core";
import { ReactiveFormsModule } from "@angular/forms";
import { MatInputModule } from '@angular/material/input';
import { FormsModule } from '@angular/forms';

import { MetaViewerComponent } from "./meta-viewer/meta-viewer.component";
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import { TextViewerComponent } from "./text-viewer/text-viewer.component";
import { LetterComponent } from "./text-viewer/letter/letter.component";
import { DragDropModule } from "@angular/cdk/drag-drop";
import { MatIconModule } from "@angular/material/icon";
import { MatTooltipModule } from "@angular/material/tooltip";
import { SmartSelectorModule } from "../common/smart-selector/smart-selector.module";
import { MatDialogModule } from "@angular/material/dialog";
import {MatSlideToggleModule} from '@angular/material/slide-toggle';
import { MatCardModule } from "@angular/material/card";
import { MatSliderModule } from "@angular/material/slider";
import { KeyboardShortcutsModule } from "ng-keyboard-shortcuts";
import { MatMenuModule } from '@angular/material/menu';

@NgModule({
    imports: [
        BrowserModule,
        FabricCanvasModule,
        ReactiveFormsModule,
        MatButtonModule,
        MatAutocompleteModule,
        MatSelectModule,
        MatOptionModule,
        MatInputModule,
        MatProgressSpinnerModule,
        DragDropModule,
        MatIconModule,
        MatTooltipModule,
        SmartSelectorModule,
        MatDialogModule,
        MatSlideToggleModule,
        MatCardModule,
        FormsModule,
        MatMenuModule,
        MatSliderModule,
        KeyboardShortcutsModule.forRoot()
    ],
    declarations: [AmendmentComponent, LetterViewerComponent, MetaViewerComponent, TextViewerComponent, LetterComponent, SettingsDialog
    ],
    exports: [AmendmentComponent, LetterViewerComponent, MetaViewerComponent, TextViewerComponent, LetterComponent],
    providers: [],
 })
 
 export class AmendmentModule {
 }