import { NgModule } from "@angular/core";
import { CommonModule } from "@angular/common";
import { RouterModule } from "@angular/router";
import { MatButtonModule } from "@angular/material/button";
import { MatDialogModule } from "@angular/material/dialog";
import { PdfViewerModule } from 'ng2-pdf-viewer';
import { FabricCanvasModule } from "../fabric-canvas/fabric-canvas.module";
import { MatIconModule } from "@angular/material/icon";
import { MatProgressSpinnerModule } from "@angular/material/progress-spinner";
import { FormsModule } from "@angular/forms";
import { TextSelectorModule } from "../common/text-selector/text-selector.module";
import { TextCreatorModule } from "../common/text-creator/text-creator.module";
import { TextEditorModule } from "./text-editor/text-editor.module";
import { DragDropModule } from "@angular/cdk/drag-drop";
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
import { MatSliderModule } from "@angular/material/slider";
import { ReactiveFormsModule } from "@angular/forms";
import { MoveTextDialogComponent } from "../common/move-text-dialog/move-text-dialog.component";
import { PartDialogComponent } from "../common/part-dialog/part-dialog.component";


@NgModule({
    imports: [
        CommonModule,
        RouterModule,
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
        TextEditorModule,
        DragDropModule,
        MatDividerModule,
        MatTooltipModule,
        MatMenuModule,
        MatButtonToggleModule,
        MatFormFieldModule,
        MatInputModule,
        MatAutocompleteModule,
        MatSelectModule,
        MatSliderModule,
        KeyboardShortcutsModule.forRoot()
    ],
    declarations: [
        CuredComponent,
        MoveTextDialogComponent,
        PartDialogComponent,
    ],
    entryComponents: [
        MoveTextDialogComponent,
        PartDialogComponent,
    ],
    exports: [
        CuredComponent,
    ],
    providers: [],
})

export class PdfUploaderModule {
}