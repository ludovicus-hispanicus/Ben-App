import { NgModule } from "@angular/core";
import { MatButtonModule } from "@angular/material/button";
import { MatDialogModule } from "@angular/material/dialog";
import { PdfViewerModule } from 'ng2-pdf-viewer';
import { BrowserModule } from "@angular/platform-browser";
import { FabricCanvasModule } from "../fabric-canvas/fabric-canvas.module";
import { MatIconModule } from "@angular/material/icon";
import { MatProgressSpinnerModule } from "@angular/material/progress-spinner";
import { FormsModule } from "@angular/forms";
import { TextSelectorModule } from "../common/text-selector/text-selector.module";
import { TextCreatorModule } from "../common/text-creator/text-creator.module";
import { TextEditorComponent } from "./text-editor/text-editor.component";
import { DragDropModule } from "@angular/cdk/drag-drop";
import { AmendmentModule } from "../amendment/amendment.module";
import { CuredComponent } from "./cured.component";
import { MatDividerModule } from "@angular/material/divider";
import { MatTooltipModule } from "@angular/material/tooltip";
import { KeyboardShortcutsModule } from "ng-keyboard-shortcuts";
import { MatMenuModule } from "@angular/material/menu";
import { MatButtonToggleModule } from "@angular/material/button-toggle";
import { MatFormFieldModule } from "@angular/material/form-field";
import { MatInputModule } from "@angular/material/input";
import { MatAutocompleteModule } from "@angular/material/autocomplete";
import { MatSelectModule } from "@angular/material/select";
import { ReactiveFormsModule } from "@angular/forms";


@NgModule({
    imports: [
        BrowserModule,
        MatDialogModule,
        MatButtonModule,
        PdfViewerModule,
        FabricCanvasModule,
        MatProgressSpinnerModule,
        MatIconModule,
        MatTooltipModule,
        FormsModule,
        ReactiveFormsModule,
        TextSelectorModule,
        TextCreatorModule,
        DragDropModule,
        MatDividerModule,
        AmendmentModule,
        MatTooltipModule,
        MatMenuModule,
        MatButtonToggleModule,
        MatFormFieldModule,
        MatInputModule,
        MatAutocompleteModule,
        MatSelectModule,
        KeyboardShortcutsModule.forRoot()
    ],
    declarations: [
        CuredComponent,
        TextEditorComponent
    ],
    exports: [
        CuredComponent,
        TextEditorComponent
    ],
    providers: [],
})

export class PdfUploaderModule {
}