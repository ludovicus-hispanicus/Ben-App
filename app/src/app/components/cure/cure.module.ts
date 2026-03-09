import { NgModule } from "@angular/core";
import { CommonModule } from "@angular/common";
import { RouterModule } from "@angular/router";
import { FormsModule, ReactiveFormsModule } from "@angular/forms";
import { MatButtonModule } from "@angular/material/button";
import { MatDialogModule } from "@angular/material/dialog";
import { MatIconModule } from "@angular/material/icon";
import { MatProgressSpinnerModule } from "@angular/material/progress-spinner";
import { MatTooltipModule } from "@angular/material/tooltip";
import { MatSelectModule } from "@angular/material/select";
import { MatInputModule } from "@angular/material/input";
import { MatProgressBarModule } from "@angular/material/progress-bar";
import { PdfViewerModule } from "ng2-pdf-viewer";
import { FabricCanvasModule } from "../fabric-canvas/fabric-canvas.module";
import { TextEditorModule } from "../cure-d/text-editor/text-editor.module";
import { CureComponent } from "./cure.component";

@NgModule({
    imports: [
        CommonModule,
        RouterModule,
        FormsModule,
        ReactiveFormsModule,
        MatButtonModule,
        MatDialogModule,
        MatIconModule,
        MatProgressSpinnerModule,
        MatTooltipModule,
        MatSelectModule,
        MatInputModule,
        MatProgressBarModule,
        PdfViewerModule,
        FabricCanvasModule,
        TextEditorModule,
    ],
    declarations: [
        CureComponent,
    ],
    exports: [
        CureComponent,
    ],
})
export class CureModule {}
