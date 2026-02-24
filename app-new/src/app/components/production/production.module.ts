import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { PdfViewerModule } from 'ng2-pdf-viewer';

import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatChipsModule } from '@angular/material/chips';

import { ProductionComponent } from './production.component';
import { PdfUploaderModule } from '../cure-d/cured.module';
import { TextEditorModule } from '../cure-d/text-editor/text-editor.module';
import { FabricCanvasModule } from '../fabric-canvas/fabric-canvas.module';

@NgModule({
    declarations: [
        ProductionComponent
    ],
    imports: [
        CommonModule,
        FormsModule,
        ReactiveFormsModule,
        PdfViewerModule,
        MatIconModule,
        MatButtonModule,
        MatTooltipModule,
        MatFormFieldModule,
        MatInputModule,
        MatProgressSpinnerModule,
        MatChipsModule,
        PdfUploaderModule,
        TextEditorModule,
        FabricCanvasModule
    ],
    exports: [
        ProductionComponent
    ]
})
export class ProductionModule { }
